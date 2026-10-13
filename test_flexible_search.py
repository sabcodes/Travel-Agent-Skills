import unittest
import json
from unittest.mock import Mock, patch

from flight_scanner import (
    _get_flights_resilient,
    generate_date_pairs_between,
    generate_target_date_pairs,
)


class FlexibleDateTests(unittest.TestCase):
    @patch("flight_scanner.LexborHTMLParser")
    @patch("flight_scanner.fetch_flights_html", return_value="<html></html>")
    def test_null_google_result_slot_is_a_successful_empty_search(
        self, fetch_html, html_parser
    ):
        script = Mock()
        script.text.return_value = "data:[null,null,null,null],"
        html_parser.return_value.css_first.return_value = script

        self.assertEqual(_get_flights_resilient("query"), [])

    @patch("flight_scanner.parse_js")
    @patch("flight_scanner.LexborHTMLParser")
    @patch("flight_scanner.fetch_flights_html", return_value="<html></html>")
    def test_reads_best_and_other_flights_and_reports_unpriced_carriers(self, fetch_html, html_parser, parse_js):
        best = [[None, ["Emirates"]], [[None, 1494]]]
        other = [[None, ["Qatar Airways"]], [[None, 4015]]]
        unpriced = [[None, ["Singapore Airlines"]], [[[], "opaque itinerary reference"]]]
        payload = [None, None, [[best]], [[other, best, unpriced]]]
        html_parser.return_value.css_first.return_value.text.return_value = f"data:{json.dumps(payload)},"
        class Results(list):
            pass
        parse_js.return_value = Results(["best fare", "other fare"])

        results = _get_flights_resilient("query")
        parsed = json.loads(parse_js.call_args.args[0][5:-1])
        self.assertEqual(parsed[3][0], [best, other, [[None, ["Singapore Airlines"]], [[None, None]]]])
        self.assertEqual(results.unpriced_airlines, ["Singapore Airlines"])
        fetch_html.assert_called_once_with("query")

    def test_generates_requested_trip_lengths_inside_date_range(self):
        pairs = generate_date_pairs_between("2027-03-01", "2027-03-15", [4, 7], step_days=7)
        self.assertEqual(pairs, [("2027-03-01", "2027-03-04"), ("2027-03-01", "2027-03-07"), ("2027-03-08", "2027-03-11"), ("2027-03-08", "2027-03-14")])

    def test_rejects_an_invalid_date_range(self):
        with self.assertRaises(ValueError):
            generate_date_pairs_between("2027-04-01", "2027-03-01", [7])

    def test_monthly_searches_generate_each_requested_trip_duration(self):
        pairs = generate_target_date_pairs(["2026-11"], trip_durations_days=[6, 7])
        self.assertEqual(len(pairs), 10)
        self.assertEqual(pairs[:2], [("2026-11-01", "2026-11-06"), ("2026-11-01", "2026-11-07")])


if __name__ == "__main__":
    unittest.main()
