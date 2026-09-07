import unittest
from unittest.mock import patch

from stay_scanner import package_flights_with_stays, scan_airbnb_stays


class StayScannerTests(unittest.TestCase):
    @patch("stay_scanner.pyairbnb.search_all")
    def test_keeps_three_cheapest_stays_under_budget(self, search_all):
        search_all.return_value = [
            {"room_id": "a", "name": "Over budget", "price": {"unit": {"amount": 275}, "total": {"amount": 1925}}},
            {"room_id": "b", "name": "Second", "price": {"unit": {"amount": 130}, "total": {"amount": 910}}, "rating": {"value": 4.8}, "title": "Home", "structuredContent": {"mapPrimaryLine": [{"body": "2 bedrooms"}, {"body": "3 beds"}, {"body": "1.5 baths"}]}},
            {"room_id": "c", "name": "Cheapest", "price": {"unit": {"amount": 90}, "total": {"amount": 630}}},
            {"room_id": "d", "name": "Third", "price": {"unit": {"amount": 150}, "total": {"amount": 1050}}},
            {"room_id": "e", "name": "Fourth", "price": {"unit": {"amount": 170}, "total": {"amount": 1190}}},
        ]
        stays = scan_airbnb_stays("CUN", "2026-11-13", "2026-11-20", max_nightly_usd=175, adults=4)
        self.assertEqual([stay["name"] for stay in stays], ["Cheapest", "Second", "Third"])
        self.assertIn("adults=4", stays[0]["url"])
        self.assertEqual(stays[1]["bedrooms"], 2)
        self.assertEqual(stays[1]["beds"], 3)
        self.assertEqual(stays[1]["bathrooms"], 1.5)

    @patch("stay_scanner.pyairbnb.get_details")
    @patch("stay_scanner.pyairbnb.search_all")
    def test_details_are_fetched_only_when_requested(self, search_all, get_details):
        search_all.return_value = [{"room_id": "123", "name": "Detailed", "price": {"unit": {"amount": 100}, "total": {"amount": 700}}}]
        get_details.return_value = {"room_type": "Entire home/apt", "person_capacity": 4, "coordinates": {"latitude": 1, "longitude": 2}, "amenities": [{"values": [{"title": "Wifi", "available": True}]}], "images": [{"url": "https://image.example/1"}], "rating": {"guest_satisfaction": 4.9}, "reviews": []}
        stays = scan_airbnb_stays("CUN", "2026-11-13", "2026-11-20", include_details=True)
        self.assertEqual(stays[0]["details"]["amenities"], ["Wifi"])
        self.assertEqual(get_details.call_args.kwargs["adults"], 2)

    @patch("stay_scanner.pyairbnb.search_all")
    def test_converts_a_stay_total_to_a_nightly_rate(self, search_all):
        search_all.return_value = [
            {"room_id": "total", "name": "Seven-night total", "price": {"unit": {"amount": 700, "qualifier": "for 7 nights"}, "total": {"amount": 0}}},
        ]
        stays = scan_airbnb_stays("CUN", "2026-11-13", "2026-11-20", max_nightly_usd=150)
        self.assertEqual(stays[0]["nightly_rate"], 100)
        self.assertTrue(stays[0]["total_price_is_estimate"])
        self.assertEqual(stays[0]["total_price"], 700)

    @patch("stay_scanner.scan_airbnb_stays", return_value=[])
    def test_packages_flight_dates_and_caches_duplicate_route_dates(self, scanner):
        flights = [
            {"origin": "SFO", "destination": "CUN", "departure_date": "2026-11-13", "return_date": "2026-11-20"},
            {"origin": "SJC", "destination": "CUN", "departure_date": "2026-11-13", "return_date": "2026-11-20"},
        ]
        packages = package_flights_with_stays(flights)
        self.assertEqual(len(packages), 2)
        self.assertEqual(scanner.call_count, 1)
        self.assertEqual(scanner.call_args.kwargs["check_in_str"], "2026-11-13")


if __name__ == "__main__":
    unittest.main()
