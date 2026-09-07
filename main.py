import argparse
import asyncio
import json
import os
import sys
from typing import Optional, List

from feed_monitor import fetch_card_deals
from flight_scanner import generate_date_pairs_between, scan_flights, scan_sfo_flights
from accommodation_scanner import search_accommodations
from stay_scanner import package_flights_with_stays
from synergy_engine import analyze_synergies
from notifier import send_alert, format_terminal_deals, format_terminal_flights

async def run_scanner(
    config_path: str = "config.json",
    scan_cc: bool = True,
    scan_air: bool = True,
    origins: Optional[List[str]] = None,
    destinations: Optional[List[str]] = None,
    months: Optional[List[str]] = None,
    max_price: Optional[float] = None,
    max_stops: Optional[int] = None,
    date_pairs: Optional[List] = None,
    scan_stays: bool = False,
    max_nightly_price: Optional[float] = None,
    adults: Optional[int] = None,
    stay_location: Optional[str] = None,
    stay_details: bool = False,
    output_json: bool = False,
    output_file: Optional[str] = None
):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    webhook_url = os.getenv("WEBHOOK_URL", cfg.get("webhook_url", ""))
    deals = []
    flights = []
    accommodations = []
    flight_stay_packages = []

    # 1. Scan Credit Card & Transfer Deals
    if scan_cc:
        print("🔍 Checking RSS feeds for Chase, Amex, and Capital One offers & transfer bonuses...")
        deals = fetch_card_deals(config_path=config_path)

    # 2. Scan Google Flights
    if scan_air:
        flights = scan_flights(
            config_path=config_path,
            origins=origins,
            destinations=destinations,
            months=months,
            max_price=max_price,
            max_stops=max_stops,
            date_pairs=date_pairs
        )

    # 3. Preserve points-and-miles context in both standalone flights and packages.
    if flights:
        flights = analyze_synergies(flights, deals)

    # 4. Chain each flight's actual travel dates into the public Airbnb scanner.
    if scan_stays and flights:
        flight_stay_packages = package_flights_with_stays(
            flights,
            config_path=config_path,
            max_nightly_usd=max_nightly_price,
            adults=adults,
            stay_location=stay_location,
            include_stay_details=stay_details,
        )
    elif scan_stays:
        # Retain a useful hotel/Airbnb search-link result when no flight is found.
        accommodation_dates = date_pairs
        if not accommodation_dates:
            from flight_scanner import generate_target_date_pairs
            accommodation_dates = generate_target_date_pairs(months or cfg.get("target_months", []))
        accommodations = search_accommodations(config_path, destinations, accommodation_dates, max_nightly_price, adults)

    # 5. JSON output mode if requested
    if output_json or output_file:
        result_payload = {
            "credit_card_deals": deals,
            "flight_deals": flights,
            "accommodation_searches": accommodations,
            "flight_stay_packages": flight_stay_packages,
            "summary": {
                "total_cc_deals": len(deals),
                "total_flight_deals": len(flights),
                "total_accommodation_searches": len(accommodations),
                "total_flight_stay_packages": len(flight_stay_packages),
            }
        }
        if output_file:
            with open(output_file, "w", encoding="utf-8") as out:
                json.dump(result_payload, out, indent=2)
            print(f"📁 Results saved to {output_file}")
        if output_json:
            print(json.dumps(result_payload, indent=2))
            return

    # 5. Dispatch alerts / render formatted terminal tables
    if deals and scan_cc:
        send_alert(webhook_url, "New Card Deals & Transfer Bonuses", deals)

    if flight_stay_packages:
        send_alert(webhook_url, "SFO / SJC Flight + Accommodation Packages", flight_stay_packages)
    elif flights and scan_air:
        send_alert(webhook_url, "SFO / SJC Flight Deals Found", flights)

    if accommodations:
        for stay in accommodations:
            print(f"🏨 {stay['provider']}: {stay['destination_name']} | {stay['check_in']}–{stay['check_out']} | "
                  f"up to ${stay['max_nightly_price']:.0f}/night (${stay['max_total_price']:.0f} total) | {stay['booking_url']}")

    if not deals and not flights and not accommodations:
        print("\nNo deals found matching current filters.")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Flight, stay, and transfer-bonus deal tracker",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--deals", action="store_true", help="Scan Chase, Amex, and Capital One deals / transfer bonuses")
    parser.add_argument("--flights", action="store_true", help="Scan only flights")
    parser.add_argument("--stays", "--accommodations", dest="stays", action="store_true", help="Create Hotel and Airbnb searches for the selected dates")
    parser.add_argument("--origin", type=str, help="Comma-separated origins (e.g. SFO or SFO,SJC)")
    parser.add_argument("--dest", type=str, help="Comma-separated destinations or regions (e.g. cancun, jamaica, SJU, SJO)")
    parser.add_argument("--months", type=str, help="Comma-separated months (e.g. 2026-11,2026-12,2027-01)")
    parser.add_argument("--date-range", type=str, help="Flexible travel window START:END (e.g. 2027-03-01:2027-04-15)")
    parser.add_argument("--trip-lengths", type=str, help="Trip lengths in days for --date-range (e.g. 4,7,10)")
    parser.add_argument("--date-step-days", type=int, default=7, help="Days between generated departures for --date-range")
    parser.add_argument("--max-price", type=float, help="Max cash round-trip price in USD")
    parser.add_argument("--max-stops", type=int, default=None, help="Maximum number of layovers / stops (e.g. 0 for nonstop, 1 for max 1 stop)")
    parser.add_argument("--max-nightly-price", type=float, help="Maximum nightly accommodation budget in USD")
    parser.add_argument("--adults", type=int, help="Number of accommodation guests")
    parser.add_argument("--stay-location", type=str, help="City/location for worldwide Airbnb lookup (e.g. 'Paris, France')")
    parser.add_argument("--stay-details", action="store_true", help="Fetch amenities, photos, rules, and review data for selected Airbnb stays")
    parser.add_argument("--dates", type=str, help="Specific departure:return pair (e.g. 2026-11-13:2026-11-20)")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--output", type=str, help="File path to save JSON output")
    return parser.parse_args()

