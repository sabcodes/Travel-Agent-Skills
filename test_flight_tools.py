import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from flight_scanner import FlightLookupError, _duration_minutes, generate_date_pairs_between, scan_flights, scan_route
from flight_tools import ROOT, filter_fares, load_pool, main, select_destinations


class FlightToolTests(unittest.TestCase):
    def setUp(self):
        sleeper = patch("flight_scanner.time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def cli(self, args):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = main(args)
        return code, json.loads(output.getvalue())

    def search_args(self, *extra):
        return ["search", "--start-date", "2027-01-01", "--end-date", "2027-01-31",
                "--dest", "cancun,maui", *extra]

    def test_lite_default_and_configurable_spacing_with_strict_end(self):
        _, plan = self.cli(self.search_args("--dry-run"))
        self.assertEqual(plan["summary"]["planned_searches"], 12)
        self.assertEqual(plan["query"]["date_pairs"], [[f"2027-01-{d:02d}", f"2027-01-{d+5:02d}"] for d in range(1, 27, 5)])
        _, plan = self.cli(self.search_args("--dry-run", "--date-step-days", "8"))
        self.assertEqual(len(plan["query"]["date_pairs"]), 4)
        self.assertEqual(plan["query"]["date_pairs"][-1], ["2027-01-25", "2027-01-30"])
        self.assertIsNone(plan["query"]["filters"]["max_price"])

    def test_deep_checks_every_day_for_each_requested_length(self):
        _, plan = self.cli(self.search_args("--dry-run", "--mode", "deep"))
        self.assertEqual(plan["summary"]["planned_searches"], 52)
        self.assertEqual(plan["query"]["date_pairs"][-1], ["2027-01-26", "2027-01-31"])
        _, sampled = self.cli(self.search_args("--dry-run", "--mode", "deep", "--date-step-days", "3"))
        self.assertEqual(sampled["summary"]["planned_searches"], 18)
        self.assertEqual(sampled["query"]["date_pairs"][1], ["2027-01-04", "2027-01-09"])
        pairs = generate_date_pairs_between("2027-01-01", "2027-01-10", [5, 6], 1)
        self.assertEqual(len(pairs), 11)
        self.assertEqual(pairs[-1], ("2027-01-06", "2027-01-10"))

    def test_pool_contains_all_50_locations_and_explicit_gateways(self):
        pool = load_pool(ROOT / "flight_destinations.json")
        self.assertEqual(len(pool), 50)
        self.assertEqual(select_destinations(pool, "Tokyo")[0]["airports"], ["HND", "NRT"])
        self.assertEqual(select_destinations(pool, "NRT")[0]["airports"], ["NRT"])
        self.assertEqual(select_destinations(pool, "St. John USVI")[0]["airports"], ["STT"])
        self.assertIn("ferry", select_destinations(pool, "st_john_usvi")[0]["gateway_note"])
        self.assertEqual(len(select_destinations(pool, "all")), 50)
        self.assertEqual(select_destinations(pool, "Curaçao")[0]["airports"], ["CUR"])
        with self.assertRaises(ValueError):
            select_destinations(pool, "not_a_destination")

    def test_missing_duration_is_not_ranked_as_zero(self):
        self.assertEqual(_duration_minutes("N/A"), float("inf"))

    def test_airlines_match_exact_carriers_case_insensitively_and_check_mixed_itineraries(self):
        base = {"origin": "SFO", "destination": "DAC", "departure_date": "2027-01-01", "return_date": "2027-01-05", "price": 1500, "stops": 1}
        fares = [{**base, "airline": "United"}, {**base, "airline": "United, Lufthansa"}, {**base, "airline": "United Express"}, {**base, "airline": "Emirates"}]
        self.assertEqual([f["airline"] for f in filter_fares(fares, airlines=[" united "])], ["United"])
        self.assertEqual({f["airline"] for f in filter_fares(fares, airlines=["UNITED", "lufthansa"])}, {"United", "United, Lufthansa"})
        self.assertEqual(filter_fares(fares, airlines=["Qatar"]), [])

    def test_invalid_destination_files_give_clear_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pool.json"
            for value in [{"id": "x"}, [], ["CUN"], [{"id": "x", "name": "X", "airports": "CUN"}], [{"id": "x", "name": "X", "airports": ["cun"]}]]:
                path.write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaises(ValueError):
                    load_pool(path)

    def test_filters_find_price_winner_and_respect_outbound_constraints(self):
        base = {"origin": "SFO", "destination": "CUN", "departure_date": "2027-01-01", "return_date": "2027-01-06"}
        fares = [
            {**base, "price": 350, "stops": 1, "total_journey_duration": "8h 0m", "airline": "Zulu", "layovers": [{"duration_min": 90}]},
            {**base, "price": 300, "stops": 2, "total_journey_duration": "25h 0m", "airline": "Alpha", "layovers": [{"duration_min": 900}, {"duration_min": 90}]},
            {**base, "price": 400, "stops": 0, "total_journey_duration": "6h 0m", "airline": "Beta", "layovers": []},
        ]
        self.assertEqual(filter_fares(fares)[0]["price"], 300)
        self.assertEqual(filter_fares(fares, max_stops=1, max_duration_hours=10, max_layover_hours=2)[0]["price"], 350)
        self.assertEqual(filter_fares(fares, max_price=320, max_stops=1), [])

    @patch("flight_scanner.scan_route", side_effect=FlightLookupError("provider unavailable"))
    def test_all_provider_failures_still_produce_json_and_nonzero_exit(self, route):
        code, payload = self.cli(self.search_args())
        self.assertEqual(code, 1)
        self.assertEqual(len(payload["source_errors"]), 12)
        self.assertEqual(payload["summary"]["failed_searches"], 12)
        self.assertTrue(all(c["status"] == "unavailable" for row in payload["matrix"] for c in row["cells"]))

    @patch("flight_scanner.scan_route", return_value=[])
    def test_empty_provider_results_are_distinct_and_have_no_implicit_cap(self, route):
        code, payload = self.cli(self.search_args())
        self.assertEqual(code, 0)
        self.assertEqual(payload["source_errors"], [])
        self.assertTrue(all(c["status"] == "no_matching_fares" for row in payload["matrix"] for c in row["cells"]))
        self.assertTrue(all(call.kwargs["max_price"] is None for call in route.call_args_list))

    @patch("flight_scanner.scan_route")
    def test_distinct_itineraries_and_all_prices_survive_retention(self, route):
        base = {"origin": "SFO", "destination": "CUN", "departure_date": "2027-01-01", "return_date": "2027-01-06", "price": 5000, "stops": 0, "airline": "United", "total_journey_duration": "5h 0m"}
        first = {**base, "legs": [{"dep_time": "08:00"}]}
        second = {**base, "legs": [{"dep_time": "09:00"}]}
        third = {**base, "price": 5500, "legs": [{"dep_time": "10:00"}]}
        route.return_value = [third, second, first, first]
        with redirect_stderr(io.StringIO()):
            fares = scan_flights(origins=["SFO"], destinations=["CUN"], date_pairs=[("2027-01-01", "2027-01-06")], delay_between_requests=0)
        self.assertEqual(fares, [first, second, third])

    @patch("flight_scanner._get_flights_resilient")
    def test_live_adapter_labels_one_adult_outbound_scope_and_retains_dates(self, provider):
        dep = NS(date=(2027, 1, 1), time=(8, 0))
        arr = NS(date=(2027, 1, 1), time=(13, 0))
        leg = NS(from_airport=NS(code="SFO"), to_airport=NS(code="CUN"), departure=dep, arrival=arr, duration=300, plane_type="A320")
        provider.return_value = [NS(price=3000, airlines=["United"], flights=[leg])]
        fare = scan_route("SFO", "CUN", "2027-01-01", "2027-01-06")[0]
        self.assertEqual(fare["price"], 3000)
        self.assertEqual(fare["trip_days"], 6)
        self.assertEqual(fare["passengers"], 1)
        self.assertEqual(fare["legs"][0]["departure_date"], "2027-01-01")
        self.assertFalse(fare["return_itinerary_available"])
        self.assertIn("curr=USD", fare["booking_url"])

    @patch("flight_scanner._get_flights_resilient")
    def test_priced_result_without_legs_is_a_provider_error(self, provider):
        provider.return_value = [NS(price=500, airlines=["United"], flights=[])]
        with self.assertRaisesRegex(FlightLookupError, "no outbound"):
            scan_route("SFO", "CUN", "2027-01-01", "2027-01-06")

    @patch("flight_scanner._get_flights_resilient")
    def test_unpriced_airlines_are_reported_without_inventing_a_fare(self, provider):
        class Results(list):
            unpriced_airlines = ["Singapore Airlines"]
        provider.return_value = Results()
        warnings = []
        self.assertEqual(scan_route("SFO", "DAC", "2027-01-01", "2027-01-30", source_warnings=warnings), [])
        self.assertEqual(warnings[0]["airlines"], ["Singapore Airlines"])
        self.assertEqual(warnings[0]["status"], "price_unavailable")
        self.assertEqual(warnings[0]["return_date"], "2027-01-30")
        with tempfile.TemporaryDirectory() as folder:
            snapshot = str(Path(folder) / "unpriced.json")
            code, payload = self.cli(["search", "--dest", "DAC", "--start-date", "2027-01-01", "--end-date", "2027-01-30", "--trip-lengths", "30", "--output", snapshot])
            self.assertEqual(code, 0)
            self.assertEqual(payload["source_warnings"], warnings)
            self.assertIsNone(payload["cheapest"])
            self.assertEqual(payload["source_errors"], [])
            _, filtered = self.cli(["filter", "--input", snapshot, "--airlines", "Singapore Airlines"])
            self.assertEqual(filtered["source_warnings"], warnings)
            self.assertEqual(filtered["flight_deals"], [])

    @patch("flight_browser.fill_missing_prices")
    @patch("flight_scanner._get_flights_resilient")
    def test_browser_retry_is_optional_and_recovered_quotes_use_normal_filters(self, provider, browser):
        dep, arr = NS(date=(2027, 1, 1), time=(8, 0)), NS(date=(2027, 1, 1), time=(13, 0))
        item = NS(price=None, airlines=["Singapore Airlines"], flights=[NS(from_airport=NS(code="SFO"), to_airport=NS(code="DAC"), departure=dep, arrival=arr, duration=300, plane_type="A350")])
        provider.return_value = [item]
        self.assertEqual(scan_route("SFO", "DAC", "2027-01-01", "2027-01-06"), [])
        browser.assert_not_called()
        self.assertEqual(scan_route("SFO", "DAC", "2027-01-01", "2027-01-06", browser_missing=True, browser_airlines=["Emirates"]), [])
        browser.assert_not_called()
        def recover(*args, **kwargs):
            item.price, item.price_source, item.price_checked_at = 995, "google_flights_browser", "2026-10-13T12:00:00+00:00"
            return {"status": "recovered", "recovered": 1}
        browser.side_effect = recover
        attempts, warnings, phases = [], [], []
        fares = scan_route("SFO", "DAC", "2027-01-01", "2027-01-06", browser_missing=True, browser_engine="chrome", browser_airlines=["singapore airlines"], browser_attempts=attempts, source_warnings=warnings, browser_callback=lambda: phases.append("browser"))
        self.assertEqual(fares[0]["price"], 995)
        self.assertEqual(fares[0]["price_source"], "google_flights_browser")
        self.assertEqual(attempts[0]["recovered"], 1)
        self.assertEqual(warnings, [])
        self.assertEqual(phases, ["browser"])
        self.assertEqual(filter_fares(fares, max_price=900), [])

    @patch("flight_scanner.scan_route")
    def test_saved_filter_is_repeatable_offline_and_can_relax_local_limits(self, route):
        def fares(**query):
            return [{"origin": query["origin"], "destination": query["destination"], "departure_date": query["dep_date"], "return_date": query["ret_date"], "price": 500, "airline": "United", "stops": 1, "total_journey_duration": "8h 0m", "layovers": [{"duration_min": 60}]}]
        route.side_effect = fares
        with tempfile.TemporaryDirectory() as folder:
            snapshot = str(Path(folder) / "search.json")
            code, payload = self.cli(["search", "--start-date", "2027-01-01", "--end-date", "2027-01-06", "--dest", "cancun", "--max-price", "400", "--output", snapshot])
            self.assertEqual(code, 0)
            self.assertEqual(payload["flight_deals"], [])
            self.assertEqual(payload["matrix"][0]["cells"][0]["status"], "filtered_out")
            route.reset_mock()
            args = ["filter", "--input", snapshot, "--max-price", "600"]
            first = self.cli(args)[1]
            self.assertEqual(first, self.cli(args)[1])
            self.assertEqual(first["cheapest"]["price"], 500)
            self.assertEqual(first["checked_at"], payload["checked_at"])
            route.assert_not_called()

    def test_invalid_cli_inputs_report_usage_errors(self):
        for extra in [("--date-step-days", "0"), ("--max-price", "nan"), ("--trip-lengths", "1"), ("--airlines", ", ")]:
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(self.search_args("--dry-run", *extra))
                self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
