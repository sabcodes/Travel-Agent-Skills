"""Public synthetic fixtures for native Chrome quote validation and cleanup."""
import copy
import json
import time
import unittest
from urllib.parse import urlencode
from unittest.mock import Mock, patch

from fast_flights import FlightQuery, create_filter
from flight_native_browser import ChromeSession, fill_native_prices, matching_request, verified_rows
from test_flight_browser import LABEL, itinerary


def query(stops=None):
    return create_filter(flights=[FlightQuery(date="2027-01-14", from_airport="SFO", to_airport="DAC"),
                                  FlightQuery(date="2027-02-09", from_airport="DAC", to_airport="SFO")],
                         trip="round-trip", currency="USD", max_stops=stops)


def request(stops=0):
    main = [None] * 14
    main[2], main[6] = 1, [1, 0, 0, 0]
    main[13] = [[[[[a, 0]]], [[[b, 0]]], None, stops, ["SQ"], None, d]
                for a, b, d in [("SFO", "DAC", "2027-01-14"), ("DAC", "SFO", "2027-02-09")]]
    return [None, main]


def post(value):
    return urlencode({"f.req": json.dumps([None, json.dumps(value)])})


def state(labels=None):
    return {"body": "Departing flights. 5 results returned", "labels": [LABEL] if labels is None else labels,
            "tabs": [{"label": "Cheapest from $995", "selected": "true"}]}


class NativeBrowserTests(unittest.TestCase):
    def test_exact_both_direction_request_scope_and_live_stop_limit(self):
        self.assertTrue(matching_request(post(request()), query(), ["SQ"]))
        self.assertTrue(matching_request(post(request(2)), query(1), ["SQ"]))
        for change in (lambda r: r[1][13][1].__setitem__(6, "2027-02-10"),
                       lambda r: r[1][13][1].__setitem__(4, []),
                       lambda r: r[1][13][0].__setitem__(0, [[["SJC", 0]]]),
                       lambda r: r[1].__setitem__(2, 2), lambda r: r[1].__setitem__(6, [4, 0, 0, 0])):
            value = request()
            change(value)
            self.assertFalse(matching_request(post(value), query(), ["SQ"]))
        self.assertFalse(matching_request(post(request()), query(1), ["SQ"]))
        self.assertFalse(matching_request("invalid", query(), ["SQ"]))

    def test_only_final_network_and_individual_dom_agreement_qualifies(self):
        row = itinerary()
        row.price = 995
        matched = verified_rows([row, row], state(), {"Singapore Airlines"})
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].price_source, "google_flights_native_chrome")
        self.assertEqual(row.price, 995)
        for labels in ([], [LABEL.replace("995", "1214")], [LABEL + " Premium Economy + Economy"],
                       [LABEL.replace("23 hr", "47 hr")], [LABEL, LABEL.replace("995", "1200")]):
            self.assertEqual(verified_rows([row], state(labels), {"Singapore Airlines"}), [])
        for body in ("Oops, something went wrong", "unusual traffic"):
            final = state()
            final["body"] = body
            self.assertEqual(verified_rows([row], final, {"Singapore Airlines"}), [])
        loading = state()
        loading["loading"] = True
        self.assertEqual(verified_rows([row], loading, {"Singapore Airlines"}), [])
        final = state()
        final["tabs"][0]["selected"] = "false"
        self.assertEqual(verified_rows([row], final, {"Singapore Airlines"}), [])
        self.assertEqual(verified_rows([row], state(), {"United"}), [])

    def test_setup_failure_preserves_saved_schedules_and_redacts_details(self):
        items = [itinerary()]
        before = copy.deepcopy(items)
        with patch("flight_native_browser.chrome_binary", return_value=None):
            report = fill_native_prices(query(), items)
        self.assertEqual(report["failure_kind"], "setup")
        self.assertEqual(report["recovered"], 0)
        self.assertEqual(items, before)
        with patch("flight_native_browser.ChromeSession.__enter__", side_effect=RuntimeError("private local details")):
            report = fill_native_prices(query(), items)
        self.assertNotIn("private", json.dumps(report))

    def test_owned_browser_is_closed_and_profile_removed_on_failure(self):
        session = ChromeSession(time.monotonic() + 5)
        session.websocket, session.process, session.profile = Mock(), Mock(), Mock()
        session.process.poll.return_value = None
        session.__exit__(None, None, None)
        session.websocket.terminate.assert_called_once()
        session.process.terminate.assert_called_once()
        session.profile.cleanup.assert_called_once()

    def test_cleanup_still_closes_browser_when_socket_cleanup_fails(self):
        session = ChromeSession(time.monotonic() + 5)
        session.websocket, session.process, session.profile = Mock(), Mock(), Mock()
        session.websocket.terminate.side_effect = RuntimeError("socket already closed")
        session.process.poll.return_value = None
        with self.assertRaises(RuntimeError):
            session.__exit__(None, None, None)
        session.process.terminate.assert_called_once()
        session.profile.cleanup.assert_called_once()

    def test_deadline_is_enforced(self):
        with self.assertRaises(TimeoutError):
            ChromeSession(time.monotonic() - 1).remaining()


if __name__ == "__main__":
    unittest.main()
