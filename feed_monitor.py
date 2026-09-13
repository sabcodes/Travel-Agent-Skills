import json
import re
import requests
import feedparser
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

try:
    # Several public publishers block the default Python requests TLS signature.
    # curl_cffi is already an optional project dependency and makes a browser-like
    # retry without requiring credentials or a headless browser.
    from curl_cffi import requests as browser_requests
except ImportError:  # pragma: no cover - normal requests remains a valid fallback
    browser_requests = None

AIRLINE_PARTNERS = {
    "united": ["United Airlines", "MileagePlus", "Star Alliance"],
    "aeroplan": ["Air Canada Aeroplan", "Star Alliance"],
    "air france": ["Air France / KLM Flying Blue", "SkyTeam"],
    "flying blue": ["Air France / KLM Flying Blue", "SkyTeam"],
    "virgin atlantic": ["Virgin Atlantic Flying Club", "SkyTeam"],
    "british airways": ["British Airways Executive Club", "Oneworld"],
    "iberia": ["Iberia Plus", "Oneworld"],
    "southwest": ["Southwest Rapid Rewards"],
    "singapore airlines": ["Singapore Airlines KrisFlyer", "Star Alliance"],
    "emirates": ["Emirates Skywards"],
    "hyatt": ["World of Hyatt"],
    "marriott": ["Marriott Bonvoy"],
    "ihg": ["IHG One Rewards"]
}

# --- Quality Filters ---

# Regex patterns for titles that are never actionable deals
TITLE_BLOCKLIST = [
    re.compile(p, re.IGNORECASE) for p in [
        r"automod\s+log",
        r"mod(?:erator)?\s+log",
        r"week(?:ly)?\s+(?:in\s+)?review",
        r"on\s+the\s+air\s+ep\d+",         # podcast episodes (e.g. "Frequent Miler on the Air Ep374")
        r"how\s+to\s+(?:make|file|submit)",  # editorial how-tos (e.g. "How to make a UK261 claim")
        r"i\s+built\s+a\s+(?:website|app|tool)",  # self-promotion posts
        r"daily\s+(?:discussion|question|thread)",  # daily discussion threads
        r"what\s+card\s+should\s+i",         # advice threads
        r"frustration\s+friday",
        r"storytime\s+(?:sunday|weekly)",
        r"(?:open|daily|weekly)\s+(?:thread|discussion|question)",
        r"(?:podcast|episode)\b",
    ]
]

# Issuer tags make transfer bonuses and card offers filterable by program.
CARD_ISSUER_KEYWORDS = {
    "Chase": ["chase", "ultimate rewards", "ur points", "sapphire", "freedom", "ink business", "ink preferred", "ink cash", "ink unlimited"],
    "American Express": ["american express", "amex", "membership rewards", "mr points", "amex offer"],
    "Capital One": ["capital one", "capital one miles", "venture x", "venture", "savor", "capital one offer"],
}
ISSUER_RELATED_KEYWORDS = {keyword for keywords in CARD_ISSUER_KEYWORDS.values() for keyword in keywords}

# Keyword weights for relevance scoring
KEYWORD_WEIGHTS = {
    "chase offer": 3,
    "amex offer": 3,
    "american express offer": 3,
    "capital one offer": 3,
    "transfer bonus": 3,
    "ultimate rewards": 3,
    "membership rewards": 3,
    "capital one miles": 3,
    "american express": 2,
    "amex": 2,
    "capital one": 2,
    "aeroplan": 2,
    "flying blue": 2,
    "virgin atlantic": 2,
    "british airways": 2,
    "iberia": 2,
    "singapore airlines": 2,
    "united": 1,
    "southwest": 1,
    "emirates": 1,
    "hyatt": 1,
    "marriott": 1,
    "ihg": 1,
    "airbnb": 1,
    "hotel offer": 2,
}

# A program name alone (for example, "United") is often editorial content.
# A qualifying item needs concrete deal language unless it is a named Chase offer.
DEAL_INTENT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in [
        r"\b(?:\d{1,3}%|up\s+to\s+\d+)\s+(?:transfer\s+)?bonus\b",
        r"\btransfer\s+(?:bonus|promotion|offer)\b",
        r"\b(?:limited[- ]time|targeted|new|increased)\s+(?:chase\s+)?offer\b",
        r"\b(?:earn|save|get)\s+(?:up\s+to\s+)?\$?\d+[\d,]*(?:\.\d+)?(?:k|m)?\b",
        r"\b(?:award|mileage|points?)\s+(?:sale|discount|promotion|deal)\b",
        r"\b(?:hotel|airbnb)\s+(?:offer|deal|credit|promotion)\b",
    ]
]

