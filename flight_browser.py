"""Opt-in, bounded Google Flights browser retries for unpriced itineraries."""
import calendar
import copy
import json
import math
import re
import time
from types import SimpleNamespace
from datetime import datetime, timezone
from urllib.parse import parse_qs


def _text(value):
    return " ".join(value.split())


def _clock(value):
    hour, minute = value.time
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def _day(value):
    day = datetime(*value.date)
    return f"{calendar.day_name[day.weekday()]}, {calendar.month_name[day.month]} {day.day}"


def _signature(item):
    """Match the visible route, carriers, times, dates, stops and duration."""
    legs = item.flights
    first, last = legs[0], legs[-1]
    elapsed = sum(leg.duration for leg in legs)
    for previous, following in zip(legs, legs[1:]):
        wait = datetime(*following.departure.date, *following.departure.time) - datetime(*previous.arrival.date, *previous.arrival.time)
        elapsed += max(0, int(wait.total_seconds() / 60))
    hours, minutes = divmod(elapsed, 60)
    duration = " ".join(part for part in (f"{hours} hr" if hours else "", f"{minutes} min" if minutes else "") if part)
    stops = len(legs) - 1
    connections = "Nonstop" if stops == 0 else f"{stops} {'stop' if stops == 1 else 'stops'}"
    return _text(f"{connections} flight with {' and '.join(item.airlines)}. "
                 f"Leaves {first.from_airport.name} at {_clock(first.departure)} on {_day(first.departure)} "
                 f"and arrives at {last.to_airport.name} at {_clock(last.arrival)} on {_day(last.arrival)}. "
                 f"Total duration {duration}.")


def apply_browser_prices(items, labels):
    """Accept only explicit USD round-trip quotes with one unambiguous match."""
    pending = {}
    for item in items:
        if item.price is None and item.flights:
            pending.setdefault(_signature(item), []).append(item)
    quotes = {}
    for label in labels:
        match = re.match(r"From ([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?) US dollars round trip total\. (.+)", _text(label))
        if not match:
            continue
        price = float(match[1].replace(",", ""))
        for signature in pending:
            if match[2].startswith(signature + " ") or match[2] == signature:
                quotes.setdefault(signature, set()).add(price)
    recovered = 0
    for signature, candidates in pending.items():
        prices = quotes.get(signature, set())
        if len(candidates) != 1 or len(prices) != 1:
            continue
        price = next(iter(prices))
        if price <= 0:
            continue
        item = candidates[0]
        item.price = price
        item.price_source = "google_flights_browser"
        item.price_checked_at = datetime.now(timezone.utc).isoformat()
        recovered += 1
    return recovered


def saved_browser_items(itineraries, carriers):
    """Rebuild public schedule fields; legacy snapshots use carrier placeholders."""
    from fast_flights.model import Airport, Flights, SimpleDatetime, SingleFlight
    from fast_flights.parser import ResultList
    selected = {name.casefold() for name in carriers}
    results = ResultList()
    results.metadata = SimpleNamespace(airlines=[])
    for item in itineraries or []:
        if not {name.casefold() for name in item["airlines"]}.issubset(selected):
            continue
        legs = []
        for leg in item["flights"]:
            legs.append(SingleFlight(from_airport=Airport(**leg["from_airport"]), to_airport=Airport(**leg["to_airport"]),
                                     departure=SimpleDatetime(**leg["departure"]), arrival=SimpleDatetime(**leg["arrival"]),
                                     duration=leg["duration"], plane_type=leg.get("plane_type")))
        results.append(Flights(type="single", price=None, airlines=item["airlines"], flights=legs, carbon=None))
    represented = {name.casefold() for item in results for name in item.airlines}
    results.extend(SimpleNamespace(price=None, airlines=[name], flights=[]) for name in carriers if name.casefold() not in represented)
    return results


def shopping_response_flights(text, query, carriers, *, include_unpriced=False):
    """Read every framed shopping update, restricted to the requested route."""
    from fast_flights.parser import parse_js
    if query.get_trip_type() != "round-trip" or query.currency != "USD":
        return []
    outbound = query.flight_data[0]
    decoder = json.JSONDecoder()
    offset = text.find("[")
    flights, seen = [], set()
    while offset >= 0:
        frames, used = decoder.raw_decode(text[offset:])
        offset = text.find("[", offset + used)
        for frame in frames:
            if not isinstance(frame, list) or not frame or frame[0] != "wrb.fr" or len(frame) < 3 or not isinstance(frame[2], str):
                continue
            payload = json.loads(frame[2])
            if not isinstance(payload, list) or len(payload) < 8:
                continue
            groups = []
            for section in (payload[2], payload[3]):
                for group in (section[0] or []) if section is not None else []:
                    try:
                        legs = group[0][2]
                        price = group[1][0][1] if len(group[1][0]) > 1 else None
                        if not (include_unpriced and price is None) and (isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0):
                            continue
                        if not set(group[0][1]) & carriers or legs[0][3] != outbound.from_airport.airport or legs[-1][6] != outbound.to_airport.airport:
                            continue
                        if tuple(legs[0][20]) != tuple(map(int, outbound.date.split("-"))):
                            continue
                    except (IndexError, TypeError, AttributeError):
                        continue
                    key = json.dumps(group, sort_keys=True)
                    if key not in seen:
                        if price is None:
                            group[1] = [[None, None]]
                        groups.append(group)
                        seen.add(key)
            if groups:
                payload[3] = [groups]
                flights.extend(parse_js(f"data:{json.dumps(payload, separators=(',', ':'))},"))
    return flights


