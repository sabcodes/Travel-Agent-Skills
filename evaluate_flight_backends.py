"""Bounded, opt-in comparison of our flight adapter and an isolated fli install."""
import argparse
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version

ROOT = Path(__file__).resolve().parent
CASES = (
    ("CUN", "2027-01-01", "2027-01-05"),
    ("DAC", "2027-01-01", "2027-01-05"),
    ("DAC", "2027-01-14", "2027-02-09"),
    ("DAC", "2027-01-14", "2027-02-14"),
)


def numeric(price):
    return isinstance(price, (float, int)) and not isinstance(price, bool) and math.isfinite(price) and price > 0


def code(value):
    return getattr(value, "name", str(value)).removeprefix("_")


def fli_row(item):
    return {"price": item.price, "currency": item.currency,
            "airlines": sorted({code(leg.airline) for leg in item.legs}),
            "duration_minutes": item.duration, "stops": item.stops,
            "mixed_cabin": item.mixed_cabin, "self_transfer": item.self_transfer,
            "legs": [{"from": code(leg.departure_airport), "to": code(leg.arrival_airport),
                      "departure": leg.departure_datetime.isoformat(), "arrival": leg.arrival_datetime.isoformat(),
                      "airline": code(leg.airline), "flight_number": str(leg.flight_number)} for leg in item.legs]}


def summarize(report):
    rows = report.get("rows", [])
    # Keep the outbound starting quote separate from the selected pair's quote.
    outbounds = [row.get("outbound", row) for row in rows]
    prices = [row.get("price") for row in outbounds]
    returns = [row["return"] for row in rows if "return" in row]
    selected = [row["price"] for row in returns if row.get("currency") == "USD" and numeric(row.get("price"))]
    report.update(row_count=len(rows), priced_count=sum(numeric(p) for p in prices),
                  minimum_starting_quote=min((p for p in prices if numeric(p)), default=None),
                  selected_pair_priced_count=len(selected), minimum_selected_pair_quote=min(selected, default=None),
                  differing_pair_quotes=sum(numeric(out.get("price")) and numeric(ret.get("price")) and
                                            out["price"] != ret["price"] for out, ret in zip(outbounds, returns)),
                  unpriced_airlines=sorted({a for row in outbounds if not numeric(row.get("price")) for a in row.get("airlines", [])} |
                                           {a for warning in report.get("warnings", []) for a in warning.get("airlines", [])}))
    return report


def probe(args):
    started = time.monotonic()
    report = {"backend": args.backend, "origin": "SFO", "destination": args.destination,
              "departure_date": args.departure, "return_date": args.return_date,
              "airline_filter": args.airline, "checked_at": datetime.now(timezone.utc).isoformat(),
              "passengers": 1, "cabin": "economy", "currency": "USD", "rows": []}
    try:
        if args.backend == "current":
            from flight_scanner import scan_route
            warnings = []
            report["version"] = version("fast-flights")
            report["rows"] = scan_route("SFO", args.destination, args.departure, args.return_date, source_warnings=warnings)
            for row in report["rows"]:
                row.pop("booking_url", None)
            report["warnings"] = warnings
        else:
            from fli.core.builders import build_flight_segments
            from fli.models import Airport, Airline, FlightSearchFilters, PassengerInfo, SeatType, SortBy
            from fli.search import SearchFlights
            from fli.search._concurrency import configure_concurrency
            configure_concurrency(2)
            segments, trip_type = build_flight_segments(Airport.SFO, Airport[args.destination], args.departure, args.return_date)
            filters = FlightSearchFilters(flight_segments=segments, trip_type=trip_type, passenger_info=PassengerInfo(adults=1),
                                          seat_type=SeatType.ECONOMY, sort_by=SortBy.CHEAPEST,
                                          airlines=[Airline[args.airline]] if args.airline else None)
            search = SearchFlights()
            report["version"] = version("flights")
            if args.backend == "fli-page":
                # Private API used ONLY for a like-for-like outbound-board evaluation.
                results = search._fetch_flights(filters, currency="USD", language="en-US", country="US", capture_session=True)
                report["rows"] = [fli_row(item) for item in results or []]
            else:
                report["top_n"] = args.top_n
                results = search.search(filters, top_n=args.top_n, currency="USD", language="en-US", country="US")
                report["rows"] = [{"outbound": fli_row(pair[0]), "return": fli_row(pair[1])} for pair in results or []]
        summarize(report)
        report["status"] = "ok" if report["priced_count"] or report["selected_pair_priced_count"] else "unpriced_only" if report["rows"] else "no_rows"
    except Exception as exc:
        # Exceptions can include request URLs or home paths; never export their text.
        report.update(status="unavailable", error_type=type(exc).__name__)
        summarize(report)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(report))


