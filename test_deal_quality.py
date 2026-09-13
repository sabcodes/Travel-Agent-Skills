import unittest
import warnings
from unittest.mock import Mock, patch

import requests
from feedparser.util import FeedParserDict

from feed_monitor import (
    FeedAccessError,
    _compute_relevance_score,
    _fetch_feed_content,
    _fetch_public_feed,
    _has_deal_intent,
    _matched_card_issuers,
    _normalise_link,
    _parse_published_date,
    _robots_allows,
    detect_transfer_bonus,
    extract_bonus_percentage,
)


class DealQualityTests(unittest.TestCase):
    def test_removes_tracking_parameters_for_deduplication(self):
        self.assertEqual(
            _normalise_link("https://example.com/deal/?utm_source=rss&fbclid=abc"),
            "https://example.com/deal",
        )

    def test_generic_program_mention_is_not_a_deal(self):
        self.assertFalse(_has_deal_intent("My experience flying United last week", ["united"]))

    def test_transfer_bonus_is_a_qualifying_deal(self):
        text = "Chase has a 30% transfer bonus to Aeroplan"
        self.assertTrue(_has_deal_intent(text, ["transfer bonus", "aeroplan"]))
        self.assertTrue(detect_transfer_bonus(text))
        self.assertEqual(extract_bonus_percentage(text), 30)

    def test_confirmed_single_program_offer_reaches_minimum_score(self):
        text = "Earn 20K bonus Marriott points for a vacation stay"
        self.assertTrue(_has_deal_intent(text, ["marriott"]))
        self.assertEqual(_compute_relevance_score(["marriott"]) + 1, 2)

    def test_tags_amex_and_capital_one_offers(self):
        issuers = _matched_card_issuers("Amex Membership Rewards and Capital One Venture transfer bonus")
        self.assertEqual(issuers, ["American Express", "Capital One"])

    def test_does_not_tag_related_issuers_outside_the_headline(self):
        self.assertEqual(_matched_card_issuers("Current Amex Offers"), ["American Express"])

    @patch("feed_monitor.browser_requests")
    def test_does_not_retry_explicit_http_denial(self, browser_client):
        session = Mock()
        session.get.return_value = Mock(status_code=403, headers={})

        with self.assertRaises(FeedAccessError) as caught:
            _fetch_feed_content(session, "https://example.com/feed")

        self.assertEqual(caught.exception.status, "blocked")
        browser_client.get.assert_not_called()

    @patch("feed_monitor.browser_requests")
    def test_uses_browser_client_after_transport_failure(self, browser_client):
        session = Mock()
        session.get.side_effect = requests.exceptions.SSLError("TLS handshake failed")
        browser_client.get.return_value = Mock(status_code=200, content=b"<rss/>", headers={})

        self.assertEqual(_fetch_feed_content(session, "https://example.com/feed"), b"<rss/>")
        browser_client.get.assert_called_once()

    @patch("feed_monitor.browser_requests")
    def test_reports_rate_limit_without_immediate_retry(self, browser_client):
        session = Mock()
        session.get.return_value = Mock(status_code=429, headers={"Retry-After": "60"})

        with self.assertRaises(FeedAccessError) as caught:
            _fetch_feed_content(session, "https://example.com/feed")

        self.assertEqual(caught.exception.status, "rate-limited")
        self.assertEqual(caught.exception.retry_after, "60")
        browser_client.get.assert_not_called()

    def test_robots_allows_public_feed(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=200,
            text="User-agent: *\nAllow: /feed/\n",
            headers={},
        )

        self.assertTrue(_robots_allows(session, "https://example.com/feed/award", cache={}))

    def test_robots_disallow_stops_before_feed_fetch(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=200,
            text="User-agent: *\nDisallow: /private/\n",
            headers={},
        )

        with self.assertRaises(FeedAccessError) as caught:
            _fetch_public_feed(session, "https://example.com/private/award.xml", robots_cache={})

        self.assertEqual(caught.exception.status, "blocked")
        self.assertEqual(session.get.call_count, 1)

    def test_cached_robots_policy_is_rechecked_for_each_path(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=200,
            text="User-agent: *\nAllow: /feed/\nDisallow: /private/\n",
            headers={},
        )
        cache = {}

        self.assertTrue(_robots_allows(session, "https://example.com/feed/award", cache=cache))
        self.assertFalse(_robots_allows(session, "https://example.com/private/award", cache=cache))
        self.assertEqual(session.get.call_count, 1)

    def test_published_date_does_not_probe_deprecated_updated_alias(self):
        entry = FeedParserDict({
            "published": "Sun, 13 Sep 2026 12:00:00 +0000",
            "published_parsed": (2026, 9, 13, 12, 0, 0, 6, 256, 0),
        })
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            published = _parse_published_date(entry)
        self.assertEqual(published.isoformat(), "2026-09-13T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
