import unittest

from flight_scanner import generate_date_pairs_between


class FlexibleDateTests(unittest.TestCase):
    def test_generates_requested_trip_lengths_inside_date_range(self):
        pairs = generate_date_pairs_between("2027-03-01", "2027-03-15", [4, 7], step_days=7)
        self.assertEqual(pairs, [("2027-03-01", "2027-03-05"), ("2027-03-01", "2027-03-08"), ("2027-03-08", "2027-03-12"), ("2027-03-08", "2027-03-15")])

    def test_rejects_an_invalid_date_range(self):
        with self.assertRaises(ValueError):
            generate_date_pairs_between("2027-04-01", "2027-03-01", [7])


if __name__ == "__main__":
    unittest.main()
