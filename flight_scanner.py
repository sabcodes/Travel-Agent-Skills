import asyncio
import json
import time
import urllib.parse
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

try:
    from fast_flights import FlightQuery, create_filter, fetch_flights_html, get_flights
    from fast_flights.parser import parse_js
    from selectolax.lexbor import LexborHTMLParser
    # Alias FlightData to FlightQuery for spec compatibility
    FlightData = FlightQuery
except ImportError:
    FlightQuery = None
    create_filter = None
    fetch_flights_html = None
    get_flights = None
    parse_js = None
    LexborHTMLParser = None
    FlightData = None

# Region and Airport mappings
REGION_MAP = {
    "cancun": ["CUN"],
    "jamaica": ["MBJ", "KIN"],
    "puerto_rico": ["SJU", "BQN"],
    "costa_rica": ["SJO", "LIR"],
    "brazil": ["GIG"],
    "peru": ["LIM"],
    "guatemala": ["GUA"],
    "maui": ["OGG"],
    "belize": ["BZE"],
    "mexico_city": ["MEX"],
    "saint_lucia": ["UVF"],
    "roatan_bay_islands": ["RTB"],
}

AIRPORT_NAMES = {
    "SFO": "San Francisco (SFO)",
    "SJC": "San Jose (SJC)",
    "CUN": "Cancun, Mexico (CUN)",
    "MBJ": "Montego Bay, Jamaica (MBJ)",
    "KIN": "Kingston, Jamaica (KIN)",
    "SJU": "San Juan, Puerto Rico (SJU)",
    "BQN": "Aguadilla, Puerto Rico (BQN)",
    "SJO": "San José, Costa Rica (SJO)",
    "LIR": "Liberia, Costa Rica (LIR)",
    "GIG": "Rio de Janeiro, Brazil (GIG)",
    "LIM": "Lima, Peru (LIM)",
    "GUA": "Guatemala City / Pacific Coast, Guatemala (GUA)",
    "OGG": "Maui, Hawaii (OGG)",
    "BZE": "Belize City, Belize (BZE)",
    "MEX": "Mexico City, Mexico (MEX)",
    "UVF": "St. Lucia / Hewanorra (UVF)",
    "RTB": "Roatán & Bay Islands, Honduras (RTB)",
}

FLIGHT_LOOKUP_ATTEMPTS = 2
FLIGHT_LOOKUP_RETRY_DELAY_SECONDS = 1.0


class FlightLookupError(RuntimeError):
    """Raised when Google Flights cannot be reached for a requested route."""


def _duration_minutes(value: Any) -> float:
    """Convert values such as ``22h 15m`` into minutes for stable ranking."""
    if not isinstance(value, str):
        return float("inf")
    hours = 0
    minutes = 0
    for part in value.lower().split():
        try:
            if part.endswith("h"):
                hours = int(part[:-1])
            elif part.endswith("m"):
                minutes = int(part[:-1])
        except ValueError:
            return float("inf")
    return (hours * 60) + minutes


def _fare_sort_key(deal: Dict[str, Any]) -> Tuple[Any, ...]:
    """Rank fares by price, then convenience, then stable text fields."""
    return (
        float(deal.get("price", float("inf"))),
        int(deal.get("stops", 999)),
        _duration_minutes(deal.get("total_journey_duration")),
        str(deal.get("airline", "")),
        str(deal.get("origin", "")),
        str(deal.get("destination", "")),
        str(deal.get("departure_date", "")),
        str(deal.get("return_date", "")),
        str(deal.get("layover_summary", "")),
    )


def _drop_unpriced_flight_groups(payload: List[Any]) -> int:
    """Remove Google result groups that do not contain a numeric fare."""
    groups = payload[3][0]
    if not isinstance(groups, list):
        return 0

    priced_groups = []
    for group in groups:
        try:
            price = group[1][0][1]
        except (IndexError, TypeError):
            continue
        if isinstance(price, (int, float)):
            priced_groups.append(group)

    removed = len(groups) - len(priced_groups)
    payload[3][0] = priced_groups
    return removed


def _get_flights_resilient(query):
    """Fetch with fast-flights while tolerating Google's unpriced result rows."""
    try:
        return get_flights(query)
    except (IndexError, TypeError) as original_error:
        html = fetch_flights_html(query)
        script = LexborHTMLParser(html).css_first(r"script.ds\:1")
        if script is None:
            raise original_error

        js = script.text()
        data = js.split("data:", 1)[1].rsplit(",", 1)[0]
        payload = json.loads(data)
        if isinstance(payload, list) and len(payload) > 3 and payload[3] is None:
            return []
        if _drop_unpriced_flight_groups(payload) == 0:
            raise original_error

        return parse_js(f"data:{json.dumps(payload, separators=(',', ':'))},")


