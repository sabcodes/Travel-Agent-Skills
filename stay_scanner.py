"""Public, login-free Airbnb stay lookup chained to flight itineraries."""

import json
import re
from datetime import datetime
from math import ceil, cos, radians
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode

import pyairbnb
import requests


# Geographic bounds are required by pyairbnb's public search endpoint.  They
# cover the airport and primary tourist area for each configured destination.
AIRBNB_AREAS: Dict[str, Dict[str, Any]] = {
    "CUN": {"name": "Cancun, Mexico", "ne": (21.31, -86.72), "sw": (21.05, -86.95), "zoom": 11},
    "MBJ": {"name": "Montego Bay, Jamaica", "ne": (18.55, -77.80), "sw": (18.42, -78.02), "zoom": 11},
    "KIN": {"name": "Kingston, Jamaica", "ne": (18.10, -76.65), "sw": (17.86, -76.95), "zoom": 11},
    "SJU": {"name": "San Juan, Puerto Rico", "ne": (18.53, -65.94), "sw": (18.34, -66.18), "zoom": 11},
    "BQN": {"name": "Aguadilla, Puerto Rico", "ne": (18.55, -67.05), "sw": (18.36, -67.28), "zoom": 11},
    "SJO": {"name": "San José, Costa Rica", "ne": (10.10, -84.00), "sw": (9.82, -84.24), "zoom": 11},
    "LIR": {"name": "Liberia, Costa Rica", "ne": (10.76, -85.32), "sw": (10.48, -85.63), "zoom": 11},
    "GIG": {"name": "Rio de Janeiro, Brazil", "ne": (-22.74, -43.12), "sw": (-23.02, -43.42), "zoom": 11},
    "LIM": {"name": "Lima, Peru", "ne": (-11.88, -76.90), "sw": (-12.22, -77.18), "zoom": 11},
    "GUA": {"name": "Monterrico, Guatemala", "ne": (14.02, -90.42), "sw": (13.80, -90.62), "zoom": 11},
    "OGG": {"name": "Maui, Hawaii", "ne": (20.98, -156.48), "sw": (20.58, -156.85), "zoom": 10},
    "BZE": {"name": "Belize City, Belize", "ne": (17.65, -88.05), "sw": (17.38, -88.35), "zoom": 10},
    "MEX": {"name": "Mexico City, Mexico", "ne": (19.60, -98.95), "sw": (19.18, -99.38), "zoom": 10},
    "UVF": {"name": "St. Lucia", "ne": (14.12, -60.85), "sw": (13.70, -61.12), "zoom": 9},
    "RTB": {"name": "Roatán & Bay Islands, Honduras", "ne": (16.48, -86.20), "sw": (16.20, -86.62), "zoom": 10},
}


def parse_date_str(date_str: str):
    """Parse a YYYY-MM-DD date and reject invalid values early."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def _number(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _room_url(room_id: Any, check_in: str, check_out: str, adults: int) -> str:
    query = urlencode({"check_in": check_in, "checkout": check_out, "adults": adults})
    return f"https://www.airbnb.com/rooms/{room_id}?{query}"


def _nightly_price(price: Dict[str, Any], nights: int) -> Optional[float]:
    """Convert Airbnb's result-card price to a nightly USD amount.

    Airbnb currently labels its primary card price as either a nightly figure or
    a trip total (for example, ``$2,289 for 7 nights``).  Only divide when the
    qualifier confirms that the amount spans the queried stay.
    """
    unit = price.get("unit", {}) if isinstance(price, dict) else {}
    amount = _number(unit.get("amount"))
    qualifier = str(unit.get("qualifier", "")).lower()
    match = re.search(r"for\s+(\d+)\s+nights?", qualifier)
    if amount is not None and match and int(match.group(1)) > 0:
        return round(amount / int(match.group(1)), 2)
    return amount


def _listing_layout(listing: Dict[str, Any]) -> Dict[str, Optional[int]]:
    """Extract bedrooms, beds, and bathrooms from Airbnb's result-card copy."""
    content = listing.get("structuredContent", {}) if isinstance(listing, dict) else {}
    lines = content.get("mapPrimaryLine", []) + content.get("primaryLine", [])
    result = {"bedrooms": None, "beds": None, "bathrooms": None}
    for line in lines:
        body = str(line.get("body", "")).lower() if isinstance(line, dict) else ""
        for field, pattern in {
            "bedrooms": r"(\d+)\s+bedrooms?",
            "beds": r"(\d+)\s+beds?",
            "bathrooms": r"(\d+(?:\.5)?)\s+baths?",
        }.items():
            match = re.search(pattern, body)
            if match:
                result[field] = float(match.group(1)) if field == "bathrooms" else int(match.group(1))
    return result


