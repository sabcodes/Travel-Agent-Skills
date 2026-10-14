"""Isolated browser evaluation. Does not change the flight app or its rankings."""
import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fast_flights import FlightQuery, create_filter
from flight_browser import _signature, shopping_response_flights
from playwright.sync_api import sync_playwright

CASES = {
    "captured_singapore": ("DAC", "2027-01-12", "2027-02-13", "Singapore Airlines"),
    "five_day_singapore": ("DAC", "2027-01-12", "2027-01-16", "Singapore Airlines"),
    "control_cancun": ("CUN", "2027-01-12", "2027-01-16", None),
}
EXPECTED_SHA256 = "35d4858813f1ff572550d1a8e55ea2886f313462e0ed93f95f9047792c66674a"


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def query_for(case):
    destination, departure, returning, airline = CASES[case]
    return create_filter(flights=[FlightQuery(date=departure, from_airport="SFO", to_airport=destination),
                                 FlightQuery(date=returning, from_airport=destination, to_airport="SFO")],
                         trip="round-trip", currency="USD", language="en-US", seat="economy")


def candidate_quotes(text, query, airline=None):
    """Reuse the app decoder; retain exact-carrier rows and public schedules."""
    decoder = json.JSONDecoder()
    offset = text.find("[")
    carriers = set()
    while offset >= 0:
        frames, used = decoder.raw_decode(text[offset:])
        offset = text.find("[", offset + used)
        for frame in frames:
            if isinstance(frame, list) and len(frame) > 2 and frame[0] == "wrb.fr" and isinstance(frame[2], str):
                payload = json.loads(frame[2])
                for section in (payload[2], payload[3]) if isinstance(payload, list) and len(payload) > 3 else []:
                    for group in (section[0] or []) if section else []:
                        carriers.update(group[0][1])
    if airline:
        carriers = {airline}
    rows = []
    for item in shopping_response_flights(text, query, carriers):
        if airline and set(item.airlines) != {airline}:
            continue
        rows.append({"airlines": item.airlines, "price": item.price, "signature": _signature(item),
                     "legs": [{"from": leg.from_airport.code, "to": leg.to_airport.code,
                               "departure_date": leg.departure.date, "departure_time": leg.departure.time,
                               "arrival_date": leg.arrival.date, "arrival_time": leg.arrival.time,
                               "duration_minutes": leg.duration} for leg in item.flights]})
    return rows


def verified_quotes(candidates, snapshots):
    """Require a numeric network quote and its explicit USD Cheapest-row label."""
    labels = [label for state in snapshots
              if state["stage"] in ("cheapest", "expanded_cheapest") or
              (state["stage"] == "final" and any(tab["selected"] == "true" and "Cheapest" in tab["label"] for tab in state["tabs"]))
              for label in state["labels"]]
    matched = {}
    for row in candidates:
        for label in labels:
            match = re.match(r"From ([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?) US dollars round trip total\. (.+)", " ".join(label.split()))
            if (match and float(match[1].replace(",", "")) == row["price"] and
                (match[2] == row["signature"] or match[2].startswith(row["signature"] + " ")) and
                not re.search(r"premium economy|business|first class", label, re.I)):
                matched[(row["signature"], row["price"])] = row
                break
    return list(matched.values())


