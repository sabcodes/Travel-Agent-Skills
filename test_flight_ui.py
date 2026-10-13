import csv
import http.client
import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from flight_scanner import FlightLookupError
from flight_tools import main as flight_cli, summarize
from flight_ui import App, Handler, ThreadingHTTPServer, csv_table, search_arguments


class FlightUITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = App(Path(self.folder.name) / "data")
        self.addCleanup(self.app.close)
        self.values = {"destinations": ["cancun", "maui"], "start_date": "2027-01-01", "end_date": "2027-01-06", "trip_lengths": "6"}

    def completed_snapshot(self):
        payload, _, _ = self.app.plan(self.values)
        fares = []
        for record, price in zip(payload["searches"], [500, 375]):
            record.update(status="ok", fare_count=1)
            fares.append({**{k: record[k] for k in ("origin", "destination", "departure_date", "return_date")},
                          "price": price, "airline": "United", "stops": 0, "layovers": [],
                          "total_journey_duration": "5h 0m", "booking_url": "https://www.google.com/travel/flights"})
        payload.update(flight_deals=fares, raw_flight_deals=fares, checked_at="2026-10-12T12:00:00+00:00")
        summarize(payload)
        snapshot = Path(self.app.temp.name) / "snapshot.json"
        snapshot.write_text(json.dumps(payload), encoding="utf-8")
        self.app.job = {"id": "test", "status": "done", "completed": 2, "total": 2,
                        "current": "Complete", "error": None, "cancelled": False, "started": 0, "finished": 10,
                        "snapshot": str(snapshot), "result": payload, "view": payload, "query": payload["query"]}
        return payload

    def test_regular_and_deep_plans_use_the_real_cli(self):
        values = {**self.values, "end_date": "2027-01-31"}
        regular, _, _ = self.app.plan(values)
        deep, arguments, _ = self.app.plan({**values, "mode": "deep"})
        self.assertEqual(regular["summary"]["planned_searches"], 10)
        self.assertEqual(regular["query"]["date_step_days"], 6)
        self.assertEqual(deep["summary"]["planned_searches"], 52)
        self.assertEqual(arguments[arguments.index("--date-step-days") + 1], "1")
        sampled, _, _ = self.app.plan({**values, "mode": "deep", "date_step_days": "3"})
        self.assertEqual(sampled["summary"]["planned_searches"], 18)
        self.assertEqual(sampled["query"]["date_pairs"][1], ["2027-01-04", "2027-01-09"])
        with self.assertRaisesRegex(ValueError, "date-range end must be after its start"):
            self.app.plan({**values, "end_date": "2026-12-01"})
        self.completed_snapshot()
        self.assertEqual(self.app.state()["query"]["start_date"], "2027-01-01")

    def test_browser_retry_is_opt_in_and_dry_run_does_not_launch_it(self):
        plan, arguments, _ = self.app.plan(self.values)
        self.assertFalse(plan["query"]["browser_missing"])
        self.assertNotIn("--browser-missing", arguments)
        plan, arguments, _ = self.app.plan({**self.values, "browser_missing": True, "browser_engine": "chrome"})
        self.assertTrue(plan["query"]["browser_missing"])
        self.assertEqual(plan["query"]["browser_engine"], "chrome")
        self.assertIn("--browser-missing", arguments)
        self.assertEqual(plan["browser_attempts"], [])
        for change in ({"browser_missing": "yes"}, {"browser_engine": "--config"}):
            with self.assertRaises(ValueError):
                self.app.plan({**self.values, **change})

    def test_custom_locations_persist_and_reserved_all_cannot_trigger_a_sweep(self):
        entry = self.app.add_location({"name": "Honolulu", "airports": "hnl, HNL"})
        self.assertEqual(entry["airports"], ["HNL"])
        other = App(self.app.data_dir)
        self.addCleanup(other.close)
        self.assertEqual(other.pool()[-1], entry)
        plan, _, _ = other.plan({**self.values, "destinations": [entry["id"]]})
        self.assertEqual(plan["summary"]["planned_searches"], 1)
        self.assertEqual(plan["searches"][0]["destination"], "HNL")
        for values in [{"name": "All", "airports": "HNL"}, {"name": "Honolulu", "airports": "HNL"}, {"name": "Invalid", "airports": "HNL,--config"}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.app.add_location(values)

    def test_rejects_invalid_and_flag_like_arguments(self):
        for change in [{"destinations": ["--config"]}, {"origin": "SFO;exit"}, {"trip_lengths": "6 --pool"},
                       {"date_step_days": "0"}, {"max_price": "nan"}, {"max_stops": "1.5"}, {"max_price": []}, {"airlines": []}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                search_arguments({**self.values, **change}, self.app.pool())

    def test_added_dhaka_five_day_january_regular_grid_persists(self):
        dhaka = self.app.add_location({"name": "Dhaka, Bangladesh", "airports": "DAC"})
        other = App(self.app.data_dir)
        self.addCleanup(other.close)
        plan, arguments, _ = other.plan({"destinations": [dhaka["id"]], "start_date": "2027-01-01",
                                        "end_date": "2027-01-31", "trip_lengths": "5", "mode": "lite"})
        self.assertEqual(plan["query"]["trip_lengths"], [5])
        self.assertEqual(plan["query"]["date_step_days"], 5)
        self.assertEqual(plan["summary"]["planned_searches"], 6)
        self.assertEqual(plan["query"]["date_pairs"], [[f"2027-01-{d:02d}", f"2027-01-{d+4:02d}"] for d in range(1, 27, 5)])
        self.assertTrue(all(s["origin"] == "SFO" and s["destination"] == "DAC" for s in plan["searches"]))
        self.assertIn(dhaka, other.pool())
        self.assertIn("--date-step-days", arguments)

    def test_changing_vacation_length_from_five_to_thirty_updates_dates_and_default_interval(self):
        dhaka = self.app.add_location({"name": "Dhaka, Bangladesh", "airports": "DAC"})
        values = {"destinations": [dhaka["id"]], "start_date": "2027-01-01", "end_date": "2027-01-31",
                  "mode": "lite", "date_step_days": "", "trip_lengths": "5"}
        short, _, _ = self.app.plan(values)
        long, arguments, _ = self.app.plan({**values, "trip_lengths": "30"})
        self.assertEqual(short["summary"]["planned_searches"], 6)
        self.assertEqual(long["query"]["trip_lengths"], [30])
        self.assertEqual(long["query"]["date_pairs"], [["2027-01-01", "2027-01-30"]])
        self.assertEqual(long["query"]["date_step_days"], 30)
        self.assertEqual(arguments[arguments.index("--trip-lengths") + 1], "30")
        override, _, _ = self.app.plan({**values, "trip_lengths": "30", "date_step_days": "5"})
        self.assertEqual(override["query"]["trip_lengths"], [30])
        self.assertEqual(override["query"]["date_step_days"], 5)

    def test_ui_airline_filter_uses_cli_and_can_be_cleared(self):
        original = self.completed_snapshot()
        self.assertEqual(len(self.app.filter({"airlines": "united"})["flight_deals"]), 2)
        excluded = self.app.filter({"airlines": "Qatar"})
        self.assertEqual(excluded["flight_deals"], [])
        self.assertEqual(excluded["applied_filters"]["airlines"], ["Qatar"])
        self.assertEqual(self.app.filter({})["flight_deals"], original["flight_deals"])

    def test_cli_progress_counts_successes_and_failures_without_corrupting_stdout(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("flight_scanner.scan_route", side_effect=[[], FlightLookupError("test failure")]), patch("flight_scanner.time.sleep"), redirect_stdout(stdout), redirect_stderr(stderr):
            code = flight_cli(["search", "--dest", "cancun,maui", "--start-date", "2027-01-01", "--end-date", "2027-01-06", "--progress-json"])
        payload = json.loads(stdout.getvalue())
        events = [json.loads(line) for line in stderr.getvalue().splitlines() if line.startswith('{"event":')]
        self.assertEqual(code, 1)
        self.assertEqual([e["completed"] for e in events], [1, 2])
        self.assertEqual([e["total"] for e in events], [2, 2])
        self.assertEqual(events[1]["status"], "unavailable")
        self.assertEqual(payload["summary"]["failed_searches"], 1)

    def test_real_offline_filter_can_clear_limits_and_csv_matches_current_view(self):
        original = self.completed_snapshot()
        filtered = self.app.filter({"max_price": 400})
        self.assertEqual([f["price"] for f in filtered["flight_deals"]], [375])
        rows = list(csv.reader(io.StringIO(csv_table(self.app.result()).decode("utf-8-sig"))))
        self.assertEqual(rows[1][3], "filtered_out")
        self.assertEqual(rows[2][3], "375.00")
        self.assertEqual(rows[2][4], "375")
        cleared = self.app.filter({})
        self.assertEqual(cleared["flight_deals"], original["flight_deals"])
        self.assertEqual(cleared["checked_at"], original["checked_at"])
        self.assertEqual(cleared, self.app.filter({}))
        cleared["matrix"][0]["destination_name"] = "=UNTRUSTED()"
        self.assertEqual(list(csv.reader(io.StringIO(csv_table(cleared).decode("utf-8-sig"))))[1][0], "'=UNTRUSTED()")

    def test_worker_records_partial_results_and_cancellation(self):
        self.completed_snapshot()
        job = self.app.job
        job.update(status="running", completed=0)
        event = {"event": "progress", "origin": "SFO", "destination": "CUN", "departure_date": "2027-01-01", "return_date": "2027-01-06", "completed": 1}
        process = Mock(stderr=io.StringIO(json.dumps(event) + "\n"))
        process.wait.return_value = 1
        with patch("flight_ui.subprocess.Popen", return_value=process) as popen:
            self.app.run(job, ["search", "--progress-json"])
        self.assertEqual(job["status"], "partial")
        self.assertEqual(job["completed"], 1)
        self.assertEqual(popen.call_args.args[0][-1], "--progress-json")
        self.assertNotIn("shell", popen.call_args.kwargs)
        self.assertIsNone(self.app.process)
        job.update(status="running", cancelled=False)
        process.poll.return_value = None
        self.app.process = process
        with patch("flight_ui.stop_process") as stop:
            self.app.cancel()
        stop.assert_called_once_with(process)
        with patch("flight_ui.subprocess.Popen") as popen:
            self.app.run(job, [])
            popen.assert_not_called()
        self.assertEqual(job["status"], "cancelled")
        self.app.process = None

    def test_eta_uses_completed_attempts_and_waits_for_the_first_lookup(self):
        self.completed_snapshot()
        self.app.job.update(status="running", completed=0, total=12, started=100)
        del self.app.job["finished"]
        with patch("flight_ui.time.monotonic", return_value=120):
            self.assertIsNone(self.app.state()["eta_seconds"])
            self.app.job["completed"] = 3
            self.assertEqual(self.app.state()["eta_seconds"], 60)
            self.app.job["status"] = "done"
            self.assertEqual(self.app.state()["eta_seconds"], 0)

    def test_http_restricts_host_origin_token_and_static_files(self):
        self.completed_snapshot()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.app = self.app
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(path, values=None, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET" if values is None else "POST", path, body=None if values is None else json.dumps(values), headers=headers or {})
            response = connection.getresponse()
            result = response.status, response.read(), dict(response.getheaders())
            connection.close()
            return result

        self.assertEqual(request("/")[0], 200)
        self.assertEqual(json.loads(request("/api/state")[1])["query"]["destinations"][0]["id"], "cancun")
        self.assertEqual(request("/flight_destinations.json")[0], 404)
        self.assertEqual(request("/api/destinations", headers={"Host": "outside.example"})[0], 403)
        self.assertEqual(request("/api/locations", {"name": "Blocked", "airports": "HNL"})[0], 403)
        self.assertEqual(request("/api/locations", {"name": "Blocked", "airports": "HNL"}, {"X-CSRF-Token": self.app.csrf, "Origin": "https://outside.example"})[0], 403)
        response = request("/api/filter", {"max_price": 400}, {"X-CSRF-Token": self.app.csrf})
        self.assertEqual(response[0], 200)
        self.assertEqual(len(json.loads(response[1])["flight_deals"]), 1)
        status, data, headers = request("/api/export.csv")
        self.assertEqual(status, 200)
        self.assertIn("flight-comparison.csv", headers["Content-Disposition"])
        self.assertIn("375.00", data.decode("utf-8-sig"))
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()