PROMOTIONAL_TERMS = ("offer", "bonus", "promotion", "sale", "deal", "discount", "credit")


def _is_title_blocklisted(title: str) -> bool:
    """Returns True if the title matches a known non-deal pattern."""
    for pattern in TITLE_BLOCKLIST:
        if pattern.search(title):
            return True
    return False


def _normalise_link(link: str) -> str:
    """Remove tracking parameters so syndications deduplicate reliably."""
    if not link:
        return ""
    parsed = urlsplit(link)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), urlencode(query), ""))


def _has_deal_intent(text: str, found_keywords: List[str]) -> bool:
    if any(keyword in found_keywords for keyword in ("chase offer", "amex offer", "american express offer", "capital one offer")):
        return True
    return any(pattern.search(text) for pattern in DEAL_INTENT_PATTERNS)


def _classify_deal(text: str) -> str:
    if detect_transfer_bonus(text):
        return "transfer_bonus"
    if "airbnb" in text or "hotel" in text or any(word in text for word in ("hyatt", "marriott", "ihg")):
        return "hotel_offer"
    return "card_offer"


def _matched_card_issuers(title: str) -> List[str]:
    """Tag issuers only when named in the headline, not related-post markup."""
    title_lower = title.lower()
    return [issuer for issuer, keywords in CARD_ISSUER_KEYWORDS.items() if any(keyword in title_lower for keyword in keywords)]


def _fetch_feed_content(session: requests.Session, url: str) -> bytes:
    """Fetch an RSS document, retrying with a browser-compatible TLS client."""
    response = session.get(url, timeout=12)
    if response.status_code == 200:
        return response.content

    if browser_requests is None:
        response.raise_for_status()

    browser_response = browser_requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"},
        impersonate="chrome",
        timeout=20,
    )
    browser_response.raise_for_status()
    return browser_response.content


def _parse_published_date(entry) -> Optional[datetime]:
    """Attempts to parse the published/updated date from a feed entry into a timezone-aware datetime."""
    if isinstance(entry, dict):
        date_str = entry.get("published") or entry.get("updated")
    else:
        date_str = getattr(entry, "published", None) or getattr(entry, "updated", None)
    if not date_str:
        return None

    # feedparser provides parsed time tuples
    if isinstance(entry, dict):
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    else:
        parsed_time = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed_time:
        try:
            # struct_time -> datetime (treat as UTC if no tz info)
            dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
            return dt
        except Exception:
            pass

    # Fallback: try ISO format parsing
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass

    return None


def _is_too_old(entry, max_age_days: int) -> bool:
    """Returns True if the post is older than max_age_days."""
    pub_date = _parse_published_date(entry)
    if pub_date is None:
        # Can't determine age — keep the post to avoid dropping valid deals
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    return pub_date < cutoff


def _compute_relevance_score(found_keywords: List[str]) -> int:
    """Computes a weighted relevance score from matched keywords."""
    score = 0
    for kw in found_keywords:
        score += KEYWORD_WEIGHTS.get(kw, 1)
    return score


def _is_card_relevant_for_reddit(url: str, title: str, summary: str) -> bool:
    """
    For Reddit r/churning posts, requires a supported card issuer keyword in
    addition to travel keywords to avoid generic discussion noise.
    """
    if "reddit.com/r/churning" not in url:
        return True  # Non-Reddit sources don't need this filter

    text = f"{title} {summary}".lower()
    return any(kw in text for keywords in CARD_ISSUER_KEYWORDS.values() for kw in keywords)


