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

from flight_scanner import FlightLookupError, REGION_MAP, _duration_minutes, _fare_sort_key, generate_date_pairs_between, scan_flights, scan_route

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


def retry_missing_targets(payload, airlines=None):
    """Use only warning cells from the saved query, in their recorded order."""
    if payload.get("schema_version") != 1 or not isinstance(payload.get("query"), dict) or not isinstance(payload.get("searches"), list):
        raise ValueError("input must be a flight_tools search snapshot (schema_version 1)")
    query = payload["query"]
    if query.get("currency") != "USD" or query.get("cabin") != "economy" or query.get("flight_passengers") != 1:
        raise ValueError("browser retry supports saved one-adult USD economy searches")
    limits = payload.get("applied_filters", query["filters"])
    airlines = limits.get("airlines") if airlines is None else airlines
    if airlines is not None and (not isinstance(airlines, list) or any(not isinstance(name, str) for name in airlines)):
        raise ValueError("saved airline filters must be a list of names")
    selected = {name.strip().casefold() for name in airlines} if airlines else None
    airports = {a for d in query["destinations"] for a in d["airports"]}
    pairs = {tuple(pair) for pair in query["date_pairs"]}
    allowed = {cell_key(s) for s in payload["searches"] if s["origin"] in query["origins"] and s["destination"] in airports and (s["departure_date"], s["return_date"]) in pairs}
    targets = {}
    for warning in payload.get("source_warnings", []):
        key = cell_key(warning)
        if key not in allowed:
            continue
        for airport in key[:2]:
            if not isinstance(airport, str) or not re.fullmatch(r"[A-Z]{3}", airport):
                raise ValueError("saved airports must be three-letter IATA codes")
        for value in key[2:]:
            datetime.strptime(value, "%Y-%m-%d")
        if any(not isinstance(name, str) or not name.strip() or len(name) > 100 for name in warning["airlines"]):
            raise ValueError("saved warning carriers must be airline names")
        names = [name for name in warning["airlines"] if selected is None or name.casefold() in selected]
        if names:
            target = targets.setdefault(key, {**warning, "airlines": []})
            target["airlines"] = list(dict.fromkeys(target["airlines"] + names))
    return list(targets.values())


