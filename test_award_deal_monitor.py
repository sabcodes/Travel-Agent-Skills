import json
import unittest
from types import SimpleNamespace
from unittest.mock import mock_open, patch

from award_deal_monitor import (
    attach_transfer_deals,
    fetch_award_deals,
    match_configured_destinations,
    parse_award_entry,
)


def load_config():
    with open("config.json", "r", encoding="utf-8") as config_file:
        return json.load(config_file)


class AwardDestinationCoverageTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_checked_in_config_has_twelve_regions_and_excludes_dhaka(self):
        self.assertEqual(
            {destination["region"] for destination in self.config["destinations"]},
            {
                "cancun", "jamaica", "puerto_rico", "costa_rica", "brazil", "peru",
                "guatemala", "maui", "belize", "mexico_city", "saint_lucia",
                "roatan_bay_islands",
            },
        )
        self.assertEqual(
            {
                destination["code"]
                for destination in self.config["destinations"]
                if destination["region"] in {"belize", "mexico_city", "saint_lucia", "roatan_bay_islands"}
            },
            {"BZE", "MEX", "UVF", "RTB"},
        )
        self.assertNotIn("dhaka", json.dumps(self.config).lower())
        self.assertNotIn('"dac"', json.dumps(self.config).lower())

    def test_matches_each_configured_region_by_public_place_name(self):
        cases = {
            "Cancun": "cancun",
            "Jamaica": "jamaica",
            "Puerto Rico": "puerto_rico",
            "Costa Rica": "costa_rica",
            "Brazil": "brazil",
            "Peru": "peru",
            "Guatemala": "guatemala",
            "Maui": "maui",
            "Belize": "belize",
            "Mexico City": "mexico_city",
            "St. Lucia": "saint_lucia",
            "Roatán": "roatan_bay_islands",
        }
        for place_name, expected_region in cases.items():
            with self.subTest(place_name=place_name):
                airport_codes, regions, match_level = match_configured_destinations(
                    f"New business-class award space to {place_name}", self.config
                )
                self.assertIn(expected_region, regions)
                self.assertEqual(match_level, "regional-match")
                self.assertEqual(airport_codes, [])

    def test_mexico_country_name_does_not_also_match_mexico_city(self):
        airport_codes, regions, match_level = match_configured_destinations(
            "New award space to Cancun, Mexico", self.config
        )

        self.assertEqual(airport_codes, [])
        self.assertEqual(regions, ["cancun"])
        self.assertEqual(match_level, "regional-match")

    def test_dhaka_is_not_a_fallback_destination(self):
        airport_codes, regions, match_level = match_configured_destinations(
            "SFO to Dhaka (DAC) award seats from 70,000 miles", self.config
        )
        self.assertEqual(airport_codes, [])
        self.assertEqual(regions, [])
        self.assertEqual(match_level, "general-sale")

    def test_full_feed_pipeline_returns_all_twelve_regions_but_not_dhaka(self):
        config = dict(self.config)
        config.update({
            "award_deal_feeds": [{"name": "Twelve Region Fixture", "url": "https://feeds.example/twelve"}],
            "award_deal_max_age_days": 365,
            "include_general_award_sales": False,
        })
        places = (
            "Cancun", "Jamaica", "Puerto Rico", "Costa Rica", "Brazil", "Peru",
            "Guatemala", "Maui", "Belize", "Mexico City", "St. Lucia", "Roatán",
        )
        items = [
            {
                "title": f"Award space to {place} in December 2026 from 20,000 miles",
                "summary": "Reported economy redemption opportunity.",
                "link": f"https://publisher.example/{place.casefold().replace(' ', '-')}",
            }
            for place in places
        ]
        items.append({
            "title": "Award space to Dhaka DAC in December 2026 from 20,000 miles",
            "summary": "Control item outside the configured destinations.",
            "link": "https://publisher.example/dhaka",
        })

        with patch("award_deal_monitor.open", mock_open(read_data=json.dumps(config)), create=True):
            leads = fetch_award_deals(
                months=["2026-12"], fetch_content=lambda session, url: rss_document(*items)
            )

        self.assertEqual(len(leads), 12)
        self.assertEqual(
            {lead["matched_regions"][0] for lead in leads},
            {
                "cancun", "jamaica", "puerto_rico", "costa_rica", "brazil", "peru",
                "guatemala", "maui", "belize", "mexico_city", "saint_lucia",
                "roatan_bay_islands",
            },
        )
        self.assertNotIn("dhaka", json.dumps(leads).lower())


class AwardEntryParsingTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_extracts_only_stated_award_facts_for_an_exact_route(self):
        entry = SimpleNamespace(
            title="SFO to CUN business-class award space in November 2026 from 25,000 United miles",
            summary="Seats reported with $56 in taxes and fees.",
            link="https://example.com/sfo-cun-award?utm_source=rss",
            published="Sun, 13 Sep 2026 12:00:00 +0000",
        )

        lead = parse_award_entry(entry, self.config, "Example Awards")

        self.assertEqual(lead["origins"], ["SFO"])
        self.assertEqual(lead["destinations"], ["CUN"])
        self.assertEqual(lead["matched_regions"], ["cancun"])
        self.assertEqual(lead["travel_months"], ["2026-11"])
        self.assertEqual(lead["cabin"], "business")
        self.assertEqual(lead["programs"], ["United MileagePlus"])
        self.assertEqual(lead["points"], 25000)
        self.assertEqual(lead["taxes_usd"], 56.0)
        self.assertEqual(lead["match_level"], "exact-route")
        self.assertGreaterEqual(lead["confidence_score"], 80)
        self.assertEqual(lead["availability_status"], "reported")
        self.assertTrue(lead["verification_required"])
        self.assertEqual(lead["source_url"], "https://example.com/sfo-cun-award")

    def test_named_destination_without_airport_code_is_a_regional_match(self):
        entry = SimpleNamespace(
            title="Jamaica economy award deal from 18,000 Flying Blue miles in January 2027",
            summary="A newly reported redemption opportunity.",
            link="https://example.com/jamaica-award",
            published="Sun, 13 Sep 2026 12:00:00 +0000",
        )

        lead = parse_award_entry(entry, self.config, "Example Awards")

        self.assertEqual(lead["destinations"], [])
        self.assertEqual(lead["matched_regions"], ["jamaica"])
        self.assertEqual(lead["match_level"], "regional-match")
        self.assertEqual(lead["travel_months"], ["2027-01"])

    def test_rejects_generic_program_commentary(self):
        entry = SimpleNamespace(
            title="What I learned about United MileagePlus",
            summary="A general discussion of the loyalty program.",
            link="https://example.com/united-commentary",
            published="Sun, 13 Sep 2026 12:00:00 +0000",
        )

        self.assertIsNone(parse_award_entry(entry, self.config, "Example Awards"))

    def test_rejects_credit_card_bonus_articles_as_award_fares(self):
        entry = SimpleNamespace(
            title="Earn 75,000 points with a new card for your Cancun trip",
            summary="A welcome-offer review for new applicants.",
            link="https://example.com/card-bonus",
            published="Sun, 13 Sep 2026 12:00:00 +0000",
        )

        self.assertIsNone(parse_award_entry(entry, self.config, "Example Awards"))


def rss_document(*items):
    item_xml = "".join(
        "<item>"
        f"<title><![CDATA[{item['title']}]]></title>"
        f"<description><![CDATA[{item.get('summary', '')}]]></description>"
        f"<link>{item['link']}</link>"
        f"<pubDate>{item.get('published', 'Sun, 13 Sep 2026 12:00:00 +0000')}</pubDate>"
        "</item>"
        for item in items
    )
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>Fixture Awards</title>{item_xml}</channel></rss>".encode()


class AwardFeedTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.config.update({
            "award_deal_feeds": [
                {"name": "Broken Feed", "url": "https://feeds.example/broken"},
                {"name": "Fixture Awards", "url": "https://feeds.example/awards"},
            ],
            "award_deal_max_age_days": 365,
            "include_general_award_sales": False,
        })

    def _fetch(self, session, url):
        if url.endswith("broken"):
            raise RuntimeError("source unavailable")
        return rss_document(
            {
                "title": "SFO to CUN award deal in December 2026 from 20,000 Aeroplan points",
                "summary": "Reported economy award availability.",
                "link": "https://publisher.example/cun?utm_source=first",
            },
            {
                "title": "SFO to CUN award deal in December 2026 from 20,000 Aeroplan points",
                "summary": "Duplicate syndication.",
                "link": "https://publisher.example/cun?utm_source=second",
            },
            {
                "title": "SFO to CUN award deal in March 2027 from 20,000 Aeroplan points",
                "summary": "Outside the requested months.",
                "link": "https://publisher.example/cun-march",
            },
            {
                "title": "SFO to Dhaka DAC award deal in December 2026 from 40,000 miles",
                "summary": "Not one of the configured destinations.",
                "link": "https://publisher.example/dhaka",
            },
        )

    def test_deduplicates_links_filters_months_and_continues_after_a_source_error(self):
        with patch("award_deal_monitor.open", mock_open(read_data=json.dumps(self.config)), create=True):
            leads = fetch_award_deals(months=["2026-12"], fetch_content=self._fetch)

        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "Fixture Awards")
        self.assertEqual(leads[0]["source_url"], "https://publisher.example/cun")
        self.assertEqual(leads[0]["travel_months"], ["2026-12"])
        self.assertEqual(leads[0]["matched_regions"], ["cancun"])

    def test_destination_override_uses_a_configured_region(self):
        def jamaica_feed(session, url):
            return rss_document({
                "title": "Jamaica award space in January 2027 from 18,000 Flying Blue miles",
                "summary": "Reported economy seats.",
                "link": "https://publisher.example/jamaica",
            })

        with patch("award_deal_monitor.open", mock_open(read_data=json.dumps(self.config)), create=True):
            leads = fetch_award_deals(
                origins=["SFO"], destinations=["jamaica"], months=["2027-01"], fetch_content=jamaica_feed
            )

        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["matched_regions"], ["jamaica"])

    def test_attaches_only_overlapping_transfer_bonus_programs(self):
        award_leads = [
            {"title": "Aeroplan award", "programs": ["Air Canada Aeroplan"]},
            {"title": "United award", "programs": ["United MileagePlus"]},
        ]
        card_deals = [
            {
                "title": "Chase 20% transfer bonus to Aeroplan",
                "link": "https://publisher.example/aeroplan-bonus",
                "is_transfer_bonus": True,
                "matched_partners": ["Air Canada Aeroplan"],
            },
            {
                "title": "Capital One card welcome offer",
                "link": "https://publisher.example/card",
                "is_transfer_bonus": False,
                "matched_partners": [],
            },
        ]

        enriched = attach_transfer_deals(award_leads, card_deals)

        self.assertEqual(
            enriched[0]["matching_transfer_deals"],
            [{"title": "Chase 20% transfer bonus to Aeroplan", "link": "https://publisher.example/aeroplan-bonus"}],
        )
        self.assertEqual(enriched[1]["matching_transfer_deals"], [])


if __name__ == "__main__":
    unittest.main()
