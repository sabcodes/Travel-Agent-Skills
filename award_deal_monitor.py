import json
import re
import unicodedata
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Tuple

import feedparser
import requests

from feed_monitor import (
    FeedAccessError,
    USER_AGENT,
    _fetch_public_feed,
    _is_title_blocklisted,
    _is_too_old,
    _normalise_link,
    _parse_published_date,
)


MONTH_NUMBERS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

PROGRAM_KEYWORDS = {
    "United MileagePlus": ("united mileageplus", "mileageplus", "united miles"),
    "Air Canada Aeroplan": ("air canada aeroplan", "aeroplan"),
    "Air France/KLM Flying Blue": ("flying blue",),
    "Virgin Atlantic Flying Club": ("virgin atlantic flying club", "virgin points"),
    "British Airways Executive Club": ("british airways executive club", "british airways avios", "ba avios"),
    "Iberia Plus": ("iberia plus", "iberia avios"),
    "American AAdvantage": ("american aadvantage", "aadvantage"),
    "Alaska Mileage Plan": ("alaska mileage plan", "alaska miles"),
    "Southwest Rapid Rewards": ("southwest rapid rewards", "rapid rewards"),
    "Singapore KrisFlyer": ("singapore krisflyer", "krisflyer"),
    "Emirates Skywards": ("emirates skywards", "skywards"),
}


def _entry_value(entry: Any, name: str, default: str = "") -> str:
    if isinstance(entry, dict):
        return entry.get(name, default) or default
    return getattr(entry, name, default) or default


def _normalise_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", unescape(value or ""))
    ascii_text = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).split())


def _contains_phrase(normalised_text: str, phrase: str) -> bool:
    normalised_phrase = _normalise_text(phrase)
    return bool(normalised_phrase) and f" {normalised_phrase} " in f" {normalised_text} "


def _destination_aliases(destination: Dict[str, Any]) -> List[str]:
    display_name = re.sub(r"\([^)]*\)", " ", destination.get("display_name", ""))
    aliases = {
        destination.get("region", "").replace("_", " "),
        display_name,
        *(part.strip() for part in display_name.split(",")),
    }
    return sorted({_normalise_text(alias) for alias in aliases if _normalise_text(alias)}, key=len, reverse=True)


def match_configured_destinations(text: str, cfg: Dict[str, Any]) -> Tuple[List[str], List[str], str]:
    """Match only configured airport codes and place names; never infer unconfigured destinations."""
    normalised_text = _normalise_text(text)
    airport_codes: List[str] = []
    regions: List[str] = []

    for destination in cfg.get("destinations", []):
        code = str(destination.get("code", "")).upper()
        region = str(destination.get("region", ""))
        code_match = bool(code and re.search(rf"\b{re.escape(code)}\b", text, re.IGNORECASE))
        alias_match = any(_contains_phrase(normalised_text, alias) for alias in _destination_aliases(destination))
        if code_match and code not in airport_codes:
            airport_codes.append(code)
        if (code_match or alias_match) and region and region not in regions:
            regions.append(region)

    if airport_codes:
        match_level = "exact-route"
    elif regions:
        match_level = "regional-match"
    else:
        match_level = "general-sale"
    return airport_codes, regions, match_level


def _extract_origins(text: str, cfg: Dict[str, Any]) -> List[str]:
    return [
        str(code).upper()
        for code in cfg.get("origins", [])
        if re.search(rf"\b{re.escape(str(code))}\b", text, re.IGNORECASE)
    ]


def _extract_months(text: str) -> List[str]:
    matches: List[Tuple[int, str]] = []
    for match in re.finditer(r"\b(20\d{2})[-/](0[1-9]|1[0-2])\b", text):
        matches.append((match.start(), f"{match.group(1)}-{match.group(2)}"))
    month_pattern = "|".join(sorted(MONTH_NUMBERS, key=len, reverse=True))
    for match in re.finditer(rf"\b({month_pattern})\.?\s+(20\d{{2}})\b", text, re.IGNORECASE):
        month_number = MONTH_NUMBERS[match.group(1).casefold()]
        matches.append((match.start(), f"{match.group(2)}-{month_number:02d}"))
    ordered: List[str] = []
    for _, value in sorted(matches):
        if value not in ordered:
            ordered.append(value)
    return ordered


