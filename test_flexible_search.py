import unittest
from unittest.mock import Mock, patch

from flight_scanner import (
    _drop_unpriced_flight_groups,
    _get_flights_resilient,
    generate_date_pairs_between,
    generate_target_date_pairs,
)


class FlexibleDateTests(unittest.TestCase):
    def test_skips_google_result_groups_without_a_price(self):
        priced = ["flight", [[None, 1229]]]
        unpriced = ["flight", []]
        payload = [None, None, None, [[priced, unpriced]]]

        self.assertEqual(_drop_unpriced_flight_groups(payload), 1)
        self.assertEqual(payload[3][0], [priced])

    @patch("flight_scanner.LexborHTMLParser")
    @patch("flight_scanner.fetch_flights_html", return_value="<html></html>")
    @patch("flight_scanner.get_flights", side_effect=TypeError("'NoneType' object is not subscriptable"))
    def test_null_google_result_slot_is_a_successful_empty_search(
        self, get_flights, fetch_html, html_parser
    ):
        script = Mock()
        script.text.return_value = "data:[null,null,null,null],"
        html_parser.return_value.css_first.return_value = script

        self.assertEqual(_get_flights_resilient("query"), [])

    def test_generates_requested_trip_lengths_inside_date_range(self):
        pairs = generate_date_pairs_between("2027-03-01", "2027-03-15", [4, 7], step_days=7)
        self.assertEqual(pairs, [("2027-03-01", "2027-03-05"), ("2027-03-01", "2027-03-08"), ("2027-03-08", "2027-03-12"), ("2027-03-08", "2027-03-15")])

    def test_rejects_an_invalid_date_range(self):
        with self.assertRaises(ValueError):
            generate_date_pairs_between("2027-04-01", "2027-03-01", [7])

    def test_monthly_searches_generate_each_requested_trip_duration(self):
        pairs = generate_target_date_pairs(["2026-11"], trip_durations_days=[6, 7])
        self.assertEqual(len(pairs), 6)
        self.assertEqual(pairs[:2], [("2026-11-06", "2026-11-12"), ("2026-11-06", "2026-11-13")])


if __name__ == "__main__":
    unittest.main()
