import json
import requests
from typing import List, Dict, Any, Optional
from urllib.parse import parse_qs, urlsplit, urlunsplit
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def _notification_request(webhook_url: str, message: str):
    """Return the provider-specific endpoint and JSON payload for a message."""
    parsed = urlsplit(webhook_url)
    host = (parsed.hostname or "").lower()
    if host.endswith("slack.com"):
        return webhook_url, {"text": message}
    if host == "api.telegram.org":
        chat_id = parse_qs(parsed.query).get("chat_id", [None])[0]
        if not chat_id:
            raise ValueError("Telegram webhook URLs must include ?chat_id=YOUR_CHAT_ID")
        endpoint = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        return endpoint, {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    return webhook_url, {"content": message}


def _post_message(webhook_url: str, message: str):
    endpoint, payload = _notification_request(webhook_url, message)
    requests.post(endpoint, json=payload, timeout=10)

def format_terminal_deals(deals: List[Dict[str, Any]]):
    """Prints credit card and transfer bonus deals in a formatted table."""
    if not deals:
        console.print("[dim]No active credit card deals or transfer bonuses found.[/dim]")
        return

    table = Table(title="💳 Active Card & Points Deals / Transfer Bonuses", header_style="bold cyan")
    table.add_column("Type", style="bold green", width=16)
    table.add_column("Title", style="white", width=45)
    table.add_column("Partner / Keyword", style="yellow", width=22)
    table.add_column("Link", style="blue underline", overflow="fold")

    for d in deals:
        deal_type = "Transfer Bonus" if d.get("is_transfer_bonus") else "Card Offer"
        partners = ", ".join(d.get("card_issuers", [])) or ", ".join(d.get("matched_partners", [])) or ", ".join(d.get("matched_keywords", []))
        table.add_row(
            deal_type,
            d.get("title", "")[:45],
            partners[:22],
            d.get("link", "")
        )
    console.print(table)


def format_terminal_award_deals(deals: List[Dict[str, Any]]):
    """Print public award reports without implying that inventory is still live."""
    if not deals:
        console.print("[dim]No matching reported award leads. This does not mean no award seats exist.[/dim]")
        return

    table = Table(title="🎟️ Reported Award Leads — Verify live availability", header_style="bold cyan")
    table.add_column("Reported lead", style="white", width=32)
    table.add_column("Award", style="yellow", width=12, min_width=10, no_wrap=True)
    table.add_column("When / Source / Verify", style="cyan", width=24, overflow="fold")

    for deal in deals:
        origins = ",".join(deal.get("origins", []))
        destinations = ",".join(deal.get("destinations", []))
        regions = ", ".join(region.replace("_", " ").title() for region in deal.get("matched_regions", []))
        route = f"{origins} ➔ {destinations}" if origins and destinations else regions or destinations or "General sale"
        points = f"{deal['points']:,}" if deal.get("points") is not None else "Not stated"
        months = ", ".join(deal.get("travel_months", [])) or "Dates not stated"
        cabin = deal.get("cabin") or "cabin not stated"
        table.add_row(
            f"{deal.get('title', 'Award opportunity')}\n[green]{route} · {deal.get('match_level', 'general-sale')} · score {deal.get('confidence_score', 0)}[/green]",
            f"{points}\n{cabin}",
            f"{months}\n{deal.get('source', 'Unknown')}\n{deal.get('source_url', '')}",
        )
    console.print(table)
    console.print("[bold yellow]Reported award lead — verify live availability with the loyalty program before transferring points.[/bold yellow]")

def format_terminal_flights(flights: List[Dict[str, Any]]):
    """Prints flight deals in a clean formatted table."""
    if not flights:
        console.print("[dim]No flight deals matching the criteria found.[/dim]")
        return

    table = Table(title="✈️ Cheap Flight Deals", header_style="bold magenta")
    table.add_column("Route", style="bold cyan", width=11)
    table.add_column("Destination", style="white", width=20)
    table.add_column("Price", style="bold green", justify="right", width=7)
    table.add_column("Airline", style="yellow", width=16)
    table.add_column("Dates", style="cyan", width=23)
    table.add_column("Duration (Total / Air)", style="magenta", width=22)
    table.add_column("Layovers", style="white", width=26)
    table.add_column("Chase UR Synergy", style="bold blue", width=24)

    for f in flights:
        route = f"{f.get('origin', '')} ➔ {f.get('destination', '')}"
        dates = f.get("dates") or f"{f.get('departure_date', '')} to {f.get('return_date', '')}"
        dest_name = f.get("destination_name", f.get("destination", ""))

        # Durations
        total_dur = f.get("total_journey_duration", "N/A")
        air_dur = f.get("flight_duration_air", "N/A")
        dur_str = f"{total_dur} (Air: {air_dur})"

        # Layovers
        layover_summary = f.get("layover_summary", "Nonstop")

        # Synergy text
        synergy_text = "-"
        if f.get("chase_partner_info"):
            partners = f["chase_partner_info"]["partners"]
            synergy_text = f"💡 {partners[0]}"
            if f.get("has_transfer_bonus"):
                synergy_text += " [bold yellow](BONUS!)[/bold yellow]"

        table.add_row(
            route,
            dest_name[:20],
            f"${f.get('price', 0):.0f}",
            f.get("airline", "Unknown")[:16],
            dates,
            dur_str,
            layover_summary[:26],
            synergy_text
        )
    console.print(table)

def format_terminal_packages(packages: List[Dict[str, Any]]):
    """Print combined flight and Airbnb results without losing individual stay prices."""
    table = Table(title="✈️ + 🏠 Flight & Accommodation Packages", header_style="bold magenta")
    table.add_column("Flight", style="bold cyan", width=26)
    table.add_column("Airbnb stays under budget", style="white", width=65)
    for package in packages:
        flight = package.get("flight", {})
        flight_text = f"{flight.get('origin', '')} ➔ {flight.get('destination', '')} | ${flight.get('price', 0):.0f}\n{flight.get('departure_date', '')} to {flight.get('return_date', '')}"
        stays = package.get("stays", [])
        stay_rows = []
        for stay in stays:
            layout = " · ".join(str(value) + label for value, label in ((stay.get("bedrooms"), " bd"), (stay.get("beds"), " beds"), (stay.get("bathrooms"), " ba")) if value is not None)
            stay_rows.append(f"{stay.get('name', 'Airbnb stay')} - ${stay.get('nightly_rate', 0):.0f}/night (${stay.get('total_price', 0):.0f}{' est.' if stay.get('total_price_is_estimate') else ''} total){' | ' + layout if layout else ''}")
        stay_text = "\n".join(stay_rows) or "No public Airbnb stays under the configured nightly cap."
        table.add_row(flight_text, stay_text)
    console.print(table)

def send_alert(webhook_url: str, title: str, details: List[Dict[str, Any]]):
    """
    Formats and dispatches alerts to external webhooks (e.g. Discord).
    Falls back gracefully to console output if webhook_url is not set.
    """
    if not details:
        return

    is_package_alert = bool(details and "flight" in details[0])
    is_award_alert = bool(details and details[0].get("availability_status") == "reported")

    # If no valid webhook URL is provided, display in terminal
    if not webhook_url or webhook_url.strip() in ("", "YOUR_WEBHOOK_URL_HERE"):
        if is_package_alert:
            format_terminal_packages(details)
        elif is_award_alert:
            format_terminal_award_deals(details)
        elif any("price" in item for item in details):
            format_terminal_flights(details)
        else:
            format_terminal_deals(details)
        return

    # Webhook delivery (Discord / Slack format)
    header = f"✈️ **{title}**\n\n"
    lines = []
    for item in details:
        if "flight" in item:
            flight = item["flight"]
            line = f"• **{flight.get('origin', '')} ➔ {flight.get('destination', '')}**: ${flight.get('price', 0):.0f} ({flight.get('airline', 'Airline')}) - {flight.get('departure_date', '')} to {flight.get('return_date', '')}"
            stays = item.get("stays", [])
            if stays:
                line += " | 🏠 " + "; ".join(f"{stay.get('name', 'Airbnb stay')} ${stay.get('nightly_rate', 0):.0f}/night" for stay in stays)
            lines.append(line)
        elif "price" in item:
            origin = item.get("origin", "Origin")
            dest = item.get("destination", "")
            price = item.get("price", 0)
            airline = item.get("airline", "Airline")
            dates = item.get("dates") or f"{item.get('departure_date', '')} to {item.get('return_date', '')}"
            link = item.get("booking_url", "")

            tot_dur = item.get("total_journey_duration", "")
            lay_sum = item.get("layover_summary", "")
            dur_info = f" | ⏱️ {tot_dur} ({lay_sum})" if tot_dur else ""
            line = f"• **{origin} ➔ {dest}**: ${price:.0f} ({airline}) - {dates}{dur_info}"
            if link:
                line += f" [Book]({link})"
            if item.get("has_transfer_bonus"):
                line += " 🌟 *Active Chase Transfer Bonus Available!*"
            lines.append(line)
        elif item.get("availability_status") == "reported":
            source_url = item.get("source_url", "")
            title_text = item.get("title", "Reported award opportunity")
            linked_title = f"[{title_text}]({source_url})" if source_url else title_text
            line = f"• **Reported award lead — verify live availability:** {linked_title}"
            if item.get("points") is not None:
                line += f" | {item['points']:,} points/miles"
            if item.get("matching_transfer_deals"):
                line += " | matching transfer bonus reported"
            lines.append(line)
        else:
            lines.append(f"• [{item['title']}]({item['link']})")

    # Chunk into Discord safe message size (< 1900 chars)
    chunk = header
    for line in lines:
        if len(chunk) + len(line) + 2 > 1900:
            try:
                _post_message(webhook_url, chunk)
            except Exception as e:
                print(f"Error posting to webhook: {e}")
            chunk = header
        chunk += line + "\n"

    if chunk != header:
        try:
            _post_message(webhook_url, chunk)
        except Exception as e:
            print(f"Error posting to webhook: {e}")

if __name__ == "__main__":
    sample_flights = [
        {
            "origin": "SFO",
            "destination": "CUN",
            "destination_name": "Cancun, Mexico (CUN)",
            "price": 389.0,
            "airline": "United",
            "departure_date": "2026-11-13",
            "return_date": "2026-11-20",
            "booking_url": "https://www.google.com/travel/flights",
            "chase_partner_info": {"partners": ["United MileagePlus"]},
            "has_transfer_bonus": True
        }
    ]
    send_alert("", "SFO Flight Deals Found", sample_flights)
