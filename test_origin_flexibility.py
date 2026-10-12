import unittest
from unittest.mock import patch

from flight_scanner import FlightLookupError, scan_route, scan_flights


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

    @patch("flight_scanner.get_flights", side_effect=RuntimeError("DNS unavailable"))
    def test_surfaces_provider_failures_instead_of_returning_no_deals(self, get_flights):
        with self.assertRaisesRegex(FlightLookupError, "DNS unavailable"):
            scan_route("SFO", "CUN", "2026-11-13", "2026-11-20")

    @patch("flight_scanner.scan_route", side_effect=[FlightLookupError("temporary failure"), []])
    def test_continues_after_an_individual_provider_failure(self, scan_route):
        source_errors = []
        self.assertEqual(
            scan_flights(
                origins=["SFO"],
                destinations=["CUN"],
                date_pairs=[("2026-11-13", "2026-11-20"), ("2026-11-20", "2026-11-27")],
                delay_between_requests=0,
                source_errors=source_errors,
            ),
            [],
        )
        self.assertEqual(scan_route.call_count, 2)
        self.assertEqual(
            source_errors,
            [{
                "component": "cash_flights",
                "status": "unavailable",
                "origin": "SFO",
                "destination": "CUN",
                "departure_date": "2026-11-13",
                "return_date": "2026-11-20",
                "message": "temporary failure",
            }],
        )

    @patch("flight_scanner.time.sleep")
    @patch("flight_scanner.get_flights", side_effect=[RuntimeError("temporary failure"), []])
    def test_retries_a_transient_provider_failure(self, get_flights, sleep):
        self.assertEqual(scan_route("SFO", "CUN", "2026-11-13", "2026-11-20"), [])
        self.assertEqual(get_flights.call_count, 2)
        sleep.assert_called_once()

    @patch("flight_scanner.scan_route")
    def test_orders_equal_price_fares_deterministically(self, scan_route):
        base = {
            "origin": "SFO",
            "destination": "BZE",
            "departure_date": "2026-11-08",
            "return_date": "2026-11-15",
            "price": 630,
        }
        scan_route.return_value = [
            {**base, "airline": "Zulu", "stops": 1, "total_journey_duration": "12h 0m"},
            {**base, "airline": "Alpha", "stops": 1, "total_journey_duration": "10h 0m"},
            {**base, "airline": "Bravo", "stops": 0, "total_journey_duration": "14h 0m"},
        ]

        deals = scan_flights(
            origins=["SFO"],
            destinations=["BZE"],
            date_pairs=[("2026-11-08", "2026-11-15")],
            delay_between_requests=0,
        )

        self.assertEqual([deal["airline"] for deal in deals], ["Bravo", "Alpha", "Zulu"])


if __name__ == "__main__":
    unittest.main()