def _stay_details(room_id: Any, check_in, check_out, adults: int) -> Dict[str, Any]:
    """Fetch rich public listing data for one selected Airbnb stay."""
    try:
        data = pyairbnb.get_details(
            room_id=int(room_id), check_in=check_in, check_out=check_out,
            adults=adults, currency="USD", timeout=30,
        )
        amenities = []
        for section in data.get("amenities", []):
            for amenity in section.get("values", []):
                if amenity.get("available"):
                    amenities.append(amenity.get("title"))
        return {
            "room_type": data.get("room_type"),
            "guest_capacity": data.get("person_capacity"),
            "approximate_coordinates": data.get("coordinates"),
            "is_superhost": data.get("is_super_host"),
            "is_guest_favorite": data.get("is_guest_favorite"),
            "description": data.get("description") or None,
            "amenities": amenities,
            "house_rules": data.get("house_rules", {}).get("general", []),
            "photos": [image.get("url") for image in data.get("images", [])[:5] if image.get("url")],
            "review_scores": data.get("rating", {}),
            "recent_reviews": [
                review.get("localizedReview", {}).get("comments") or review.get("comments")
                for review in data.get("reviews", [])[:3]
                if review.get("localizedReview", {}).get("comments") or review.get("comments")
            ],
        }
    except Exception as error:
        return {"error": str(error)}


def _area_for(destination: str) -> Optional[Dict[str, Any]]:
    code = destination.upper()
    if code in AIRBNB_AREAS:
        return AIRBNB_AREAS[code]
    destination_normalized = destination.strip().lower()
    known_area = next((area for area in AIRBNB_AREAS.values() if area["name"].lower() == destination_normalized), None)
    if known_area:
        return known_area
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": destination, "format": "jsonv2", "limit": 1},
            headers={"User-Agent": "FlightStayTracker/1.0 (personal travel search)"},
            timeout=12,
        )
        response.raise_for_status()
        matches = response.json()
        if not matches:
            return None
        latitude, longitude = float(matches[0]["lat"]), float(matches[0]["lon"])
        longitude_delta = max(0.18, 0.25 / max(abs(cos(radians(latitude))), 0.1))
        return {
            "name": matches[0].get("display_name", destination),
            "ne": (latitude + 0.18, longitude + longitude_delta),
            "sw": (latitude - 0.18, longitude - longitude_delta),
            "zoom": 10,
        }
    except (requests.RequestException, KeyError, TypeError, ValueError) as error:
        print(f"[StayScanner] Could not resolve {destination}: {error}")
        return None