async def main():
    args = parse_args()

    # Default run follows the add-on spec: scan flights and attach stays.
    scan_cc = True
    scan_air = True
    if args.deals and not args.flights:
        scan_air = False
    elif args.flights and not args.deals:
        scan_cc = False
    scan_stays = args.stays or (not args.deals and not args.flights)
    if args.stays:
        scan_air = True

    origins = [o.strip().upper() for o in args.origin.split(",")] if args.origin else None
    destinations = [d.strip() for d in args.dest.split(",")] if args.dest else None
    months = [m.strip() for m in args.months.split(",")] if args.months else None

    date_pairs = None
    if args.dates:
        parts = args.dates.split(":")
        if len(parts) == 2:
            date_pairs = [(parts[0].strip(), parts[1].strip())]
        else:
            parser.error("--dates must use DEPARTURE:RETURN")
    elif args.date_range:
        range_parts = args.date_range.split(":")
        if len(range_parts) != 2:
            parser.error("--date-range must use START:END")
        try:
            lengths = [int(value.strip()) for value in (args.trip_lengths or "7").split(",")]
            date_pairs = generate_date_pairs_between(
                range_parts[0].strip(), range_parts[1].strip(), lengths, args.date_step_days,
            )
        except ValueError as error:
            parser.error(str(error))

    await run_scanner(
        config_path=args.config,
        scan_cc=scan_cc,
        scan_air=scan_air,
        origins=origins,
        destinations=destinations,
        months=months,
        max_price=args.max_price,
        max_stops=args.max_stops,
        date_pairs=date_pairs,
        scan_stays=scan_stays,
        max_nightly_price=args.max_nightly_price,
        adults=args.adults,
        stay_location=args.stay_location,
        stay_details=args.stay_details,
        output_json=args.json,
        output_file=args.output
    )

if __name__ == "__main__":
    asyncio.run(main())
