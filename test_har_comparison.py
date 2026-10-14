import base64
import json
from pathlib import Path
import tempfile
import unittest
from compare_flight_hars import compare, read_capture


def capture(price, reference=False, encoded=False, duplicate=False):
    filters = [None] * 14
    outbound, returning = [None] * 10, [None] * 10
    for segment, day, origin, destination in ((outbound, "2027-01-12", "SFO", "DAC"), (returning, "2027-02-13", "DAC", "SFO")):
        segment[4], segment[6], segment[8], segment[9] = ["SQ"], day, [[origin, 0]], [[destination, 0]]
    filters[13] = [outbound, returning]
    query = [None, filters, 0, 1, 0, 2]
    leg = [None] * 23
    leg[3], leg[6], leg[8], leg[10], leg[11], leg[20], leg[21] = "SFO", "DAC", [9, 40], [22, 40], 1380, [2027, 1, 12], [2027, 1, 13]
    group = [["single", ["Singapore Airlines"], [leg]], [[None, price]]]
    payload = [None] * 31
    payload[3] = [[group, group] if duplicate else [group]]
    if reference:
        payload[30] = [[None, 1039], "PRIVATE_CONTEXT_STUB"]
    body = json.dumps([["wrb.fr", None, json.dumps(payload)]])
    content = {"text": base64.b64encode(body.encode()).decode(), "encoding": "base64"} if encoded else {"text": body}
    return {"log": {"entries": [{"request": {
        "url": "https://www.google.com/travel/flights/_/FlightsFrontendService/GetShoppingResults?f.sid=PRIVATE_SESSION_STUB",
        "headers": [{"name": "Cookie", "value": "PRIVATE_COOKIE_STUB"}, {"name": "x-goog-batchexecute-bgr", "value": "PRIVATE_GUARD_STUB"}],
        "postData": {"params": [{"name": "f.req", "value": json.dumps([None, json.dumps(query)])}]}},
        "response": {"status": 200, "content": content}}]}}


class HarComparisonTests(unittest.TestCase):
    def save(self, folder, name, data):
        path = Path(folder) / (name + ".har")
        path.write_text(json.dumps(data))
        return path

    def test_identical_search_json_can_have_different_prices(self):
        with tempfile.TemporaryDirectory() as folder:
            human = self.save(folder, "human", capture(1039, reference=True))
            chrome = self.save(folder, "chrome", capture(None))
            result = compare({"human": human, "chrome": chrome})
        self.assertEqual(result["matching_mode_comparisons"][0]["all_query_differences"], [])
        self.assertEqual(result["matched_itineraries"][0]["human_prices"], [1039])
        self.assertEqual(result["matched_itineraries"][0]["agent_prices"], [None])

    def test_reference_amount_is_not_counted_as_a_flight_price(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.save(folder, "human", capture(None, reference=True))
            public, internal = read_capture(path)
        self.assertTrue(public["shopping"][0]["response_price_reference_present"])
        self.assertEqual(public["shopping"][0]["response_reference_amounts"], [1039])
        self.assertEqual(public["unique_priced_singapore_itineraries"], 0)
        self.assertIsNone(public["shopping"][0]["rows"][0]["price"])

    def test_private_values_are_not_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.save(folder, "human", capture(1039, reference=True))
            public, internal = read_capture(path)
        rendered = json.dumps(public)
        for value in ("PRIVATE_CONTEXT_STUB", "PRIVATE_COOKIE_STUB", "PRIVATE_GUARD_STUB", "PRIVATE_SESSION_STUB"):
            self.assertNotIn(value, rendered)
        self.assertTrue(public["shopping"][0]["bot_guard_present"])

    def test_base64_and_duplicate_frames_preserve_unique_count(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.save(folder, "human", capture(1039, encoded=True, duplicate=True))
            public, internal = read_capture(path)
        self.assertEqual(len(public["shopping"][0]["rows"]), 2)
        self.assertEqual(public["unique_priced_singapore_itineraries"], 1)


if __name__ == "__main__":
    unittest.main()
