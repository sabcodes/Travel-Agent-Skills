import unittest
import json
from unittest.mock import patch
from evaluate_lightpanda import verified_quotes, final_capture_quotes
from test_har_comparison import capture


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.row = {"price": 1039, "signature": "1 stop flight with Singapore Airlines. SFO to DAC. Total duration 23 hr."}
        self.label = "From 1,039 US dollars round trip total. " + self.row["signature"] + " Select flight"

    def snapshots(self, label, stage="cheapest", selected="true"):
        return [{"stage": stage, "labels": [label], "tabs": [{"label": "Cheapest from $1,039", "selected": selected}]}]

    def test_requires_matching_network_and_visible_row_price(self):
        self.assertEqual(verified_quotes([self.row], self.snapshots(self.label)), [self.row])
        self.assertEqual(verified_quotes([], self.snapshots(self.label)), [])
        self.assertEqual(verified_quotes([self.row], self.snapshots(self.label.replace("1,039", "1,258"))), [])

    def test_header_unknown_price_and_other_currency_do_not_count(self):
        for label in ("Cheapest from $1,039", "Total price is unavailable. " + self.row["signature"],
                      self.label.replace("US dollars", "euros"), self.label.replace("round trip", "one way")):
            with self.subTest(label=label):
                self.assertEqual(verified_quotes([self.row], self.snapshots(label)), [])

    def test_different_itinerary_and_mixed_cabin_do_not_count(self):
        for label in (self.label.replace("23 hr", "47 hr"), self.label + " Premium Economy + Economy"):
            self.assertEqual(verified_quotes([self.row], self.snapshots(label)), [])

    def test_best_view_and_unselected_cheapest_final_do_not_count(self):
        self.assertEqual(verified_quotes([self.row], self.snapshots(self.label, "best")), [])
        self.assertEqual(verified_quotes([self.row], self.snapshots(self.label, "final", "false")), [])
        self.assertEqual(verified_quotes([self.row], self.snapshots(self.label, "final")), [self.row])

    def capture_report(self, label=None):
        return {"status": "complete_requires_price_verification", "final_state": {
            "labels": [self.label if label is None else label],
            "tabs": [{"label": "Cheapest", "selected": "true"}]}}

    @patch("evaluate_lightpanda.candidate_quotes")
    def test_final_capture_requires_both_leg_filters(self, decode):
        decode.return_value = [self.row]
        har = capture(1039)
        self.assertEqual(final_capture_quotes(har, self.capture_report()), [self.row])
        form = har["log"]["entries"][0]["request"]["postData"]["params"][0]
        outer = json.loads(form["value"])
        query = json.loads(outer[1])
        query[1][13][1][4] = None
        form["value"] = json.dumps([None, json.dumps(query)])
        self.assertEqual(final_capture_quotes(har, self.capture_report()), [])

    @patch("evaluate_lightpanda.candidate_quotes")
    def test_withdrawn_transient_quote_is_rejected(self, decode):
        decode.return_value = [self.row]
        report = self.capture_report("Total price is unavailable. " + self.row["signature"])
        report["snapshots"] = self.snapshots(self.label)
        self.assertEqual(final_capture_quotes(capture(1039), report), [])

    @patch("evaluate_lightpanda.candidate_quotes")
    def test_failed_flow_cannot_pass_with_stale_priced_rows(self, decode):
        decode.return_value = [self.row]
        report = self.capture_report()
        report["status"] = "unavailable"
        self.assertEqual(final_capture_quotes(capture(1039), report), [])

    @patch("evaluate_lightpanda.candidate_quotes")
    def test_wrong_dates_cannot_be_verified(self, decode):
        decode.return_value = [self.row]
        self.assertEqual(final_capture_quotes(capture(1039), self.capture_report(), "five_day_singapore"), [])


if __name__ == "__main__":
    unittest.main()