def fill_missing_prices(query, items, *, engine="chromium", airlines=None, timeout_seconds=None, browser_only=False, progress=None):
    """Retry a fixed query without login, profile reuse or challenge bypasses."""
    if engine == "native-chrome":
        from flight_native_browser import fill_native_prices
        return fill_native_prices(query, items, airlines=airlines, timeout_seconds=timeout_seconds or 90, browser_only=browser_only, progress=progress)
    timeout_seconds = timeout_seconds or 45
    report = {"status": "unavailable", "recovered": 0, "engine": engine, "stage": "launch", "sections_checked": []}
    started = time.monotonic()
    browser_flights = []
    labels = []
    selected = {name.casefold() for name in airlines} if airlines else None
    missing_carriers = {name for item in items if item.price is None and (selected is None or {name.casefold() for name in item.airlines}.issubset(selected)) for name in item.airlines}
    # Apply Google’s airline choices after its initial search, matching the
    # captured flow. Preserve dates and live connection constraints.
    codes = [airline.code for airline in getattr(getattr(items, "metadata", None), "airlines", []) if airline.name in missing_carriers]
    browser_query = copy.deepcopy(query)
    if codes or browser_only:
        for flight in browser_query.flight_data:
            del flight.airlines[:]
    def remaining():
        left = timeout_seconds - (time.monotonic() - started)
        if left <= 0:
            raise TimeoutError("Browser retry timed out")
        return max(1, int(left * 1000))
    def ingest(rows):
        priced = [row for row in rows if row.price is not None]
        browser_flights.extend(priced)
        if not browser_only:
            return
        observed = {name.casefold() for row in rows for name in row.airlines}
        items[:] = [item for item in items if item.flights or not {name.casefold() for name in item.airlines}.issubset(observed)]
        pending = {_signature(item) for item in items if item.flights}
        for row in rows:
            if row.price is None and _signature(row) not in pending:
                pending.add(_signature(row))
                items.append(row)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, timeout=remaining(), **({"channel": "chrome"} if engine == "chrome" else {}))
            try:
                page = browser.new_page(locale="en-US")
                requests = set()
                filtered_responses = set()
                def remember_request(request):
                    if "FlightsFrontendService/GetShoppingResults" in request.url:
                        requests.add(request)
                def read_response(response):
                    if response.request in requests and response.status == 200:
                        try:
                            ingest(shopping_response_flights(response.text(), query, missing_carriers, include_unpriced=browser_only))
                            form = parse_qs(response.request.post_data or "")
                            wrapped = json.loads(form["f.req"][0])
                            request_query = json.loads(wrapped[1])
                            request_codes = set(request_query[1][13][0][4] or [])
                            if (codes and request_codes == set(codes)) or (browser_only and request_codes):
                                filtered_responses.add(response.request)
                        except Exception:
                            # A filter change can cancel an earlier response.
                            # Its missing body must not abort later valid replies.
                            report["response_errors"] = report.get("response_errors", 0) + 1
                page.on("request", remember_request)
                page.on("response", read_response)
                report["stage"] = "best"
                page.goto(browser_query.url(), wait_until="domcontentloaded", timeout=remaining())
                # Wait for Google's completed result state, not just a heading
                # that can appear before prices have finished loading.
                page.wait_for_function(
                    "() => /(?:\\d+ results returned|No results returned|Oops, something went wrong|unusual traffic|not a robot)/i.test(document.body.innerText)",
                    timeout=remaining())
                page.get_by_text("Fetching results", exact=True).wait_for(state="hidden", timeout=remaining())
                text = page.locator("body").inner_text(timeout=remaining())
                if re.search(r"Oops, something went wrong|unusual traffic|not a robot", text, re.I):
                    raise RuntimeError("Google's browser search failed or requires human verification")
                if browser_only:
                    from selectolax.lexbor import LexborHTMLParser
                    script = LexborHTMLParser(page.content()).css_first(r"script.ds\:1")
                    if script:
                        payload = script.text().split("data:", 1)[1].rsplit(",", 1)[0]
                        ingest(shopping_response_flights(json.dumps([["wrb.fr", None, payload]]), query, missing_carriers, include_unpriced=True))
                def collect_labels():
                    labels.extend(page.locator('li [role="link"][aria-label]').evaluate_all(
                        "elements => elements.map(element => element.getAttribute('aria-label'))"))
                def click_and_collect(control):
                    before = page.locator('li [role="link"][aria-label]').evaluate_all(
                        "elements => elements.map(element => element.getAttribute('aria-label'))")
                    was_selected = control.get_attribute("aria-selected")
                    control.press("Enter", timeout=remaining())
                    # Expansion can use cached data; wait for changed cards as
                    # well as fetched data, rather than requiring another RPC.
                    page.wait_for_function(
                        "state => !document.body.innerText.includes('Fetching results') && (JSON.stringify([...document.querySelectorAll('li [role=link][aria-label]')].map(element => element.getAttribute('aria-label'))) !== JSON.stringify(state.before) || state.tab && [...document.querySelectorAll('[role=tab]')].some(e => e.getAttribute('aria-selected') === 'true' && e.innerText.includes('Cheapest')) || /Oops, something went wrong/.test(document.body.innerText))",
                        arg={"before": before, "tab": was_selected is not None}, timeout=remaining())
                    if "Oops, something went wrong" in page.locator("body").inner_text(timeout=remaining()):
                        raise RuntimeError("Google's browser search failed")
                    collect_labels()
                collect_labels()
                report["sections_checked"].append("best")
                if codes or browser_only:
                    report["stage"] = "airline_filter"
                    before_filtered = set(filtered_responses)
                    page.keyboard.press("Escape")
                    page.get_by_role("button", name=re.compile(r"^Airlines(?:,|$)")).press("Enter", timeout=remaining())
                    all_airlines = page.get_by_role("switch", name="Select all airlines", exact=True)
                    if all_airlines.get_attribute("aria-checked") == "true":
                        all_airlines.click(timeout=remaining())
                    for name in sorted(missing_carriers):
                        page.get_by_role("checkbox", name=name, exact=True).check(timeout=remaining())
                    remaining()
                    page.keyboard.press("Escape")
                    while not (filtered_responses - before_filtered):
                        page.wait_for_timeout(min(100, remaining()))
                    # Cheapest's reference can finish after the flight cards.
                    # Do not switch while its header still says Fetching results.
                    report["stage"] = "price_reference"
                    page.wait_for_function(
                        "() => /(?:\\d+ results returned|No results returned|Oops, something went wrong)/.test(document.body.innerText) && !document.body.innerText.includes('Fetching results')",
                        timeout=remaining())
                    if "Oops, something went wrong" in page.locator("body").inner_text(timeout=remaining()):
                        raise RuntimeError("Google's filtered browser search failed")
                    collect_labels()
                    report["sections_checked"].append("filtered_best")
                more = page.get_by_role("button", name="View more flights", exact=True)
                cheapest = page.get_by_role("tab", name=re.compile("Cheapest"))
                if "No results returned" not in page.locator("body").inner_text(timeout=remaining()):
                    cheapest.wait_for(state="visible", timeout=remaining())
                if cheapest.count() and cheapest.get_attribute("aria-selected") != "true":
                    report["stage"] = "cheapest"
                    click_and_collect(cheapest)
                    report["sections_checked"].append("cheapest")
                    if more.count():
                        report["stage"] = "more_cheapest"
                        click_and_collect(more)
                        report["sections_checked"].append("more_cheapest")
                elif not cheapest.count() and more.count():
                    report["stage"] = "more_best"
                    click_and_collect(more)
                    report["sections_checked"].append("more_best")
                report["status"] = "price_unavailable"
                report["stage"] = "complete"
                report["message"] = "Google's browser did not provide a matching numeric quote."
            finally:
                browser.close()
    except ImportError:
        report["message"] = "Install requirements-browser.txt and run python -m playwright install chromium, or select installed Chrome."
    except Exception as error:
        # Playwright exception text may contain full request URLs or runtime
        # data. Keep only this actionable, non-sensitive status in snapshots.
        report["message"] = "Browser retry failed or timed out. Check browser installation or open Google Flights manually; no price was inferred."
        report["failure_kind"] = type(error).__name__
    # Retain exact DOM quotes even if a later expansion failed. Parsed shopping
    # quotes can fill original itineraries as well as add longer alternatives.
    for item in browser_flights:
        labels.append(f"From {item.price} US dollars round trip total. {_signature(item)}")
    report["recovered"] = apply_browser_prices(items, labels)
    # Valid priced shopping responses can contain additional itineraries, such
    # as longer connections absent from Best. Preserve them even if a later
    # browser step fails, without treating the whole retry as successful.
    def key_for(item):
        return (item.price, tuple(item.airlines), repr(item.flights))
    seen = {key_for(item) for item in items}
    for item in browser_flights:
        key = key_for(item)
        if key in seen:
            continue
        seen.add(key)
        item.price_source = "google_flights_browser"
        item.price_checked_at = datetime.now(timezone.utc).isoformat()
        items.append(item)
        report["recovered"] += 1
    if report["recovered"] and report["status"] != "unavailable":
        report["status"] = "recovered"
        report["message"] = "Browser quotes matched to the requested search."
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return report