def generate_target_date_pairs(
    months: List[str] = ["2026-11", "2026-12", "2027-01"],
    trip_days: int = 7,
    trip_durations_days: Optional[List[int]] = None,
) -> List[Tuple[str, str]]:
    """
    Generates representative 6-8 day round-trip windows for each target month.
    Covers early month, mid month, and late month (including holiday windows).
    """
    date_pairs = []
    durations = sorted({int(duration) for duration in (trip_durations_days or [trip_days])})
    if not durations or any(duration < 1 for duration in durations):
        raise ValueError("trip durations must contain one or more positive whole days")

    # Specific curated target travel windows across Nov, Dec, Jan
    curated_departures = [
        # November: Early, Mid, Thanksgiving
        "2026-11-06",
        "2026-11-13",
        "2026-11-20",
        # December: Early, Mid, Holiday / Christmas
        "2026-12-04",
        "2026-12-11",
        "2026-12-23",
        # January: Early, Mid, Late
        "2027-01-08",
        "2027-01-15",
        "2027-01-22"
    ]

    for dep_str in curated_departures:
        dep_date = datetime.strptime(dep_str, "%Y-%m-%d")
        month_key = dep_date.strftime("%Y-%m")
        if month_key in months:
            for duration in durations:
                ret_date = dep_date + timedelta(days=duration)
                date_pairs.append((dep_str, ret_date.strftime("%Y-%m-%d")))

    return date_pairs


