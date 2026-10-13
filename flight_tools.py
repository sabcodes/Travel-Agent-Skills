"""Flight-only search, destination discovery, and offline filtering CLI."""
import argparse
import copy
import json
import math
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from flight_scanner import REGION_MAP, _duration_minutes, _fare_sort_key, generate_date_pairs_between, scan_flights

ROOT = Path(__file__).resolve().parent


def normalized(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return re.sub(r"[^a-z0-9]+", "_", "".join(c for c in value if not unicodedata.combining(c))).strip("_")


def load_pool(path):
    pool = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(pool, list) or not pool:
        raise ValueError("destination pool must be a nonempty JSON array")
    seen = set()
    for entry in pool:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not isinstance(entry.get("name"), str) or not entry["id"] or not entry["name"] or not isinstance(entry.get("airports"), list) or not entry["airports"]:
            raise ValueError("each destination needs id, name, and airports")
        if entry["id"] in seen:
            raise ValueError(f'duplicate destination id: {entry["id"]}')
        seen.add(entry["id"])
        if any(not isinstance(code, str) or not re.fullmatch(r"[A-Z]{3}", code) for code in entry["airports"]):
            raise ValueError(f'invalid airport code for {entry["id"]}')
        if not isinstance(entry.get("aliases", []), list) or any(not isinstance(alias, str) for alias in entry.get("aliases", [])):
            raise ValueError(f'aliases must be a list of names for {entry["id"]}')
    return pool


def select_destinations(pool, selection):
    if selection.casefold() == "all":
        return copy.deepcopy(pool)
    selected = []
    for token in selection.split(","):
        key = normalized(token)
        matches = [d for d in pool if key in {normalized(v) for v in [d["id"], d["name"], *d.get("aliases", [])]}]
        if not matches and key in REGION_MAP:
            matches = [d for d in pool if set(d["airports"]) & set(REGION_MAP[key])]
        if not matches and re.fullmatch(r"[A-Za-z]{3}", token.strip()):
            code = token.strip().upper()
            entry = next((d for d in pool if code in d["airports"]), None)
            matches = [{**entry, "airports": [code]}] if entry else [{"id": code.lower(), "name": code, "airports": [code]}]
        if not matches:
            raise ValueError(f"unknown destination: {token!r}; use the destinations command or an IATA code")
        for entry in matches:
            existing = next((d for d in selected if d["id"] == entry["id"]), None)
            if existing:
                existing["airports"] = list(dict.fromkeys(existing["airports"] + entry["airports"]))
            else:
                selected.append(copy.deepcopy(entry))
    return selected


def filter_fares(fares, *, airports=None, origins=None, max_price=None, max_stops=None,
                 max_duration_hours=None, max_layover_hours=None, airlines=None):
    selected_airlines = {name.strip().casefold() for name in airlines} if airlines else None
    result = []
    for fare in fares:
        if airports is not None and fare["destination"] not in airports:
            continue
        if origins is not None and fare["origin"] not in origins:
            continue
        if selected_airlines is not None:
            carriers = {name.strip().casefold() for name in fare.get("airline", "").split(",") if name.strip()}
            if not carriers or not carriers.issubset(selected_airlines):
                continue
        if max_price is not None and float(fare["price"]) > max_price:
            continue
        if max_stops is not None and (fare.get("stops") is None or fare["stops"] > max_stops):
            continue
        if max_duration_hours is not None and _duration_minutes(fare.get("total_journey_duration")) > max_duration_hours * 60:
            continue
        if max_layover_hours is not None:
            waits = fare.get("layovers")
            if waits is None or (fare.get("stops", 0) and len(waits) != fare["stops"]):
                continue
            if any(wait.get("duration_min", float("inf")) > max_layover_hours * 60 for wait in waits):
                continue
        result.append(fare)
    return sorted(result, key=_fare_sort_key)


def cell_key(record):
    return tuple(record[k] for k in ("origin", "destination", "departure_date", "return_date"))


def summarize(payload):
    """Compute the same minima and matrix from live or saved fares."""
    fares = sorted(payload["flight_deals"], key=_fare_sort_key)
    by_cell = {}
    for fare in fares:
        by_cell.setdefault(cell_key(fare), []).append(fare)
    for search in payload["searches"]:
        matches = by_cell.get(cell_key(search), [])
        search["matching_fare_count"] = len(matches)
        search["cheapest"] = matches[0] if matches else None
    manifest = payload["query"]
    matrix = []
    minima = []
    for origin in manifest["origins"]:
        for location in manifest["destinations"]:
            cells = []
            for dep, ret in manifest["date_pairs"]:
                records = [s for s in payload["searches"] if s["origin"] == origin and s["destination"] in location["airports"] and s["departure_date"] == dep and s["return_date"] == ret]
                matches = sorted([f for s in records for f in by_cell.get(cell_key(s), [])], key=_fare_sort_key)
                statuses = {s["status"] for s in records}
                failed = "unavailable" in statuses
                status = "partial" if matches and failed else "ok" if matches else "unavailable" if failed else "planned" if "planned" in statuses else "filtered_out" if any(s.get("fare_count", 0) for s in records) else "no_matching_fares"
                cells.append({"departure_date": dep, "return_date": ret, "status": status,
                              "fare_count": len(matches), "cheapest": matches[0] if matches else None})
            best = min((c["cheapest"] for c in cells if c["cheapest"]), key=_fare_sort_key, default=None)
            matrix.append({"origin": origin, "destination_id": location["id"], "destination_name": location["name"],
                           "airports": location["airports"], "gateway_note": location.get("gateway_note"),
                           "cells": cells, "cheapest": best})
            if best:
                minima.append(best)
    payload["flight_deals"] = fares
    payload["matrix"] = matrix
    payload["cheapest_by_destination"] = sorted(minima, key=_fare_sort_key)
    payload["cheapest"] = fares[0] if fares else None
    payload["summary"] = {"planned_searches": len(payload["searches"]),
                          "completed_searches": sum(s["status"] not in {"planned", "unavailable"} for s in payload["searches"]),
                          "failed_searches": sum(s["status"] == "unavailable" for s in payload["searches"]),
                          "total_flight_deals": len(fares)}
    return payload


def render_table(payload):
    windows = payload["query"]["date_pairs"]
    headings = ["Destination / origin", *[f"{dep} → {ret}" for dep, ret in windows], "Cheapest"]
    lines = ["| " + " | ".join(headings) + " |", "| " + " | ".join(["---"] * len(headings)) + " |"]
    for row in payload["matrix"]:
        values = []
        for cell in row["cells"]:
            best = cell["cheapest"]
            values.append(f'${best["price"]:,.2f}' + (" (partial)" if cell["status"] == "partial" else "") if best else cell["status"])
        best = row["cheapest"]
        cheapest = f'${best["price"]:,.2f} ({best["departure_date"]} → {best["return_date"]})' if best else "—"
        lines.append("| " + " | ".join([f'{row["destination_name"]} / {row["origin"]}', *values, cheapest]) + " |")
    warnings = payload.get("source_warnings", [])
    if warnings:
        carriers = sorted({name for warning in warnings for name in warning["airlines"]})
        lines.append("\nPrices unavailable for some returned itineraries: " + ", ".join(carriers) + ". These are excluded from fare comparisons.")
    attempts = payload.get("browser_attempts", [])
    if attempts:
        lines.append(f"\nBrowser retries: {len(attempts)} route/date checks; {sum(a['recovered'] for a in attempts)} quotes recovered; {sum(a['status'] == 'unavailable' for a in attempts)} failed or timed out.")
    return "\n".join(lines)


def add_filters(parser):
    parser.add_argument("--airlines", help="Comma-separated reported airline names; all carriers must match, case-insensitively")
    parser.add_argument("--max-price", type=float, help="Optional USD per-person round-trip ceiling; default unlimited")
    parser.add_argument("--max-stops", "--max-layovers", type=int, help="Maximum outbound connections; search also requests this limit on both directions")
    parser.add_argument("--max-duration-hours", type=float, help="Maximum outbound elapsed journey hours")
    parser.add_argument("--max-layover-hours", type=float, help="Maximum wait at any outbound connecting airport")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    destinations = commands.add_parser("destinations", help="List the selectable destination pool")
    destinations.add_argument("--pool", default=str(ROOT / "flight_destinations.json"))
    search = commands.add_parser("search", help="Fetch fresh fares for a deterministic date grid")
    search.add_argument("--start-date", required=True)
    search.add_argument("--end-date", required=True, help="Last allowed return-departure date")
    search.add_argument("--mode", choices=["lite", "deep"], default="lite")
    search.add_argument("--date-step-days", type=int, default=None, help="Departure spacing for either mode; default 5 for lite, 1 for deep")
    search.add_argument("--trip-lengths", default="6", help="Comma-separated inclusive calendar days, e.g. 5,6")
    search.add_argument("--pool", default=str(ROOT / "flight_destinations.json"))
    search.add_argument("--config", default=str(ROOT / "config.json"))
    search.add_argument("--dest", default="all", help="all, comma-separated destination ids/names, or IATA codes")
    search.add_argument("--origin", default="SFO", help="Comma-separated origin airport codes")
    search.add_argument("--dry-run", action="store_true", help="Emit the complete search plan without network requests")
    search.add_argument("--progress-json", action="store_true", help="Emit one structured progress event per lookup on stderr")
    search.add_argument("--browser-missing", action="store_true", help="Slower optional Playwright retry for unpriced itineraries only")
    search.add_argument("--browser-engine", choices=["chromium", "chrome"], default="chromium", help="Browser fallback engine; chrome uses installed Google Chrome")
    saved = commands.add_parser("filter", help="Filter and rank a saved search without network requests")
    saved.add_argument("--input", required=True)
    saved.add_argument("--dest", help="Saved destination ids/names or airport codes")
    saved.add_argument("--origin", help="Comma-separated origin airport codes")
    for command in (search, saved):
        add_filters(command)
        command.add_argument("--output", help="Save the full structured JSON snapshot")
        command.add_argument("--format", choices=["json", "table"], default="json", help="stdout format; --output always saves JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "destinations":
            print(json.dumps(load_pool(args.pool), indent=2, ensure_ascii=False))
            return 0
        limits = {name: getattr(args, name) for name in ("max_price", "max_stops", "max_duration_hours", "max_layover_hours")}
        for name, value in limits.items():
            if value is not None and (not math.isfinite(value) or value < 0 or (name == "max_price" and value == 0)):
                raise ValueError(f"{name.replace('_', '-')} must be finite and nonnegative (price must be positive)")
        airlines = list(dict.fromkeys(name.strip() for name in args.airlines.split(",") if name.strip())) if args.airlines else None
        if args.airlines and not airlines:
            raise ValueError("airlines must include at least one carrier name")
        limits["airlines"] = airlines
        origins = list(dict.fromkeys(code.strip().upper() for code in args.origin.split(","))) if args.origin else None
        if origins and any(not re.fullmatch(r"[A-Z]{3}", code) for code in origins):
            raise ValueError("origins must be three-letter IATA codes")
        if args.command == "search":
            step = args.date_step_days if args.date_step_days is not None else (1 if args.mode == "deep" else 5)
            lengths = sorted(set(int(v.strip()) for v in args.trip_lengths.split(",")))
            pairs = generate_date_pairs_between(args.start_date, args.end_date, lengths, step)
            selected = select_destinations(load_pool(args.pool), args.dest)
            airports = list(dict.fromkeys(code for d in selected for code in d["airports"]))
            payload = {"schema_version": 1, "checked_at": None if args.dry_run else datetime.now(timezone.utc).isoformat(),
                       "query": {"origins": origins, "destinations": selected, "start_date": args.start_date,
                                 "end_date": args.end_date, "mode": args.mode, "date_step_days": step,
                                 "trip_lengths": lengths, "date_pairs": pairs, "day_count": "inclusive",
                                 "currency": "USD", "cabin": "economy", "flight_passengers": 1,
                                 "price_basis": "per_person", "filters": limits},
                       "source_errors": [], "source_warnings": [], "browser_attempts": [], "searches": [], "flight_deals": [],
                       "limitations": ["Connection counts, waits, and durations describe outbound legs; selected return legs are unavailable.",
                                       "The end date bounds return departure, not final arrival back at the origin.",
                                       "Gateway fares exclude onward transport; prices can change before booking."]}
            payload["query"].update(browser_missing=args.browser_missing, browser_engine=args.browser_engine)
            if args.dry_run:
                payload["searches"] = [{"origin": o, "destination": a, "departure_date": dep, "return_date": ret,
                                        "status": "planned", "fare_count": 0} for o in origins for a in airports for dep, ret in pairs]
            else:
                payload["flight_deals"] = scan_flights(config_path=args.config, origins=origins, destinations=airports,
                    date_pairs=pairs, max_price=None, max_stops=args.max_stops,
                    source_errors=payload["source_errors"], source_warnings=payload["source_warnings"], search_records=payload["searches"],
                    browser_missing=args.browser_missing, browser_engine=args.browser_engine, browser_attempts=payload["browser_attempts"], browser_airlines=airlines,
                    progress_callback=(lambda event: print(json.dumps({"event": "progress", **event}), file=sys.stderr, flush=True)) if args.progress_json else None)
                for fare in payload["flight_deals"]:
                    location = next(d for d in selected if fare["destination"] in d["airports"])
                    fare["destination_name"] = location["name"]
                    fare["gateway_note"] = location.get("gateway_note")
        else:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
            if payload.get("schema_version") != 1 or "query" not in payload or "searches" not in payload:
                raise ValueError("input must be a flight_tools search snapshot (schema_version 1)")
            selected = select_destinations(payload["query"]["destinations"], args.dest) if args.dest else payload["query"]["destinations"]
            airports = list(dict.fromkeys(code for d in selected for code in d["airports"]))
            origins = origins or payload["query"]["origins"]
            if set(origins) - set(payload["query"]["origins"]) or set(airports) - {a for d in payload["query"]["destinations"] for a in d["airports"]}:
                raise ValueError("filters can select only airports present in the saved query")
            payload["query"]["destinations"] = selected
            payload["query"]["origins"] = origins
            payload["searches"] = [s for s in payload["searches"] if s["origin"] in origins and s["destination"] in airports]
            payload["source_errors"] = [e for e in payload["source_errors"] if e.get("origin") in origins and e.get("destination") in airports]
            payload["source_warnings"] = [w for w in payload.get("source_warnings", []) if w.get("origin") in origins and w.get("destination") in airports]
            payload["browser_attempts"] = [a for a in payload.get("browser_attempts", []) if a.get("origin") in origins and a.get("destination") in airports]
            payload["applied_filters"] = limits
        # Retain raw candidates so a later offline filter can relax previous local filters.
        raw = payload.get("raw_flight_deals", payload["flight_deals"])
        raw = filter_fares(raw, airports=airports, origins=origins)
        payload["raw_flight_deals"] = raw
        payload["flight_deals"] = filter_fares(raw, **limits)
        summarize(payload)
        if args.output:
            Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(render_table(payload) if args.format == "table" else json.dumps(payload, indent=2, ensure_ascii=False))
        return 1 if payload["source_errors"] else 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
