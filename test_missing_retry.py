import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from flight_scanner import FlightLookupError, scan_route
from flight_tools import main, retry_missing, retry_missing_targets, summarize


def snapshot():
    output = io.StringIO()
    with redirect_stdout(output):
        main(["search", "--start-date", "2027-01-01", "--end-date", "2027-01-06",
              "--dest", "cancun,maui", "--max-stops", "1", "--dry-run"])
    payload = json.loads(output.getvalue())
    payload["checked_at"] = "2026-10-13T12:00:00+00:00"
    for record in payload["searches"]:
        record.update(status="ok", fare_count=0)
    record = payload["searches"][0]
    fare = {**{k: record[k] for k in ("origin", "destination", "departure_date", "return_date")},
            "price": 500, "airline": "United", "stops": 0, "legs": [], "layovers": [],
            "total_journey_duration": "5h 0m", "booking_url": "https://www.google.com/travel/flights"}
    payload["raw_flight_deals"] = [fare]
    payload["flight_deals"] = [fare]
    record["fare_count"] = 1
    payload["source_warnings"] = [{**{k: record[k] for k in ("origin", "destination", "departure_date", "return_date")},
                                  "airlines": ["Singapore Airlines"], "status": "price_unavailable"}]
    return summarize(payload)


class MissingRetryTests(unittest.TestCase):
    def test_separate_backend_never_calls_the_normal_provider(self):
        from test_flight_browser import itinerary
        item = itinerary()
        item.price = 1039
        item.price_source = "google_flights_browser"
        item.price_checked_at = "2026-10-13T12:01:00+00:00"
        def browser(query, items, **options):
            self.assertTrue(options["browser_only"])
            self.assertEqual(query.flight_data[1].date, "2027-02-09")
            self.assertEqual(items[0].airlines, ["Singapore Airlines"])
            items[:] = [item]
            return {"status": "recovered", "recovered": 1}
        attempts = []
        with patch("flight_scanner._get_flights_resilient", side_effect=AssertionError("normal provider must not run")) as regular, patch("flight_browser.fill_missing_prices", side_effect=browser):
            fares = scan_route("SFO", "DAC", "2027-01-14", "2027-02-09", browser_missing=True, browser_only=True,
                               browser_airlines=["Singapore Airlines"], browser_attempts=attempts)
        regular.assert_not_called()
        self.assertEqual(fares[0]["price"], 1039)
        self.assertEqual(fares[0]["price_source"], "google_flights_browser")
        self.assertEqual(attempts[0]["recovered"], 1)

    def test_targets_are_saved_warning_cells_and_selected_airlines_only(self):
        payload = snapshot()
        warning = payload["source_warnings"][0]
        payload["source_warnings"].extend([copy.deepcopy(warning), {**warning, "origin": "LAX"}])
        self.assertEqual(len(retry_missing_targets(payload)), 1)
        self.assertEqual(retry_missing_targets(payload, ["Qatar Airways"]), [])
        payload["applied_filters"] = {"airlines": ["singapore airlines"]}
        self.assertEqual(retry_missing_targets(payload)[0]["airlines"], ["Singapore Airlines"])

    def test_retry_merges_without_losing_fares_or_relaxing_original_live_limit(self):
        payload = snapshot()
        payload["applied_filters"] = {**payload["query"]["filters"], "max_stops": 0}
        before = copy.deepcopy(payload)
        def lookup(origin, destination, dep, ret, **kwargs):
            self.assertTrue(kwargs["browser_missing"])
            self.assertTrue(kwargs["browser_only"])
            self.assertEqual(kwargs["browser_engine"], "chrome")
            self.assertEqual(kwargs["browser_airlines"], ["Singapore Airlines"])
            self.assertEqual(kwargs["max_stops"], 1)
            kwargs["browser_callback"]()
            kwargs["browser_attempts"].append({"origin": origin, "destination": destination, "departure_date": dep,
                                                "return_date": ret, "status": "recovered", "recovered": 1})
            fare = {**before["raw_flight_deals"][0], "price": 400, "airline": "Singapore Airlines", "stops": 1,
                    "price_source": "google_flights_browser", "price_checked_at": "2026-10-13T12:01:00+00:00"}
            return [fare, copy.deepcopy(fare)]
        events = []
        with patch("flight_tools.scan_route", side_effect=lookup) as route:
            result = retry_missing(payload, engine="chrome", progress=events.append)
        self.assertEqual(route.call_count, 1)
        self.assertEqual(payload, before)
        self.assertEqual(result["query"], before["query"])
        self.assertEqual(len(result["raw_flight_deals"]), 2)
        self.assertEqual(result["flight_deals"], before["flight_deals"])
        self.assertEqual(result["source_warnings"], [])
        self.assertEqual(events[-1]["completed"], 1)
        self.assertEqual(events[-1]["total"], 1)

    def test_cli_failures_preserve_old_fares_and_write_a_valid_incremental_snapshot(self):
        payload = snapshot()
        with tempfile.TemporaryDirectory() as folder:
            input_path, output_path = Path(folder) / "input.json", Path(folder) / "output.json"
            input_path.write_text(json.dumps(payload))
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch("flight_tools.scan_route", side_effect=FlightLookupError("private request details")), redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["retry-missing", "--input", str(input_path), "--output", str(output_path), "--progress-json"])
            result = json.loads(stdout.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output_path.read_text()), result)
            self.assertEqual(result["raw_flight_deals"], payload["raw_flight_deals"])
            self.assertEqual(result["source_warnings"], payload["source_warnings"])
            self.assertEqual(result["browser_attempts"][-1]["status"], "unavailable")
            self.assertNotIn("private request details", stdout.getvalue() + stderr.getvalue())
            event = json.loads(stderr.getvalue().splitlines()[-1])
            self.assertEqual((event["completed"], event["total"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
