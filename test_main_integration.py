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


if __name__ == "__main__":
    unittest.main()
