import unittest
from unittest.mock import patch

from flight_scanner import scan_flights


class OriginFlexibilityTests(unittest.TestCase):
    @patch("flight_scanner.scan_route", return_value=[])
    def test_accepts_any_iata_origin_not_just_bay_area_airports(self, scan_route):
        scan_flights(
            origins=["ORD", "MDW"],
            destinations=["LHR"],
            date_pairs=[("2027-05-10", "2027-05-17")],
            delay_between_requests=0,
        )
        self.assertEqual(
            [(call.kwargs["origin"], call.kwargs["destination"]) for call in scan_route.call_args_list],
            [("ORD", "LHR"), ("MDW", "LHR")],
        )


if __name__ == "__main__":
    unittest.main()
