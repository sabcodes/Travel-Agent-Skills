import unittest
from unittest.mock import patch

from flight_scanner import scan_flights


class BeachPresetTests(unittest.TestCase):
    @patch("flight_scanner.scan_route", return_value=[])
    def test_new_beach_regions_resolve_to_expected_airports(self, scan_route):
        scan_flights(
            origins=["SFO"],
            destinations=["brazil", "peru", "guatemala", "maui"],
            date_pairs=[("2027-01-15", "2027-01-22")],
            delay_between_requests=0,
        )
        self.assertEqual(
            [call.kwargs["destination"] for call in scan_route.call_args_list],
            ["GIG", "LIM", "GUA", "OGG"],
        )


if __name__ == "__main__":
    unittest.main()
