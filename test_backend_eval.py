import unittest

from evaluate_flight_backends import summarize


class BackendEvaluationTests(unittest.TestCase):
    def test_return_option_is_not_ranked_as_outbound_starting_price(self):
        report = summarize({"rows": [{"outbound": {"price": 618, "currency": "USD"},
                                      "return": {"price": 749, "currency": "USD"}}]})
        self.assertEqual(report["minimum_starting_quote"], 618)
        self.assertEqual(report["minimum_selected_pair_quote"], 749)
        self.assertEqual(report["differing_pair_quotes"], 1)

    def test_unknown_price_stays_unknown_and_preserves_carrier_notices(self):
        report = summarize({"rows": [{"outbound": {"price": None, "airlines": ["SQ"]},
                                      "return": {"price": None, "currency": None}}]})
        self.assertEqual(report["priced_count"], 0)
        self.assertIsNone(report["minimum_starting_quote"])
        self.assertIsNone(report["minimum_selected_pair_quote"])
        self.assertEqual(report["unpriced_airlines"], ["SQ"])
        self.assertEqual(summarize({"warnings": [{"airlines": ["Singapore Airlines"]}]})["unpriced_airlines"], ["Singapore Airlines"])

    def test_invalid_quotes_and_other_currencies_do_not_enter_usd_pair_minimum(self):
        report = summarize({"rows": [{"outbound": {"price": float("nan")}, "return": {"price": 500, "currency": "EUR"}},
                                      {"outbound": {"price": True}, "return": {"price": float("inf"), "currency": "USD"}}]})
        self.assertEqual(report["priced_count"], 0)
        self.assertEqual(report["selected_pair_priced_count"], 0)
        self.assertIsNone(report["minimum_selected_pair_quote"])


if __name__ == "__main__":
    unittest.main()
