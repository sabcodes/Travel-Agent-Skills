import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from flight_scanner import FlightLookupError
from main import run_scanner


class MainIntegrationTests(unittest.TestCase):
    @patch("main.package_flights_with_stays", return_value=[])
    @patch("main.scan_flights")
    def test_enriches_flights_before_packaging_stays(self, scan_flights, package_stays):
        scan_flights.return_value = [{
            "origin": "SFO", "destination": "CUN", "airline": "United",
            "price": 491, "departure_date": "2026-11-13", "return_date": "2026-11-20",
        }]
        with redirect_stdout(io.StringIO()):
            asyncio.run(run_scanner(scan_cc=False, scan_air=True, scan_stays=True, output_json=True))
        packaged_flight = package_stays.call_args.args[0][0]
        self.assertEqual(packaged_flight["chase_partner_info"]["alliance"], "Star Alliance")

    @patch("main.search_accommodations")
    @patch("main.package_flights_with_stays", return_value=[])
    @patch("main.scan_flights")
    def test_stay_scan_keeps_hotel_and_airbnb_links_when_flights_exist(
        self, scan_flights, package_stays, search_accommodations
    ):
        scan_flights.return_value = [{
            "origin": "SFO", "destination": "BZE", "airline": "United",
            "price": 650, "departure_date": "2026-11-13", "return_date": "2026-11-20",
        }]
        search_accommodations.return_value = [{
            "provider": "Google Hotels", "destination_name": "Belize City, Belize",
            "check_in": "2026-11-13", "check_out": "2026-11-20",
            "max_nightly_price": 400, "max_total_price": 2800,
            "booking_url": "https://example.com/hotels",
        }]
        dates = [("2026-11-13", "2026-11-20")]

        output = io.StringIO()
        with redirect_stdout(output):
            asyncio.run(run_scanner(
                scan_cc=False,
                scan_air=True,
                scan_stays=True,
                destinations=["belize"],
                date_pairs=dates,
                max_nightly_price=400,
                adults=4,
                output_json=True,
            ))

        package_stays.assert_called_once()
        search_accommodations.assert_called_once_with(
            "config.json", ["belize"], dates, 400, 4
        )
        self.assertIn('"total_accommodation_searches": 1', output.getvalue())

    @patch("main.search_accommodations")
    @patch("main.scan_flights", side_effect=FlightLookupError("provider unavailable"))
    def test_stay_scan_preserves_flight_error_and_still_returns_provider_links(
        self, scan_flights, search_accommodations
    ):
        search_accommodations.return_value = [{
            "provider": "Google Hotels", "destination_name": "St. Lucia (Hewanorra)",
            "check_in": "2027-01-08", "check_out": "2027-01-15",
            "max_nightly_price": 500, "max_total_price": 3500,
            "booking_url": "https://example.com/hotels",
        }]
        dates = [("2027-01-08", "2027-01-15")]

        output = io.StringIO()
        with redirect_stdout(output):
            asyncio.run(run_scanner(
                scan_cc=False,
                scan_air=True,
                scan_stays=True,
                destinations=["saint_lucia"],
                date_pairs=dates,
                max_nightly_price=500,
                adults=4,
                output_json=True,
            ))

        search_accommodations.assert_called_once_with(
            "config.json", ["saint_lucia"], dates, 500, 4
        )
        self.assertIn('"source_errors"', output.getvalue())
        self.assertIn('"component": "cash_flights"', output.getvalue())
        self.assertIn("provider unavailable", output.getvalue())
        self.assertIn('"total_accommodation_searches": 1', output.getvalue())

    @patch("stay_scanner.pyairbnb.search_all", side_effect=RuntimeError("provider changed"))
    @patch("main.search_accommodations", return_value=[])
    @patch("main.scan_flights")
    def test_stay_scan_emits_airbnb_provider_errors_in_json(
        self, scan_flights, search_accommodations, search_all
    ):
        scan_flights.return_value = [{
            "origin": "SFO", "destination": "CUN", "airline": "United",
            "price": 491, "departure_date": "2026-11-13", "return_date": "2026-11-20",
        }]

        output = io.StringIO()
        with redirect_stdout(output):
            asyncio.run(run_scanner(
                scan_cc=False,
                scan_air=True,
                scan_stays=True,
                date_pairs=[("2026-11-13", "2026-11-20")],
                output_json=True,
            ))

        self.assertIn('"component": "airbnb_stays"', output.getvalue())
        self.assertIn('"status": "unavailable"', output.getvalue())
        self.assertIn("provider changed", output.getvalue())

    @patch("main.scan_flights")
    @patch("main.fetch_award_deals")
    def test_award_only_scan_uses_filters_and_emits_json_without_cash_lookup(self, fetch_awards, scan_flights):
        fetch_awards.return_value = [{
            "title": "SFO to Cancun from 20,000 points",
            "source": "Fixture Awards",
            "source_url": "https://publisher.example/cancun",
            "availability_status": "reported",
            "verification_required": True,
            "programs": [],
        }]

        output = io.StringIO()
        with redirect_stdout(output):
            asyncio.run(run_scanner(
                scan_cc=False,
                scan_air=False,
                scan_awards=True,
                origins=["SFO", "SJC"],
                destinations=["cancun"],
                months=["2026-11", "2026-12", "2027-01"],
                output_json=True,
            ))

        scan_flights.assert_not_called()
        fetch_awards.assert_called_once_with(
            config_path="config.json",
            origins=["SFO", "SJC"],
            destinations=["cancun"],
            months=["2026-11", "2026-12", "2027-01"],
        )
        self.assertIn('"award_deals"', output.getvalue())
        self.assertIn('"total_award_deals": 1', output.getvalue())


if __name__ == "__main__":
    unittest.main()