def extract_bonus_percentage(text: str) -> Optional[int]:
    """Extracts bonus percentage like 20%, 30%, 40% from text if present."""
    match = re.search(r'(\d{1,2})%\s+(?:transfer\s+)?bonus', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def detect_transfer_bonus(text: str) -> bool:
    """
    Detects whether text describes an actual Chase transfer bonus.
    Requires 'transfer' context — plain 'bonus' alone is not enough.
    """
    return bool(re.search(
        r"transfer\s+bonus|bonus\s+transfer|(\d+%?\s+)?transfer\s+to\s+|"
        r"transfer\s+partner|point\s+transfer|transfer\s+promotion",
        text, re.IGNORECASE
    ))


def fetch_card_deals(config_path: str = "config.json") -> List[Dict[str, Any]]:
    """
    Parses RSS feeds for Chase, Amex, and Capital One offers and transfer bonuses.
    Applies quality filters: title blocklist, freshness gating, relevance scoring,
    Chase-specificity for Reddit, and accurate transfer bonus detection.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    rss_feeds = cfg.get("rss_feeds", [])
    keywords = [kw.lower() for kw in cfg.get("keywords", [])]
    max_age_days = cfg.get("max_deal_age_days", 90)
    min_score = cfg.get("min_relevance_score", 2)
    matched_deals = []
    seen_links = set()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for url in rss_feeds:
        try:
            feed = feedparser.parse(_fetch_feed_content(session, url))
            if not feed.entries:
                print(f"No current entries in RSS feed: {url}")
                continue
            for entry in feed.entries:
                link = _normalise_link(getattr(entry, "link", ""))
                if link in seen_links:
                    continue

                title = getattr(entry, "title", "")
                summary = unescape(getattr(entry, "summary", ""))
                text = f"{title} {summary}".lower()

                # --- Quality Filter 1: Title Blocklist ---
                if _is_title_blocklisted(title):
                    continue

                # --- Quality Filter 2: Freshness Gate ---
                if _is_too_old(entry, max_age_days):
                    continue

                # --- Keyword matching ---
                title_lower = title.lower()
                found_kw = [
                    keyword for keyword in keywords
                    if keyword in text and (keyword not in ISSUER_RELATED_KEYWORDS or keyword in title_lower)
                ]
                if not found_kw:
                    continue

                # A keyword match alone produces far too much commentary noise.
                has_deal_intent = _has_deal_intent(text, found_kw)
                if not has_deal_intent:
                    continue

                # --- Quality Filter 3: Relevance Scoring ---
                # Confirmed offer language is independent evidence of relevance.
                # This lets a genuine single-program offer (for example, a
                # Marriott promotion) pass without letting brand-only chatter in.
                relevance_score = _compute_relevance_score(found_kw) + (1 if has_deal_intent else 0)
                if relevance_score < min_score:
                    continue

                # --- Quality Filter 4: Chase-specificity for Reddit ---
                if not _is_card_relevant_for_reddit(url, title, summary):
                    continue

                seen_links.add(link)

                # --- Quality Filter 5: Accurate transfer bonus detection ---
                is_transfer_bonus = detect_transfer_bonus(text)
                bonus_pct = extract_bonus_percentage(text)

                # Detect partner matching
                matched_partners = set()
                for partner_kw, partner_names in AIRLINE_PARTNERS.items():
                    if partner_kw in text:
                        matched_partners.add(partner_names[0])

                # Clean summary of HTML tags
                clean_summary = re.sub(r'<[^>]+>', ' ', summary)
                clean_summary = ' '.join(clean_summary.split())[:200]

                matched_deals.append({
                    "title": title,
                    "link": link,
                    "matched_keywords": found_kw,
                    "card_issuers": _matched_card_issuers(title),
                    "relevance_score": relevance_score,
                    "is_transfer_bonus": is_transfer_bonus,
                    "deal_type": _classify_deal(text),
                    "bonus_percentage": bonus_pct,
                    "matched_partners": list(matched_partners),
                    "published": getattr(entry, "published", getattr(entry, "updated", "N/A")),
                    "summary": clean_summary
                })
        except Exception as e:
            print(f"Error fetching feed {url}: {e}")

    # Surface time-sensitive deals first, while retaining relevance as a tiebreaker.
    matched_deals.sort(
        key=lambda deal: (_parse_published_date(type("Entry", (), {"published": deal.get("published", "")})()) or datetime.min.replace(tzinfo=timezone.utc), deal.get("relevance_score", 0)),
        reverse=True,
    )

    return matched_deals


# Original public entry point retained for callers that have not migrated.
fetch_chase_deals = fetch_card_deals

if __name__ == "__main__":
    deals = fetch_card_deals()
    print(f"Total deals/offers found: {len(deals)}")
    for d in deals[:10]:
        print(f"\n- Title: {d['title']}")
        print(f"  Link: {d['link']}")
        print(f"  Keywords: {d['matched_keywords']}  (score: {d['relevance_score']})")
        if d['matched_partners']:
            print(f"  Partners: {d['matched_partners']}")
        if d['bonus_percentage']:
            print(f"  Bonus: {d['bonus_percentage']}%")
        if d['is_transfer_bonus']:
            print(f"  ⭐ Transfer Bonus Detected")