def generate_date_pairs_between(
    start_date: str,
    end_date: str,
    trip_durations_days: List[int],
    step_days: int = 7,
) -> List[Tuple[str, str]]:
    """Generate round-trip windows wholly contained in any travel date range."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end <= start:
        raise ValueError("date-range end must be after its start")
    if step_days < 1:
        raise ValueError("date-step-days must be at least 1")
    durations = sorted({int(duration) for duration in trip_durations_days})
    if not durations or any(duration < 1 for duration in durations):
        raise ValueError("trip lengths must contain one or more positive whole days")

    pairs = []
    departure = start
    while departure < end:
        for duration in durations:
            check_out = departure + timedelta(days=duration)
            if check_out <= end:
                pairs.append((departure.isoformat(), check_out.isoformat()))
        departure += timedelta(days=step_days)
    if not pairs:
        raise ValueError("date range is too short for the requested trip length")
    return pairs

def build_google_flights_url(origin: str, destination: str, dep_date: str, ret_date: Optional[str] = None) -> str:
    """Creates a direct Google Flights search URL for convenient booking."""
    if ret_date:
        query = f"Flights to {destination} from {origin} on {dep_date} through {ret_date}"
    else:
        query = f"Flights to {destination} from {origin} on {dep_date}"
    return f"https://www.google.com/travel/flights?q={urllib.parse.quote(query)}"

def to_datetime(s_dt):
    if not s_dt or not hasattr(s_dt, "date") or not hasattr(s_dt, "time"):
        return None
    try:
        return datetime(s_dt.date[0], s_dt.date[1], s_dt.date[2], s_dt.time[0], s_dt.time[1])
    except Exception:
        return None

def format_duration_minutes(m: float) -> str:
    if m is None or m < 0:
        return "N/A"
    h = int(m // 60)
    mins = int(m % 60)
    return f"{h}h {mins}m" if h > 0 else f"{mins}m"

def scan_route(
    origin: str,
    destination: str,
    dep_date: str,
    ret_date: Optional[str] = None,
    max_price: float = 650.0,
    max_stops: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Scrapes Google Flights for a specific route and dates using fast-flights.
    Returns flight deals at or below max_price.
    """
    deals = []
    if not get_flights or not fetch_flights_html or not create_filter:
        print("fast-flights is not installed.")
        return deals

    try:
        flights_query = [
            FlightQuery(date=dep_date, from_airport=origin, to_airport=destination)
        ]
        trip_type = "one-way"
        if ret_date:
            flights_query.append(
                FlightQuery(date=ret_date, from_airport=destination, to_airport=origin)
            )
            trip_type = "round-trip"

        last_error = None
        for attempt in range(1, FLIGHT_LOOKUP_ATTEMPTS + 1):
            try:
                q = create_filter(
                    flights=flights_query,
                    trip=trip_type,
                    currency="USD",
                    max_stops=max_stops,
                )
                results = _get_flights_resilient(q)
                break
            except Exception as error:
                last_error = error
                if attempt < FLIGHT_LOOKUP_ATTEMPTS:
                    time.sleep(FLIGHT_LOOKUP_RETRY_DELAY_SECONDS)
        else:
            # A failed request is materially different from a valid search with no fares.
            # Surface it so callers do not mistake connectivity or provider failures for
            # an empty set of flight deals.
            raise FlightLookupError(
                f"Google Flights lookup failed for {origin} → {destination} "
                f"({dep_date} to {ret_date}) after {FLIGHT_LOOKUP_ATTEMPTS} attempts: {last_error}"
            ) from last_error

        if not results:
            return deals

        for item in results:
            price = getattr(item, "price", None)
            if price is None:
                continue

            try:
                price_num = float(price)
            except (ValueError, TypeError):
                continue

            if price_num <= max_price:
                airlines = getattr(item, "airlines", ["Unknown"])
                airline_str = ", ".join(airlines) if isinstance(airlines, list) else str(airlines)

                # Extract stops, layovers, and durations
                subflights = getattr(item, "flights", [])
                stops = max(0, len(subflights) - 1) if subflights else 0

                if max_stops is not None and stops > max_stops:
                    continue

                in_air_min = sum(leg.duration for leg in subflights if getattr(leg, "duration", None))
                in_air_str = format_duration_minutes(in_air_min)

                layovers = []
                for i in range(len(subflights) - 1):
                    arr_dt = to_datetime(getattr(subflights[i], "arrival", None))
                    dep_next_dt = to_datetime(getattr(subflights[i + 1], "departure", None))
                    if arr_dt and dep_next_dt:
                        diff_min = (dep_next_dt - arr_dt).total_seconds() / 60.0
                        ap_code = getattr(subflights[i].to_airport, "code", "Layover")
                        layovers.append({
                            "airport": ap_code,
                            "duration_min": diff_min,
                            "duration_str": format_duration_minutes(diff_min),
                            "formatted": f"{ap_code} ({format_duration_minutes(diff_min)})"
                        })

                leg_details = []
                for leg in subflights:
                    dep_time_str = f"{leg.departure.time[0]:02d}:{leg.departure.time[1]:02d}" if hasattr(leg, "departure") and hasattr(leg.departure, "time") else ""
                    arr_time_str = f"{leg.arrival.time[0]:02d}:{leg.arrival.time[1]:02d}" if hasattr(leg, "arrival") and hasattr(leg.arrival, "time") else ""
                    leg_details.append({
                        "from": getattr(leg.from_airport, "code", ""),
                        "to": getattr(leg.to_airport, "code", ""),
                        "duration": format_duration_minutes(getattr(leg, "duration", 0)),
                        "dep_time": dep_time_str,
                        "arr_time": arr_time_str,
                        "plane": getattr(leg, "plane_type", "")
                    })

                # Provider timestamps are local airport times without timezone
                # offsets.  Summing flight time and same-airport layovers avoids
                # incorrect elapsed durations on routes that cross time zones.
                total_journey_min = in_air_min + sum(max(0, layover["duration_min"]) for layover in layovers)
                total_journey_str = format_duration_minutes(total_journey_min) if subflights else "N/A"

                deals.append({
                    "origin": origin,
                    "destination": destination,
                    "destination_name": AIRPORT_NAMES.get(destination, destination),
                    "price": price_num,
                    "airline": airline_str,
                    "departure_date": dep_date,
                    "return_date": ret_date,
                    "is_round_trip": bool(ret_date),
                    "stops": stops,
                    "layovers_count": len(layovers),
                    "layovers": layovers,
                    "layover_summary": ", ".join(l["formatted"] for l in layovers) if layovers else "Nonstop",
                    "flight_duration_air": in_air_str,
                    "total_journey_duration": total_journey_str,
                    "legs": leg_details,
                    "booking_url": build_google_flights_url(origin, destination, dep_date, ret_date)
                })

    except FlightLookupError:
        raise
    except Exception as e:
        print(f"Error scanning {origin} -> {destination} ({dep_date} to {ret_date}): {e}")

    return deals

