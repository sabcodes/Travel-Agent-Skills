import unittest
import json
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import Mock, patch

from fast_flights import FlightQuery, create_filter
from flight_browser import apply_browser_prices, fill_missing_prices, shopping_response_flights


def itinerary():
    def airport(code, name):
        return NS(code=code, name=name)
    def stamp(day, hour, minute):
        return NS(date=(2027, 1, day), time=(hour, minute))
    sfo = airport("SFO", "San Francisco International Airport")
    sin = airport("SIN", "Singapore Changi Airport")
    dac = airport("DAC", "Hazrat Shahjalal International Airport")
    return NS(price=None, airlines=["Singapore Airlines"], flights=[
        NS(from_airport=sfo, to_airport=sin, departure=stamp(14, 9, 40), arrival=stamp(15, 18, 20), duration=1000),
        NS(from_airport=sin, to_airport=dac, departure=stamp(15, 19, 55), arrival=stamp(15, 22, 40), duration=285)])


LABEL = ("From 995 US dollars round trip total. 1 stop flight with Singapore Airlines. "
         "Leaves San Francisco International Airport at 9:40 AM on Thursday, January 14 "
         "and arrives at Hazrat Shahjalal International Airport at 10:40 PM on Friday, January 15. "
         "Total duration 23 hr. Select flight")


class BrowserQuoteTests(unittest.TestCase):
    def test_accepts_an_exact_quote_once_and_records_provenance(self):
        item = itinerary()
        self.assertEqual(apply_browser_prices([item], [LABEL, LABEL]), 1)
        self.assertEqual(item.price, 995)
        self.assertEqual(item.price_source, "google_flights_browser")
        self.assertIn("+00:00", item.price_checked_at)

    def test_does_not_infer_or_mismatch_prices(self):
        for label in [LABEL.replace("995", "0"), LABEL.replace("US dollars", "euros"),
                      LABEL.replace("round trip", "one way"), LABEL.replace("January 14", "January 15"),
                      LABEL.replace("23 hr", "47 hr"), LABEL.replace("From 995 US dollars round trip total", "Total price is unavailable")]:
            with self.subTest(label=label):
                item = itinerary()
                self.assertEqual(apply_browser_prices([item], [label]), 0)
                self.assertIsNone(item.price)
        first, second = itinerary(), itinerary()
        self.assertEqual(apply_browser_prices([first, second], [LABEL]), 0)
        self.assertEqual(apply_browser_prices([first], [LABEL, LABEL.replace("995", "1214")]), 0)

    def test_browser_failure_preserves_missing_price_and_redacts_runtime_details(self):
        item = itinerary()
        fake = ModuleType("playwright.sync_api")
        fake.sync_playwright = Mock(side_effect=RuntimeError("runtime details should stay private"))
        with patch.dict("sys.modules", {"playwright": ModuleType("playwright"), "playwright.sync_api": fake}):
            report = fill_missing_prices(NS(), [item])
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["recovered"], 0)
        self.assertNotIn("runtime details", report["message"])
        self.assertIsNone(item.price)

    def test_streamed_additional_itineraries_are_retained_and_wrong_routes_rejected(self):
        query = create_filter(flights=[FlightQuery(date="2027-01-14", from_airport="SFO", to_airport="DAC"),
                                      FlightQuery(date="2027-02-09", from_airport="DAC", to_airport="SFO")], trip="round-trip", currency="USD")
        def group(price, origin="SFO", day=14):
            leg = [None] * 23
            leg[3], leg[6], leg[20] = origin, "DAC", [2027, 1, day]
            return [["SQ", ["Singapore Airlines"], [leg]], [[None, price]]]
        def frame(groups):
            payload = [None, None, None, [groups], None, None, None, []]
            data = json.dumps([["wrb.fr", None, json.dumps(payload)]])
            return f"{len(data)}\n{data}\n"
        text = ")]}'\n\n" + frame([group(None)]) + frame([group(995), group(995), group(900, "LAX"), group(850, day=15)])
        with patch("fast_flights.parser.parse_js", return_value=["additional priced itinerary"]) as parser:
            self.assertEqual(shopping_response_flights(text, query, {"Singapore Airlines"}), ["additional priced itinerary"])
        self.assertEqual(len(json.loads(parser.call_args.args[0][5:-1])[3][0]), 1)


if __name__ == "__main__":
    unittest.main()