@contextlib.contextmanager
def browser_session(engine, binary, stylesheets=False, headed=False, profile_dir=None, har_path=None, omit_automation_flag=False, disable_webdriver_signal=False):
    process = None
    browser = None
    context = None
    with sync_playwright() as playwright:
        try:
            if engine == "chrome":
                launch_options = {"ignore_default_args": ["--enable-automation"]} if omit_automation_flag else {}
                if disable_webdriver_signal:
                    launch_options["args"] = ["--disable-blink-features=AutomationControlled"]
                if profile_dir:
                    context = playwright.chromium.launch_persistent_context(
                        profile_dir, headless=not headed, channel="chrome", timeout=15000,
                        record_har_path=str(har_path) if har_path else None,
                        record_har_content="embed", **launch_options)
                else:
                    browser = playwright.chromium.launch(headless=not headed, channel="chrome", timeout=15000, **launch_options)
            else:
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    port = reservation.getsockname()[1]
                command = [str(binary), "serve", "--host", "127.0.0.1", "--port", str(port),
                           "--locale", "en-US", "--log-level", "fatal", "--disable-metrics"]
                if stylesheets:
                    command.extend(["--load-resources", "stylesheet"])
                process = subprocess.Popen(command,
                                           env={**os.environ, "LIGHTPANDA_DISABLE_TELEMETRY": "true", "LIGHTPANDA_DISABLE_CORE_DUMP": "1"},
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Lightpanda exited before accepting connections")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise TimeoutError("Lightpanda startup timed out")
                        time.sleep(0.1)
                browser = playwright.chromium.connect_over_cdp(f"ws://127.0.0.1:{port}", timeout=15000)
            if context is None:
                context = browser.new_context(record_har_path=str(har_path) if har_path else None,
                                              record_har_content="embed")
            page = context.new_page()
            page.set_default_timeout(10000)
            yield page, process
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


class SmokeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/quote":
            content = b'{"price": 400}'
            mime = "application/json"
        else:
            content = b'''<!doctype html><title>Local capability check</title>
<label><input type="checkbox">Singapore Airlines</label><button role="tab" aria-selected="false">Cheapest</button>
<p id="result">Waiting</p><script>
document.querySelector('button').onclick=async()=>{
  const quote=await(await fetch('/quote')).json();
  document.querySelector('#result').textContent='Fixture quote '+quote.price;
  document.querySelector('button').setAttribute('aria-selected','true');
};</script>'''
            mime = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass


def smoke(page, report):
    server = ThreadingHTTPServer(("127.0.0.1", 0), SmokeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report["stage"] = "local_navigation"
        page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="domcontentloaded", timeout=10000)
        report["stage"] = "checkbox"
        page.get_by_role("checkbox", name="Singapore Airlines", exact=True).check()
        assert page.get_by_role("checkbox", name="Singapore Airlines", exact=True).is_checked()
        report["stage"] = "javascript_fetch_and_tab"
        page.get_by_role("tab", name="Cheapest", exact=True).press("Enter")
        page.wait_for_function("() => document.querySelector('#result').textContent === 'Fixture quote 400'", timeout=10000)
        report.update(status="passed", fixture=True, live_price_recovery_verified=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def live(page, args, report):
    query = query_for(args.case)
    destination, departure, returning, airline = CASES[args.case]
    report.update(origin="SFO", destination=destination, departure_date=departure, return_date=returning,
                  airline_filter=airline, passengers=1, cabin="economy", currency="USD",
                  snapshots=[], network_quotes=[], shopping_updates=[], response_count=0, decoder_errors=0, javascript_errors=0,
                  proceed_anyway=args.proceed_anyway, dom_controls=args.dom_controls, stylesheets=args.stylesheets)
    report.update(headed=args.headed, persistent_profile=bool(args.profile_dir),
                  rpc_region=args.rpc_region, settle_seconds=args.settle_seconds)
    report["omit_automation_flag"] = args.omit_automation_flag
    report["disable_webdriver_signal"] = args.disable_webdriver_signal
    report["skip_airline_filter"] = args.skip_airline_filter
    report["filter_after_cheapest"] = args.filter_after_cheapest
    report["browser_environment"] = page.evaluate("() => ({webdriver:navigator.webdriver, language:navigator.language, languages:navigator.languages})")
    page.add_init_script("""(() => {
      window.__singaporePriceEvents = [];
      let previous = '';
      function record() {
        const rows = [...document.querySelectorAll('li')]
          .filter(e => e.innerText.includes('Singapore Airlines'))
          .map(e => ({text:e.innerText, labels:[...e.querySelectorAll('[aria-label]')]
            .map(n => n.getAttribute('aria-label'))}));
        const key = JSON.stringify(rows);
        if (rows.length && key !== previous && window.__singaporePriceEvents.length < 1000) {
          previous = key;
          window.__singaporePriceEvents.push({elapsed_ms:performance.now(), rows,
            selected_tab:document.querySelector('[role=tab][aria-selected=true]')?.innerText});
        }
      }
      new MutationObserver(record).observe(document, {subtree:true, childList:true,
        characterData:true, attributes:true, attributeFilter:['aria-label']});
    })();""")
    if args.rpc_region:
        def localize(route):
            address = urlsplit(route.request.url)
            parameters = parse_qs(address.query)
            parameters["gl"] = [args.rpc_region]
            route.continue_(url=urlunsplit(address._replace(query=urlencode(parameters, doseq=True))))
        page.route("**/FlightsFrontendService/**", localize)
    candidates = {}
    def activate(control):
        if args.dom_controls:
            control.evaluate("element => (element.closest('button,a,[role=button],[role=checkbox],[role=switch],[role=tab]') || element).click()")
        else:
            control.press("Enter")
    def add(rows):
        for row in rows:
            candidates[(row["signature"], row["price"])] = row
    def response_received(response):
        if "FlightsFrontendService/GetShoppingResults" not in response.url or response.status != 200:
            return
        report["response_count"] += 1
        try:
            form = parse_qs(response.request.post_data or "")
            parameters = json.loads(json.loads(form["f.req"][0])[1])
            segments = parameters[1][13]
            if segments[0][6] != departure or segments[1][6] != returning:
                return
            text = response.text()
            observation = {"flags": parameters[2:6], "request_reference_present": len(parameters) > 6 and parameters[6] is not None,
                           "singapore_price_fields": []}
            decoder = json.JSONDecoder()
            offset = text.find("[")
            while offset >= 0:
                frames, used = decoder.raw_decode(text[offset:])
                offset = text.find("[", offset + used)
                for frame in frames:
                    if isinstance(frame, list) and len(frame) > 2 and frame[0] == "wrb.fr" and isinstance(frame[2], str):
                        payload = json.loads(frame[2])
                        for section in (payload[2], payload[3]) if isinstance(payload, list) and len(payload) > 3 else []:
                            for group in (section[0] or []) if section else []:
                                if set(group[0][1]) == {"Singapore Airlines"}:
                                    field = group[1][0][1] if group[1] and len(group[1][0]) > 1 else None
                                    observation["singapore_price_fields"].append({"type": type(field).__name__, "value": field if field is None or isinstance(field, (int, float)) else "non_numeric"})
            report["shopping_updates"].append(observation)
            add(candidate_quotes(text, query, airline))
        except Exception:
            report["decoder_errors"] += 1
    page.on("response", response_received)
    page.on("pageerror", lambda error: report.update(javascript_errors=report["javascript_errors"] + 1))
    def snapshot(stage):
        state = page.evaluate("() => ({body: document.body.innerText, labels: [...document.querySelectorAll('li [role=link][aria-label]')].map(e => e.getAttribute('aria-label')), tabs: [...document.querySelectorAll('[role=tab]')].map(e => ({label:e.innerText,selected:e.getAttribute('aria-selected')}))})")
        report["snapshots"].append({"stage": stage, **state})
        write(Path(args.output_dir) / (stage + ".json"), state)
        if re.search(r"Oops, something went wrong|unusual traffic|not a robot|browser.*not supported", state["body"], re.I):
            raise RuntimeError("Google browser failure or unsupported browser")
    def settled():
        page.wait_for_function("() => /(?:\\d+ results returned|No results returned|Oops, something went wrong|unusual traffic|not a robot|browser.*not supported)/i.test(document.body.innerText) && !document.body.innerText.includes('Fetching results')", timeout=20000)
    def apply_airline_filter(stage):
        report["stage"] = "airline_filter"
        activate(page.get_by_role("button", name=re.compile(r"^Airlines(?:,|$)")))
        all_airlines = page.get_by_role("switch", name="Select all airlines", exact=True)
        if all_airlines.get_attribute("aria-checked") == "true":
            activate(all_airlines) if args.dom_controls else all_airlines.click()
        checkbox = page.get_by_role("checkbox", name=airline, exact=True)
        activate(checkbox) if args.dom_controls else checkbox.check()
        page.keyboard.press("Escape")
        page.wait_for_function("() => document.body.innerText.includes('All filters (1)') && !document.body.innerText.includes('Fetching results')", timeout=20000)
        settled()
        snapshot(stage)
    try:
        report["stage"] = "best"
        address = urlsplit(query.url())
        parameters = parse_qs(address.query)
        parameters.update(gl=["US"], hl=["en-US"])
        page.goto(urlunsplit(address._replace(query=urlencode(parameters, doseq=True))), wait_until="domcontentloaded", timeout=20000)
        if args.proceed_anyway:
            page.wait_for_function("() => document.body.innerText.includes('Time for an upgrade') || /(?:\\d+ results returned|No results returned|Oops, something went wrong)/.test(document.body.innerText)", timeout=20000)
            if "Time for an upgrade" in page.locator("body").inner_text():
                snapshot("upgrade_prompt")
                report["stage"] = "proceed_anyway"
                report["upgrade_control"] = page.get_by_text("Proceed anyway", exact=True).evaluate("e => ({tag: e.tagName, role: e.getAttribute('role'), tab_index: e.getAttribute('tabindex')})")
                control = page.get_by_text("Proceed anyway", exact=True)
                if args.dom_controls:
                    activate(control)
                else:
                    control.click()
                report["proceed_clicked"] = True
        settled()
        snapshot("best")
        from selectolax.lexbor import LexborHTMLParser
        initial = LexborHTMLParser(page.content()).css_first(r"script.ds\:1")
        if initial:
            try:
                payload, _ = json.JSONDecoder().raw_decode(initial.text().split("data:", 1)[1].lstrip())
                initial_rows = candidate_quotes(json.dumps([["wrb.fr", None, json.dumps(payload)]]), query, airline)
                report["initial_network_quotes"] = initial_rows
                add(initial_rows)
            except Exception:
                report["decoder_errors"] += 1
        if airline and not args.skip_airline_filter and not args.filter_after_cheapest:
            apply_airline_filter("filtered_best")
        report["stage"] = "cheapest"
        activate(page.get_by_role("tab", name=re.compile("Cheapest")))
        page.wait_for_function("() => [...document.querySelectorAll('[role=tab]')].some(e => e.getAttribute('aria-selected') === 'true' && e.innerText.includes('Cheapest'))", timeout=10000)
        settled()
        snapshot("cheapest")
        more = page.get_by_role("button", name="View more flights", exact=True)
        if more.count():
            report["stage"] = "expanded_cheapest"
            activate(more)
            page.get_by_role("button", name="View fewer flights", exact=True).wait_for(timeout=10000)
            settled()
            snapshot("expanded_cheapest")
        if airline and args.filter_after_cheapest:
            apply_airline_filter("filtered_cheapest")
        if args.settle_seconds:
            report["stage"] = "waiting_for_pricing"
            page.wait_for_timeout(args.settle_seconds * 1000)
            snapshot("final")
        report["stage"] = "complete"
        report["status"] = "no_verified_price"
    finally:
        try:
            report["dom_price_events"] = page.evaluate("() => window.__singaporePriceEvents || []")
            write(Path(args.output_dir) / "price-events.json", report["dom_price_events"])
            report["dom_price_event_count"] = len(report["dom_price_events"])
            page.screenshot(path=str(Path(args.output_dir) / "final.png"))
        except Exception:
            report["dom_capture_failed"] = True
        try:
            snapshot("final")
        except Exception:
            pass
        report["network_quotes"] = list(candidates.values())
        report["verified_rows"] = verified_quotes(candidates.values(), report["snapshots"])
        report["live_price_recovery_verified"] = bool(report["verified_rows"])
        if report.get("status") == "no_verified_price" and report["live_price_recovery_verified"]:
            report["status"] = "priced"


def probe(args):
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {"engine": args.engine, "case": args.case, "checked_at": datetime.now(timezone.utc).isoformat(),
              "status": "unavailable", "stage": "launch", "live_price_recovery_verified": False}
    if args.engine == "lightpanda":
        report["binary_sha256"] = hashlib.sha256(Path(args.binary).read_bytes()).hexdigest()
        assert report["binary_sha256"] == EXPECTED_SHA256, "Unexpected Lightpanda build"
    try:
        with browser_session(args.engine, args.binary, args.stylesheets, args.headed, args.profile_dir,
                             Path(args.output_dir) / "browser.har" if args.record_har else None,
                             args.omit_automation_flag, args.disable_webdriver_signal) as (page, process):
            if args.case == "smoke":
                smoke(page, report)
            else:
                live(page, args, report)
    except Exception as error:
        report.update(status="unavailable", failure_kind=type(error).__name__)
        method = re.search(r"Protocol error \(([A-Za-z.]+)\)", str(error))
        if method:
            report["failed_protocol_method"] = method[1]
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    write(Path(args.output_dir) / "report.json", report)
    print(json.dumps({key: value for key, value in report.items() if key not in ("snapshots", "network_quotes", "initial_network_quotes", "verified_rows", "dom_price_events")}), flush=True)
    return 0 if report["status"] in ("passed", "priced") else 1


def captured(args):
    har = json.loads(Path(args.har).read_text())
    rows = {}
    query = query_for("captured_singapore")
    for entry in har["log"]["entries"]:
        if "FlightsFrontendService/GetShoppingResults" not in entry["request"]["url"]:
            continue
        content = entry["response"]["content"]
        text = content.get("text", "")
        if content.get("encoding") == "base64":
            text = base64.b64decode(text).decode()
        for row in candidate_quotes(text, query, "Singapore Airlines") if text else []:
            rows[(row["signature"], row["price"])] = row
    report = {"source": "historical_har", "live_price_recovery_verified": False, "rows": list(rows.values())}
    write(args.output, report)
    print(json.dumps({"historical_rows": len(rows), "historical_prices": sorted({row["price"] for row in rows.values()}), "live_price_recovery_verified": False}))
    return 0 if rows else 1


def final_capture_quotes(har, report, case="captured_singapore"):
    """Require the target dates, SQ filters on both legs, and the final priced DOM."""
    if report.get("status") not in ("complete_requires_price_verification", "priced", "no_verified_price"):
        return []
    final = report.get("final_state")
    if not final:
        final = next((state for state in reversed(report.get("snapshots", [])) if state["stage"] == "final"), None)
    if not final:
        return []
    query = query_for(case)
    _, departure, returning, airline = CASES[case]
    candidates = {}
    for entry in har["log"]["entries"]:
        if "FlightsFrontendService/GetShoppingResults" not in entry["request"]["url"] or entry["response"]["status"] != 200:
            continue
        from compare_flight_hars import request_query, public_segments
        parameters = request_query(entry)
        if not parameters:
            continue
        segments = public_segments(parameters)
        if [segment["date"] for segment in segments] != [departure, returning] or any(segment["airlines"] != ["SQ"] for segment in segments):
            continue
        content = entry["response"].get("content", {})
        text = content.get("text", "")
        if content.get("encoding") == "base64":
            text = base64.b64decode(text).decode()
        for row in candidate_quotes(text, query, airline) if text else []:
            candidates[(row["signature"], row["price"])] = row
    return verified_quotes(candidates.values(), [{**final, "stage": "final"}])


def verify_capture(args):
    report = json.loads(Path(args.report).read_text())
    rows = final_capture_quotes(json.loads(Path(args.har).read_text()), report, args.case)
    result = {"source": "saved_browser_capture", "checked_at": report.get("checked_at"),
              "case": args.case, "required_airline_filter": "SQ on both legs",
              "final_dom_and_network_match": bool(rows), "verified_rows": rows}
    write(args.output, result)
    print(json.dumps({"passed": bool(rows), "verified_rows": len(rows), "prices": sorted({row["price"] for row in rows})}))
    return 0 if rows else 1


def suite(args):
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(), "runs": [],
              "binary_version": subprocess.check_output([args.binary, "version"], text=True,
                 env={**os.environ, "LIGHTPANDA_DISABLE_TELEMETRY": "true", "LIGHTPANDA_DISABLE_CORE_DUMP": "1"}).strip(),
              "binary_sha256": hashlib.sha256(Path(args.binary).read_bytes()).hexdigest(),
              "integration_approved": False}
    plan = [(engine, "smoke", 1) for engine in args.engines]
    plan += [(engine, case, repeat) for repeat in range(1, args.repeats + 1)
             for case in args.cases
             for engine in args.engines]
    for engine, case, repeat in plan:
        folder = root / f"{engine}-{case}-{repeat}"
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "probe", "--engine", engine,
                   "--case", case, "--binary", args.binary, "--output-dir", str(folder)]
        if args.proceed_anyway:
            command.append("--proceed-anyway")
        if args.dom_controls:
            command.append("--dom-controls")
        if args.stylesheets:
            command.append("--stylesheets")
        print(f"Starting {engine} {case} repeat {repeat}", flush=True)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            process.communicate(timeout=args.timeout)
            row = json.loads((folder / "report.json").read_text())
        except (subprocess.TimeoutExpired, OSError, ValueError):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
            row = {"engine": engine, "case": case, "status": "worker_timeout_or_error", "live_price_recovery_verified": False}
        # Public report excludes HTML, page bodies, opaque tokens and all URLs.
        summary = {key: value for key, value in row.items() if key not in ("snapshots", "network_quotes")}
        summary.update(repeat=repeat, network_priced_count=len(row.get("network_quotes", [])),
                       rendered_verified_count=len(row.get("verified_rows", [])),
                       sections_checked=[state["stage"] for state in row.get("snapshots", [])])
        result["runs"].append(summary)
        write(root / "summary.json", result)
        print(f"{engine} {case}: {row['status']}; {summary['rendered_verified_count']} verified rows; stage {row.get('stage')}", flush=True)
    actual = [row for row in result["runs"] if row["case"] != "smoke"]
    lightpanda = [row for row in actual if row["engine"] == "lightpanda"]
    result["lightpanda_eligible_for_integration"] = bool(lightpanda) and args.repeats >= 2 and all(row["status"] == "priced" for row in lightpanda)
    result["integration_approved"] = False
    result["decision"] = "candidate_passed_live_cases_requires_review" if result["lightpanda_eligible_for_integration"] else "do_not_integrate"
    write(root / "summary.json", result)
    print(json.dumps({"decision": result["decision"], "completed_runs": len(result["runs"])}), flush=True)
    return 0 if result["lightpanda_eligible_for_integration"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    probe_parser = commands.add_parser("probe")
    probe_parser.add_argument("--engine", choices=("lightpanda", "chrome"), required=True)
    probe_parser.add_argument("--binary", default="/tmp/travel-agent-lightpanda-eval/bin/lightpanda-aarch64-macos")
    probe_parser.add_argument("--case", choices=("smoke", *CASES), required=True)
    probe_parser.add_argument("--output-dir", required=True)
    probe_parser.add_argument("--proceed-anyway", action="store_true")
    probe_parser.add_argument("--dom-controls", action="store_true")
    probe_parser.add_argument("--stylesheets", action="store_true")
    probe_parser.add_argument("--headed", action="store_true")
    probe_parser.add_argument("--profile-dir", help="Dedicated test profile only; never use a personal Chrome profile")
    probe_parser.add_argument("--record-har", action="store_true")
    probe_parser.add_argument("--omit-automation-flag", action="store_true", help="Diagnostic: omit only Chrome's --enable-automation launch flag")
    probe_parser.add_argument("--disable-webdriver-signal", action="store_true", help="Diagnostic: disable the AutomationControlled Blink feature")
    probe_parser.add_argument("--skip-airline-filter", action="store_true", help="Open unfiltered Cheapest; retain only the target carrier in decoded output")
    probe_parser.add_argument("--filter-after-cheapest", action="store_true", help="Apply the airline filter after expanding Cheapest results")
    probe_parser.add_argument("--rpc-region", choices=("US",), help="Explicit region for Google's shopping requests")
    probe_parser.add_argument("--settle-seconds", type=int, choices=range(0, 61), default=0)
    captured_parser = commands.add_parser("captured")
    captured_parser.add_argument("--har", required=True)
    captured_parser.add_argument("--output", required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--har", required=True)
    verify_parser.add_argument("--report", required=True)
    verify_parser.add_argument("--output", required=True)
    verify_parser.add_argument("--case", choices=("captured_singapore", "five_day_singapore"), default="captured_singapore")
    suite_parser = commands.add_parser("suite")
    suite_parser.add_argument("--binary", required=True)
    suite_parser.add_argument("--output-dir", required=True)
    suite_parser.add_argument("--repeats", type=int, default=2)
    suite_parser.add_argument("--timeout", type=int, default=90)
    suite_parser.add_argument("--engines", choices=("chrome", "lightpanda"), nargs="+", default=["lightpanda"])
    suite_parser.add_argument("--cases", choices=tuple(CASES), nargs="+", default=["captured_singapore"])
    suite_parser.add_argument("--proceed-anyway", action="store_true")
    suite_parser.add_argument("--dom-controls", action="store_true")
    suite_parser.add_argument("--stylesheets", action="store_true")
    args = parser.parse_args()
    return verify_capture(args) if args.command == "verify" else captured(args) if args.command == "captured" else suite(args) if args.command == "suite" else probe(args)


if __name__ == "__main__":
    raise SystemExit(main())