def scan_flights(
    config_path: str = "config.json",
    origins: Optional[List[str]] = None,
    destinations: Optional[List[str]] = None,
    months: Optional[List[str]] = None,
    max_price: Optional[float] = None,
    max_stops: Optional[int] = None,
    date_pairs: Optional[List[Tuple[str, str]]] = None,
    trip_durations_days: Optional[List[int]] = None,
    delay_between_requests: float = 1.0,
    source_errors: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Main entrypoint to sweep Google Flights for deals across origins and destinations.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    active_origins = origins or cfg.get("origins", ["SFO", "SJC"])

    # Resolve destinations
    if destinations:
        resolved_dests = []
        for d in destinations:
            d_lower = d.lower().replace(" ", "_")
            if d_lower in REGION_MAP:
                resolved_dests.extend(REGION_MAP[d_lower])
            else:
                resolved_dests.append(d.upper())
    else:
        # Load from config destinations
        dest_entries = cfg.get("destinations", [])
        resolved_dests = [entry["code"] if isinstance(entry, dict) else entry for entry in dest_entries]

    target_months = months or cfg.get("target_months", ["2026-11", "2026-12", "2027-01"])
    global_max_price = max_price if max_price is not None else cfg.get("default_max_cash_price_usd", 550)

    # Destination-specific price limits from config if available
    dest_limits = {}
    for entry in cfg.get("destinations", []):
        if isinstance(entry, dict):
            dest_limits[entry["code"]] = entry.get("max_price", global_max_price)

    # Generate dates to scan
    pairs = date_pairs or generate_target_date_pairs(
        target_months,
        trip_durations_days=trip_durations_days or cfg.get("default_trip_durations_days", [7]),
    )

    print(f"✈️ Starting flight scan...")
    print(f"  Origins: {active_origins}")
    print(f"  Destinations: {resolved_dests}")
    print(f"  Date pairs to check: {len(pairs)} windows across {target_months}")
    print(f"  Max price filter: ${global_max_price}\n")

    all_deals = []
    lookup_errors = []
    successful_lookups = 0
    for origin in active_origins:
        for dest in resolved_dests:
            dest_price_limit = max_price if max_price is not None else dest_limits.get(dest, global_max_price)
            for dep_date, ret_date in pairs:
                try:
                    deals = scan_route(
                        origin=origin,
                        destination=dest,
                        dep_date=dep_date,
                        ret_date=ret_date,
                        max_price=dest_price_limit,
                        max_stops=max_stops
                    )
                    successful_lookups += 1
                except FlightLookupError as error:
                    lookup_errors.append(str(error))
                    if source_errors is not None:
                        source_errors.append({
                            "component": "cash_flights",
                            "status": "unavailable",
                            "origin": origin,
                            "destination": dest,
                            "departure_date": dep_date,
                            "return_date": ret_date,
                            "message": str(error),
                        })
                    print(f"⚠️ {error}")
                    continue
                if deals:
                    # Sort deals by price and keep cheapest 2 per date window
                    deals = sorted(deals, key=_fare_sort_key)
                    all_deals.extend(deals[:2])

                time.sleep(delay_between_requests)

    if successful_lookups == 0 and lookup_errors:
        raise FlightLookupError(
            "Every Google Flights lookup failed. The first provider error was: "
            f"{lookup_errors[0]}"
        )
    if lookup_errors:
        print(f"⚠️ Skipped {len(lookup_errors)} lookup(s) after provider errors.")

    # Deduplicate and sort by price
    unique_deals = []
    seen = set()
    for d in sorted(all_deals, key=_fare_sort_key):
        key = (d["origin"], d["destination"], d["departure_date"], d["return_date"], d["price"], d["airline"])
        if key not in seen:
            seen.add(key)
            unique_deals.append(d)

    return unique_deals

# Async wrapper for callers that prefer the configured origin list.
async def scan_configured_flights(config_path: str = "config.json") -> List[Dict[str, Any]]:
    """Scan flights from every origin configured in the selected config file."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, scan_flights, config_path)


# Backward-compatible name from the original SFO-only implementation.
scan_sfo_flights = scan_configured_flights

if __name__ == "__main__":
    # Test sample run for SFO/SJC -> Cancun and Puerto Rico for November
    sample_pairs = [("2026-11-13", "2026-11-20")]
    results = scan_flights(
        origins=["SFO", "SJC"],
        destinations=["CUN", "SJU"],
        date_pairs=sample_pairs,
        max_price=550
    )
    print(f"\nScan complete! Found {len(results)} deals:")
    for r in results:
        print(f"- {r['origin']} -> {r['destination']} ({r['destination_name']}): ${r['price']} on {r['airline']} ({r['departure_date']} to {r['return_date']})")
        print(f"  Booking link: {r['booking_url']}")