def _extract_points(text: str) -> Optional[int]:
    match = re.search(
        r"\b(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kK])?(?:\s+[A-Za-z][A-Za-z/&.-]*){0,3}\s+(?:points|miles|avios)\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    if match.group(2):
        value *= 1000
    return int(value)


def _extract_taxes(text: str) -> Optional[float]:
    patterns = (
        r"(?:tax(?:es)?|fees?)(?:\s+and\s+fees?)?\s*(?:of|from|:)?\s*\$([\d,]+(?:\.\d{1,2})?)",
        r"\$([\d,]+(?:\.\d{1,2})?)\s+(?:in\s+)?(?:tax(?:es)?|fees?)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def _extract_cabin(normalised_text: str) -> Optional[str]:
    for phrase, cabin in (
        ("first class", "first"),
        ("business class", "business"),
        ("premium economy", "premium-economy"),
        ("economy", "economy"),
    ):
        if _contains_phrase(normalised_text, phrase):
            return cabin
    return None


def _extract_programs(normalised_text: str) -> List[str]:
    return [
        program
        for program, keywords in PROGRAM_KEYWORDS.items()
        if any(_contains_phrase(normalised_text, keyword) for keyword in keywords)
    ]


def _clean_summary(summary: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", unescape(summary or ""))
    return " ".join(without_tags.split())[:300]


def parse_award_entry(entry: Any, cfg: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    """Convert a public feed entry into a conservative, explicitly unverified award lead."""
    title = _entry_value(entry, "title")
    summary = _entry_value(entry, "summary")
    text = f"{title} {summary}"
    normalised_text = _normalise_text(text)
    points = _extract_points(text)
    has_award_language = bool(re.search(
        r"\baward\s+(?:space|availability|seat|seats|deal|sale)|\b(?:points|miles|avios)\s+(?:deal|sale)",
        normalised_text,
        re.IGNORECASE,
    ))
    has_flight_redemption_language = bool(re.search(
        r"\b(?:fly|flight|flights|book|redeem|redemption|seat|seats|one way|round trip|nonstop)\b",
        normalised_text,
        re.IGNORECASE,
    ))
    if not has_award_language and not (points is not None and has_flight_redemption_language):
        return None

    destinations, regions, destination_level = match_configured_destinations(text, cfg)
    origins = _extract_origins(text, cfg)
    travel_months = _extract_months(text)
    cabin = _extract_cabin(normalised_text)
    programs = _extract_programs(normalised_text)
    taxes = _extract_taxes(text)

    match_level = destination_level
    if destination_level == "exact-route" and not origins:
        match_level = "regional-match"

    score = 20
    reasons = ["award language or a stated flight-redemption points price"]
    if destination_level == "exact-route":
        score += 30
        reasons.append("configured destination airport")
    elif regions:
        score += 20
        reasons.append("configured destination region")
    if origins:
        score += 15
        reasons.append("configured origin airport")
    if travel_months:
        score += 15
        reasons.append("stated travel month")
    if points is not None:
        score += 10
        reasons.append("stated points price")
    if cabin:
        score += 5
        reasons.append("stated cabin")
    if programs:
        score += 5
        reasons.append("named loyalty program")
    if taxes is not None:
        score += 5
        reasons.append("stated taxes or fees")

    published = _entry_value(entry, "published")
    if not published:
        published = _entry_value(entry, "updated", "N/A")

    return {
        "title": title,
        "source": source,
        "source_url": _normalise_link(_entry_value(entry, "link")),
        "published": published,
        "summary": _clean_summary(summary),
        "origins": origins,
        "destinations": destinations,
        "matched_regions": regions,
        "travel_months": travel_months,
        "cabin": cabin,
        "programs": programs,
        "points": points,
        "taxes_usd": taxes,
        "match_level": match_level,
        "confidence_score": min(score, 100),
        "match_reasons": reasons,
        "availability_status": "reported",
        "verification_required": True,
        "matching_transfer_deals": [],
    }


def _effective_config(
    cfg: Dict[str, Any],
    origins: Optional[List[str]],
    destinations: Optional[List[str]],
    months: Optional[List[str]],
) -> Dict[str, Any]:
    effective = dict(cfg)
    if origins:
        effective["origins"] = list(dict.fromkeys(str(origin).upper() for origin in origins))
    if months:
        effective["target_months"] = list(dict.fromkeys(months))
    if destinations:
        selected: List[Dict[str, Any]] = []
        for requested in destinations:
            requested_text = str(requested).strip()
            requested_normalised = _normalise_text(requested_text)
            configured_matches = [
                destination for destination in cfg.get("destinations", [])
                if requested_text.upper() == str(destination.get("code", "")).upper()
                or requested_normalised == _normalise_text(str(destination.get("region", "")).replace("_", " "))
            ]
            if configured_matches:
                for destination in configured_matches:
                    if destination not in selected:
                        selected.append(destination)
                continue
            if re.fullmatch(r"[A-Za-z]{3}", requested_text):
                selected.append({
                    "region": requested_text.casefold(),
                    "display_name": requested_text.upper(),
                    "code": requested_text.upper(),
                })
            else:
                selected.append({
                    "region": requested_normalised.replace(" ", "_"),
                    "display_name": requested_text,
                    "code": "",
                })
        effective["destinations"] = selected
    return effective


def _feed_definition(feed: Any) -> Tuple[str, str]:
    if isinstance(feed, str):
        return feed, feed
    return str(feed.get("name") or feed.get("url") or "Award feed"), str(feed.get("url") or "")


def _sort_date(lead: Dict[str, Any]) -> datetime:
    entry = type("PublishedEntry", (), {"published": lead.get("published", "")})()
    return _parse_published_date(entry) or datetime.min.replace(tzinfo=timezone.utc)


def fetch_award_deals(
    config_path: str = "config.json",
    origins: Optional[List[str]] = None,
    destinations: Optional[List[str]] = None,
    months: Optional[List[str]] = None,
    fetch_content: Optional[Callable[[requests.Session, str], bytes]] = None,
) -> List[Dict[str, Any]]:
    """Fetch and rank public, reported award leads that overlap the requested travel scope."""
    with open(config_path, "r", encoding="utf-8") as config_file:
        cfg = _effective_config(json.load(config_file), origins, destinations, months)

    feeds = cfg.get("award_deal_feeds", [])
    target_months = set(cfg.get("target_months", []))
    max_age_days = int(cfg.get("award_deal_max_age_days", 120))
    min_score = int(cfg.get("award_deal_min_score", 35))
    include_general = bool(cfg.get("include_general_award_sales", False))
    fetch = fetch_content or _fetch_public_feed

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    leads: List[Dict[str, Any]] = []
    seen_links = set()
    seen_titles = set()

    for feed_definition in feeds:
        source, url = _feed_definition(feed_definition)
        if not url:
            print(f"Award feed error [{source}]: missing URL")
            continue
        try:
            parsed = feedparser.parse(fetch(session, url))
            if not parsed.entries:
                print(f"Award feed [{source}]: no parseable entries")
                continue

            matched_count = 0
            for entry in parsed.entries:
                title = _entry_value(entry, "title")
                if _is_title_blocklisted(title) or _is_too_old(entry, max_age_days):
                    continue
                lead = parse_award_entry(entry, cfg, source)
                if not lead:
                    continue
                if not include_general and not lead["matched_regions"]:
                    continue
                stated_months = set(lead["travel_months"])
                if target_months and stated_months and target_months.isdisjoint(stated_months):
                    continue
                if lead["confidence_score"] < min_score:
                    continue

                canonical_link = lead["source_url"]
                title_key = _normalise_text(lead["title"])
                if (canonical_link and canonical_link in seen_links) or title_key in seen_titles:
                    continue
                if canonical_link:
                    seen_links.add(canonical_link)
                seen_titles.add(title_key)
                leads.append(lead)
                matched_count += 1
            print(f"Award feed [{source}]: checked {len(parsed.entries)} entries, matched {matched_count}")
        except FeedAccessError as error:
            print(f"Award feed {error.status} [{source}]: {error}")
        except Exception as error:
            print(f"Award feed error [{source}]: {error}")

    leads.sort(key=lambda lead: (lead["confidence_score"], _sort_date(lead)), reverse=True)
    return leads


def attach_transfer_deals(
    award_deals: List[Dict[str, Any]], card_deals: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Attach only active transfer reports that name a program used by an award lead."""
    enriched: List[Dict[str, Any]] = []
    for award_deal in award_deals:
        program_names = {_normalise_text(program) for program in award_deal.get("programs", [])}
        matches = []
        for card_deal in card_deals:
            if not card_deal.get("is_transfer_bonus"):
                continue
            partner_names = {_normalise_text(partner) for partner in card_deal.get("matched_partners", [])}
            if program_names.isdisjoint(partner_names):
                continue
            matches.append({
                "title": card_deal.get("title", ""),
                "link": card_deal.get("link", ""),
            })
        item = dict(award_deal)
        item["matching_transfer_deals"] = matches
        enriched.append(item)
    return enriched
