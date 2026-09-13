"""Login-free accommodation search links for the tracker.

This module deliberately does not scrape inventory from travel sites.  Rates and
availability change rapidly and most providers require a browser session.  It
creates date, guest, and budget-aware searches that can be opened directly in
Google Hotels or Airbnb, alongside a clear nightly budget ceiling.
"""

import json
import urllib.parse
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


DESTINATION_NAMES = {
    "CUN": "Cancun, Mexico",
    "MBJ": "Montego Bay, Jamaica",
    "KIN": "Kingston, Jamaica",
    "SJU": "San Juan, Puerto Rico",
    "BQN": "Aguadilla, Puerto Rico",
    "SJO": "San José, Costa Rica",
    "LIR": "Liberia, Costa Rica",
    "BZE": "Belize City, Belize",
    "MEX": "Mexico City, Mexico",
    "UVF": "St. Lucia (Hewanorra)",
    "RTB": "Roatán & Bay Islands, Honduras",
}


def _google_hotels_url(destination: str, check_in: str, check_out: str, adults: int) -> str:
    query = f"hotels in {destination} from {check_in} to {check_out} for {adults} adults"
    return "https://www.google.com/travel/search?" + urllib.parse.urlencode({"q": query})


def _airbnb_url(destination: str, check_in: str, check_out: str, adults: int) -> str:
    return "https://www.airbnb.com/s/" + urllib.parse.quote(destination) + "/homes?" + urllib.parse.urlencode({
        "tab_id": "home_tab",
        "refinement_paths[]": "/homes",
        "date_picker_type": "calendar",
        "checkin": check_in,
        "checkout": check_out,
        "adults": adults,
    })


def _resolve_destinations(cfg: Dict[str, Any], destinations: Optional[List[str]]) -> List[Tuple[str, str]]:
    configured = {
        str(item["code"]).upper(): item.get("display_name") or DESTINATION_NAMES.get(str(item["code"]).upper(), str(item["code"]).upper())
        for item in cfg.get("destinations", []) if isinstance(item, dict) and item.get("code")
    }
    if not destinations:
        return list(configured.items())

    region_codes = {}
    for item in cfg.get("destinations", []):
        if isinstance(item, dict) and item.get("region") and item.get("code"):
            region_codes.setdefault(item["region"].lower(), []).append(str(item["code"]).upper())

    resolved = []
    seen = set()
    for value in destinations:
        key = value.lower().replace(" ", "_")
        codes = region_codes.get(key, [value.upper()])
        for code in codes:
            if code not in seen:
                seen.add(code)
                resolved.append((code, configured.get(code, DESTINATION_NAMES.get(code, code))))
    return resolved


def search_accommodations(
    config_path: str = "config.json",
    destinations: Optional[List[str]] = None,
    date_pairs: Optional[List[Tuple[str, str]]] = None,
    max_nightly_price: Optional[float] = None,
    adults: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return date-specific Hotel and Airbnb search results for each destination."""
    with open(config_path, "r", encoding="utf-8") as config_file:
        cfg = json.load(config_file)

    nightly_budget = float(max_nightly_price or cfg.get("max_stay_nightly_usd", 250))
    guest_count = int(adults or cfg.get("default_adults", 2))
    pairs = date_pairs or []
    if not pairs:
        raise ValueError("Accommodation searches require a check-in and check-out date.")

    results = []
    for code, destination_name in _resolve_destinations(cfg, destinations):
        for check_in, check_out in pairs:
            nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
            if nights <= 0:
                raise ValueError("Check-out must be after check-in.")
            common = {
                "destination": code,
                "destination_name": destination_name,
                "check_in": check_in,
                "check_out": check_out,
                "nights": nights,
                "adults": guest_count,
                "max_nightly_price": nightly_budget,
                "max_total_price": round(nightly_budget * nights, 2),
            }
            results.extend([
                {
                    **common,
                    "provider": "Google Hotels",
                    "accommodation_type": "hotel",
                    "inventory_status": "search_link_only",
                    "rate_status": "Search handoff only; no hotel prices or availability were retrieved.",
                    "booking_url": _google_hotels_url(destination_name, check_in, check_out, guest_count),
                },
                {
                    **common,
                    "provider": "Airbnb",
                    "accommodation_type": "airbnb",
                    "inventory_status": "search_link_only",
                    "rate_status": "Search handoff only; verify live availability, fees, and taxes with Airbnb.",
                    "booking_url": _airbnb_url(destination_name, check_in, check_out, guest_count),
                },
            ])
    return results
