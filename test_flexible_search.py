import unittest

from flight_scanner import _drop_unpriced_flight_groups, generate_date_pairs_between, generate_target_date_pairs


class FlexibleDateTests(unittest.TestCase):
    def test_skips_google_result_groups_without_a_price(self):
        priced = ["flight", [[None, 1229]]]
        unpriced = ["flight", []]
        payload = [None, None, None, [[priced, unpriced]]]

        self.assertEqual(_drop_unpriced_flight_groups(payload), 1)
        self.assertEqual(payload[3][0], [priced])

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