def compare(args):
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(),
              "scope": "SFO, one adult, economy, USD, no price/stop limits; two destinations and four date pairs",
              "repeats": args.repeats, "top_n": args.top_n, "runs": [], "summary": []}
    plan = [(backend, dest, dep, ret, None, repeat) for repeat in range(args.repeats)
            for dest, dep, ret in CASES for backend in ("current", "fli-page")]
    plan += [("fli-return", dest, dep, ret, "SQ" if dest == "DAC" else None, 0)
             for dest, dep, ret in CASES if dest == "CUN" or ret.startswith("2027-02")]
    for backend, dest, dep, ret, airline, repeat in plan:
        python = args.current_python if backend == "current" else args.fli_python
        command = [python, "-B", str(Path(__file__).resolve()), "probe", "--backend", backend,
                   "--destination", dest, "--departure", dep, "--return-date", ret, "--top-n", str(args.top_n)]
        if airline:
            command.extend(["--airline", airline])
        started = time.monotonic()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout,
                                       env={**os.environ, "FLI_TIMEOUT": "15"}, cwd=ROOT)
            result = json.loads(completed.stdout) if completed.returncode == 0 else {
                "status": "worker_error", "exit_code": completed.returncode}
            if not isinstance(result, dict):
                raise ValueError("worker output must be an object")
        except subprocess.TimeoutExpired:
            result = {"status": "timeout", "elapsed_seconds": round(time.monotonic() - started, 3)}
        except (OSError, ValueError):
            result = {"status": "worker_error"}
        result.update(backend=backend, destination=dest, departure_date=dep, return_date=ret, airline_filter=airline, repeat=repeat + 1)
        report["runs"].append(result)
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{backend:10} SFO–{dest} {dep} → {ret}: {result['status']}, "
              f"{result.get('priced_count', 0)} priced, starting {result.get('minimum_starting_quote')}, "
              f"selected pair {result.get('minimum_selected_pair_quote')}", flush=True)
        time.sleep(1)
    for dest, dep, ret in CASES:
        for backend in ("current", "fli-page"):
            runs = [r for r in report["runs"] if (r["backend"], r["destination"], r["departure_date"], r["return_date"]) == (backend, dest, dep, ret)]
            successful = [r for r in runs if r["status"] in ("ok", "unpriced_only", "no_rows")]
            report["summary"].append({"backend": backend, "destination": dest, "departure_date": dep, "return_date": ret,
                                      "successful_runs": len(successful), "attempted_runs": len(runs),
                                      "median_seconds": statistics.median(r["elapsed_seconds"] for r in successful) if successful else None,
                                      "priced_counts": [r["priced_count"] for r in successful],
                                      "starting_quotes": [r["minimum_starting_quote"] for r in successful]})
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return int(any(r["status"] in ("unavailable", "worker_error", "timeout") for r in report["runs"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    command = modes.add_parser("compare", help="Run the fixed Dhaka/Cancun comparison and save JSON")
    command.add_argument("--fli-python", required=True, help="Python executable with the separately installed fli source")
    command.add_argument("--current-python", default=sys.executable)
    command.add_argument("--output", required=True, help="Save outside the repo, e.g. /tmp/backend-eval.json")
    command.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    command.add_argument("--timeout", type=int, choices=range(1, 121), default=60, help="Whole-worker timeout in seconds")
    command.add_argument("--top-n", type=int, choices=range(1, 11), default=3)
    worker = modes.add_parser("probe", help="Run one explicit matched query")
    worker.add_argument("--backend", choices=["current", "fli-page", "fli-return"], required=True)
    worker.add_argument("--destination", required=True)
    worker.add_argument("--departure", required=True)
    worker.add_argument("--return-date", required=True)
    worker.add_argument("--airline", help="fli carrier code; current backend remains unfiltered")
    worker.add_argument("--top-n", type=int, choices=range(1, 11), default=3)
    args = parser.parse_args()
    if args.mode == "probe":
        if args.backend == "current" and args.airline:
            parser.error("The current comparison probe does not apply an airline filter")
        probe(args)
        return 0
    return compare(args)


if __name__ == "__main__":
    raise SystemExit(main())
