import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

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