def retry_missing(payload, *, engine="native-chrome", progress=None, output=None):
    """Use only the selected browser for fixed warning cells and merge into saved fares."""
    if engine not in ("native-chrome", "chromium", "chrome"):
        raise ValueError("choose native Chrome, Chromium or headless Chrome")
    targets = retry_missing_targets(payload)
    if not targets:
        raise ValueError("No missing-price cases match the saved result filters")
    result = copy.deepcopy(payload)
    filters = result.get("applied_filters", result["query"]["filters"])
    live_stops = result["query"]["filters"].get("max_stops")
    if live_stops is not None and (isinstance(live_stops, bool) or not isinstance(live_stops, int) or live_stops < 0):
        raise ValueError("saved live connection limit must be a nonnegative whole number")
    raw = result.get("raw_flight_deals", result["flight_deals"])
    fields = ("origin", "destination", "departure_date", "return_date", "airline", "price", "legs")
    def fare_key(fare):
        return json.dumps({key: fare.get(key) for key in fields}, sort_keys=True)
    merged = {fare_key(fare): fare for fare in raw}
    result.setdefault("browser_attempts", [])
    result["retry_summary"] = {"total": len(targets), "completed": 0, "new_quotes": 0, "failed": 0}
    checked_at = datetime.now(timezone.utc).isoformat()
    def save():
        result["raw_flight_deals"] = sorted(merged.values(), key=_fare_sort_key)
        result["flight_deals"] = filter_fares(result["raw_flight_deals"], **filters)
        for search in result["searches"]:
            search["fare_count"] = sum(cell_key(fare) == cell_key(search) for fare in result["raw_flight_deals"])
        summarize(result)
        if output:
            path = Path(output)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            temporary.replace(path)
    save()  # The first snapshot preserves the original fares on cancellation.
    for completed, target in enumerate(targets, 1):
        key = cell_key(target)
        context = {name: target[name] for name in ("origin", "destination", "departure_date", "return_date")}
        attempts, warnings = [], []
        if progress:
            progress({"event": "phase", "phase": "browser", **context})
        try:
            fares = scan_route(*key, max_price=None, max_stops=live_stops, source_warnings=warnings,
                               browser_missing=True, browser_engine=engine, browser_attempts=attempts,
                               browser_airlines=target["airlines"],
                               browser_only=True, unpriced_itineraries=target.get("itineraries"),
                               browser_stage_callback=(lambda stage: progress({"event": "phase", "phase": "browser", "stage": stage, **context})) if progress else None,
                               browser_callback=(lambda: progress({"event": "phase", "phase": "browser", **context})) if progress else None)
            eligible = filter_fares(fares, airlines=target["airlines"])
            for fare in eligible:
                identity = fare_key(fare)
                if identity not in merged:
                    result["retry_summary"]["new_quotes"] += 1
                fare.setdefault("price_checked_at", checked_at)
                location = next(d for d in result["query"]["destinations"] if fare["destination"] in d["airports"])
                fare["destination_name"], fare["gateway_note"] = location["name"], location.get("gateway_note")
                merged[identity] = fare
            present = {name.strip().casefold() for fare in eligible for name in fare["airline"].split(",")}
            pending = {name.casefold() for warning in warnings for name in warning["airlines"]}
            resolved = present - pending
            kept = []
            for warning in result["source_warnings"]:
                if cell_key(warning) != key:
                    kept.append(warning)
                    continue
                remaining = [name for name in warning["airlines"] if name.casefold() not in resolved]
                if remaining:
                    kept.append({**warning, "airlines": remaining})
            result["source_warnings"] = kept
            if not attempts:
                attempts = [{**context, "status": "recovered" if eligible else "price_unavailable",
                             "recovered": len(eligible), "engine": engine, "stage": "context",
                             "message": "Browser prices were available." if eligible else "The retry did not return a priced matching itinerary."}]
        except FlightLookupError:
            attempts = [{**context, "status": "unavailable", "recovered": 0, "engine": engine, "stage": "context",
                         "message": "Could not prepare the browser query; saved fares were retained."}]
        failed = any(attempt["status"] == "unavailable" for attempt in attempts)
        result["browser_attempts"].extend(attempts)
        result["retry_summary"]["completed"] = completed
        result["retry_summary"]["failed"] += int(failed)
        save()
        if progress:
            progress({"event": "progress", **context, "completed": completed, "total": len(targets),
                      "status": "unavailable" if failed else "ok"})
    return result


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
    search.add_argument("--browser-missing", action="store_true", help="Slower optional browser retry for unpriced itineraries only")
    search.add_argument("--browser-engine", choices=["native-chrome", "chromium", "chrome"], default="native-chrome", help="Browser fallback engine; native-chrome opens installed Chrome; chrome/chromium use headless Playwright")
    saved = commands.add_parser("filter", help="Filter and rank a saved search without network requests")
    saved.add_argument("--input", required=True)
    saved.add_argument("--dest", help="Saved destination ids/names or airport codes")
    saved.add_argument("--origin", help="Comma-separated origin airport codes")
    retry = commands.add_parser("retry-missing", help="Retry only saved missing-price cases in a browser and preserve existing fares")
    retry.add_argument("--input", required=True)
    retry.add_argument("--browser-engine", choices=["native-chrome", "chromium", "chrome"], default="native-chrome")
    retry.add_argument("--progress-json", action="store_true")
    retry.add_argument("--output", help="Save incremental merged snapshots; existing fares survive partial failure")
    retry.add_argument("--format", choices=["json", "table"], default="json")
    for command in (search, saved):
        add_filters(command)
        command.add_argument("--output", help="Save the full structured JSON snapshot")
        command.add_argument("--format", choices=["json", "table"], default="json", help="stdout format; --output always saves JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "destinations":
            print(json.dumps(load_pool(args.pool), indent=2, ensure_ascii=False))
            return 0
        if args.command == "retry-missing":
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
            payload = retry_missing(payload, engine=args.browser_engine, output=args.output,
                                    progress=(lambda event: print(json.dumps(event), file=sys.stderr, flush=True)) if args.progress_json else None)
            print(render_table(payload) if args.format == "table" else json.dumps(payload, indent=2, ensure_ascii=False))
            return 1 if payload["retry_summary"]["failed"] or payload["source_errors"] else 0
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