def scan_airbnb_stays(
    destination: str,
    check_in_str: str,
    check_out_str: str,
    max_nightly_usd: float = 150,
    adults: int = 2,
    max_results: int = 3,
    include_details: bool = False,
) -> List[Dict[str, Any]]:
    """Return up to ``max_results`` public Airbnb listings under the nightly cap.

    `pyairbnb.search_all` exposes live result cards without an Airbnb login or
    paid API key.  Public endpoint shape may change, so failures intentionally
    degrade to no listings instead of interrupting flight alerts.
    """
    check_in = parse_date_str(check_in_str)
    check_out = parse_date_str(check_out_str)
    if check_out <= check_in:
        raise ValueError("check_out must be after check_in")

    area = _area_for(destination)
    if area is None:
        print(f"[StayScanner] No Airbnb geographic bounds configured for {destination}.")
        return []

    try:
        results = pyairbnb.search_all(
            check_in=check_in.isoformat(),
            check_out=check_out.isoformat(),
            ne_lat=area["ne"][0],
            ne_long=area["ne"][1],
            sw_lat=area["sw"][0],
            sw_long=area["sw"][1],
            zoom_value=area["zoom"],
            price_min=0,
            # Airbnb applies this filter to its displayed trip price in many
            # markets, so use the complete-stay budget rather than nightly cap.
            price_max=ceil(max_nightly_usd * (check_out - check_in).days),
            adults=adults,
            currency="USD",
            timeout=30,
        )
    except Exception as error:
        print(f"[StayScanner] Error fetching Airbnb stays for {destination}: {error}")
        return []

    affordable: List[Dict[str, Any]] = []
    nights = (check_out - check_in).days
    for listing in results if isinstance(results, list) else []:
        price = listing.get("price", {}) if isinstance(listing, dict) else {}
        nightly = _nightly_price(price, nights)
        if nightly is None or nightly > max_nightly_usd:
            continue
        total = _number(price.get("total", {}).get("amount"))
        total_is_estimate = total is None or total <= 0
        room_id = listing.get("room_id", "")
        layout = _listing_layout(listing)
        coordinates = listing.get("coordinates", {})
        affordable.append({
            "provider": "Airbnb",
            "listing_id": str(room_id),
            "name": listing.get("name") or listing.get("title") or "Airbnb stay",
            "nightly_rate": nightly,
            "total_price": total if not total_is_estimate else round(nightly * nights, 2),
            "total_price_is_estimate": total_is_estimate,
            "currency": "USD",
            "rating": listing.get("rating", {}).get("value"),
            "review_count": listing.get("rating", {}).get("reviewCount"),
            "room_type": listing.get("title") or None,
            "bedrooms": layout["bedrooms"],
            "beds": layout["beds"],
            "bathrooms": layout["bathrooms"],
            "approximate_coordinates": coordinates if coordinates.get("latitude") else None,
            "url": _room_url(room_id, check_in_str, check_out_str, adults) if room_id else "",
        })

    selected = sorted(affordable, key=lambda stay: (stay["nightly_rate"], stay["total_price"]))[:max_results]
    if include_details:
        for stay in selected:
            if stay["listing_id"]:
                stay["details"] = _stay_details(stay["listing_id"], check_in, check_out, adults)
    return selected


def _flight_dates(flight: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    dates = flight.get("dates", {})
    if isinstance(dates, dict):
        check_in = dates.get("check_in") or dates.get("departure_date")
        check_out = dates.get("check_out") or dates.get("return_date")
    else:
        check_in = check_out = None
    return check_in or flight.get("departure_date"), check_out or flight.get("return_date")


def package_flights_with_stays(
    flights: Iterable[Dict[str, Any]],
    config_path: str = "config.json",
    max_nightly_usd: Optional[float] = None,
    adults: Optional[int] = None,
    stay_location: Optional[str] = None,
    include_stay_details: bool = False,
) -> List[Dict[str, Any]]:
    """Attach cached Airbnb results to every flight with usable travel dates."""
    with open(config_path, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    max_nightly = float(max_nightly_usd or config.get("max_stay_nightly_usd", 150))
    guest_count = int(adults or config.get("default_adults", 2))
    max_results = int(config.get("max_stay_results", 3))
    cached_stays: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    packages: List[Dict[str, Any]] = []

    for flight in flights:
        check_in, check_out = _flight_dates(flight)
        destination = flight.get("destination", "")
        stays: List[Dict[str, Any]] = []
        if destination and check_in and check_out:
            search_location = stay_location or config.get("stay_locations", {}).get(destination.upper(), destination)
            cache_key = (search_location.lower(), check_in, check_out)
            if cache_key not in cached_stays:
                cached_stays[cache_key] = scan_airbnb_stays(
                    destination=search_location,
                    check_in_str=check_in,
                    check_out_str=check_out,
                    max_nightly_usd=max_nightly,
                    adults=guest_count,
                    max_results=max_results,
                    include_details=include_stay_details,
                )
            stays = cached_stays[cache_key]
        packages.append({"flight": dict(flight), "stays": stays})
    return packages
