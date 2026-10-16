"""Deterministic, bounded missing-price retrieval in disposable native Chrome.

No personal profiles, login, Node runtime, or browser downloads are required.
Only final individual Cheapest rows backed by matching shopping data qualify.
"""
import base64
import copy
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs
from urllib.request import urlopen

from flight_browser import _signature, apply_browser_prices, shopping_response_flights


def chrome_binary():
    candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    if sys.platform == "win32":
        candidates = [str(Path(os.environ.get(root, "")) / "Google/Chrome/Application/chrome.exe")
                      for root in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    return next((path for path in candidates if Path(path).is_file()), None) or shutil.which("google-chrome")


def matching_request(post_data, query, codes):
    """Require both routes, dates and airline restrictions, plus live stop limit."""
    try:
        request = json.loads(json.loads(parse_qs(post_data)["f.req"][0])[1])
        segments = request[1][13]
        if len(segments) != 2 or request[1][2] != 1 or request[1][6] != [1, 0, 0, 0]:
            return False
        for segment, flight in zip(segments, query.flight_data):
            stops = flight.max_stops + 1 if flight.HasField("max_stops") else 0
            if (segment[6] != flight.date or set(segment[4] or []) != set(codes) or
                segment[0] != [[[flight.from_airport.airport, 0]]] or
                segment[1] != [[[flight.to_airport.airport, 0]]] or segment[3] != stops):
                return False
        return query.currency == "USD" and query.get_trip_type() == "round-trip"
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return False


def verified_rows(rows, state, carriers):
    """Header-only, stale, mixed-cabin and ambiguous prices stay unavailable."""
    if (state.get("loading") or re.search(r"Oops, something went wrong|unusual traffic|not a robot", state.get("body", ""), re.I) or
        not any(tab.get("selected") == "true" and "Cheapest" in tab.get("label", "") for tab in state.get("tabs", []))):
        return []
    labels = [label for label in state.get("labels", [])
              if not re.search(r"premium economy|business|first class", label, re.I)]
    accepted = {}
    for row in rows:
        if not row.flights or not set(row.airlines).issubset(carriers):
            continue
        candidate = copy.deepcopy(row)
        candidate.price = None
        if apply_browser_prices([candidate], labels) and candidate.price == row.price:
            candidate.price_source = "google_flights_native_chrome"
            accepted[(_signature(candidate), candidate.price)] = candidate
    return list(accepted.values())


class ChromeSession:
    """Synchronous CDP transport with a deadline for commands and event reads."""
    def __init__(self, deadline):
        self.deadline, self.next_id = deadline, 0
        self.replies = {}
        self.on_event = lambda message: None
        self.websocket = self.process = self.profile = self.previous_signal = None

    def remaining(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("Chrome retry timed out")
        return left

    def __enter__(self):
        from curl_cffi.requests import WebSocket
        binary = chrome_binary()
        if not binary:
            raise FileNotFoundError("Install Google Chrome")
        self.profile = tempfile.TemporaryDirectory(prefix="travel-agent-chrome-")
        if threading.current_thread() is threading.main_thread():
            self.previous_signal = signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
        try:
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            self.process = subprocess.Popen([binary, f"--user-data-dir={self.profile.name}",
                f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
                "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            startup = min(self.deadline, time.monotonic() + 15)
            while time.monotonic() < startup:
                if self.process.poll() is not None:
                    raise RuntimeError("Chrome exited during startup")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=min(1, self.remaining())) as response:
                        target = next((tab for tab in json.load(response) if tab["type"] == "page"), None)
                    if target:
                        self.websocket = WebSocket()
                        self.websocket.connect(target["webSocketDebuggerUrl"], timeout=min(5, self.remaining()))
                        return self
                except OSError:
                    pass
                time.sleep(min(.1, self.remaining()))
            raise TimeoutError("Chrome startup timed out")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def send(self, method, params=None):
        from curl_cffi import CurlWsFlag
        self.remaining()
        self.next_id += 1
        self.websocket.send(json.dumps({"id": self.next_id, "method": method, "params": params or {}}), flags=CurlWsFlag.TEXT)
        return self.next_id

    def pump(self, wait=.1):
        from curl_cffi import CurlError, CurlECode, CurlInfo, CurlWsFlag
        end, chunks = min(self.deadline, time.monotonic() + wait), []
        while True:
            self.remaining()
            try:
                chunk, frame = self.websocket.recv_fragment()
                if frame.flags & CurlWsFlag.CLOSE:
                    raise RuntimeError("Chrome connection closed")
                if frame.flags & (CurlWsFlag.PING | CurlWsFlag.PONG):
                    continue
                chunks.append(chunk)
                if frame.bytesleft == 0 and not frame.flags & CurlWsFlag.CONT:
                    message = json.loads(b"".join(chunks))
                    if "id" in message:
                        self.replies[message["id"]] = message
                    else:
                        self.on_event(message)
                    return
            except CurlError as error:
                if error.code != CurlECode.AGAIN:
                    raise
                if time.monotonic() >= end and not chunks:
                    return
                select.select([self.websocket.curl.getinfo(CurlInfo.ACTIVESOCKET)], [], [], min(.1, self.remaining()))

    def call(self, method, params=None):
        identifier = self.send(method, params)
        limit = min(self.deadline, time.monotonic() + 10)
        while identifier not in self.replies:
            if time.monotonic() >= limit:
                raise TimeoutError("Chrome command timed out")
            self.pump()
        reply = self.replies.pop(identifier)
        if "error" in reply:
            raise RuntimeError("Chrome command failed")
        return reply.get("result", {})

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        if result.get("exceptionDetails"):
            raise RuntimeError("Expected Google Flights control is unavailable")
        return result.get("result", {}).get("value")

    def pause(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump(min(.1, end - time.monotonic()))

    def __exit__(self, *_):
        try:
            if self.websocket:
                self.websocket.terminate()
        finally:
            try:
                if self.process and self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
            finally:
                try:
                    if self.profile:
                        self.profile.cleanup()
                finally:
                    if self.previous_signal is not None:
                        signal.signal(signal.SIGTERM, self.previous_signal)


STATE = """(() => ({body:document.body?.innerText || '',
loading:[...document.querySelectorAll('[role=progressbar],[aria-busy=true]')].some(e=>{const r=e.getBoundingClientRect();return r.width>5 && r.height>5 && getComputedStyle(e).visibility!=='hidden';}),
labels:[...document.querySelectorAll('li [role=link][aria-label]')].map(e=>e.getAttribute('aria-label')),
tabs:[...document.querySelectorAll('[role=tab]')].map(e=>({label:e.innerText,selected:e.getAttribute('aria-selected')}))}))()"""
NAME = """e=>e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') || '').split(' ').map(id=>document.getElementById(id)?.innerText || '').join(' ').trim() || [...(e.labels || [])].map(n=>n.innerText).join(' ').trim() || e.innerText"""


def fill_native_prices(query, items, *, airlines=None, timeout_seconds=90, browser_only=False, progress=None):
    report = {"status": "unavailable", "engine": "native-chrome", "recovered": 0, "stage": "launch", "sections_checked": []}
    started = time.monotonic()
    selected = {name.casefold() for name in airlines} if airlines else None
    carriers = {name for item in items if item.price is None and
                (selected is None or {name.casefold() for name in item.airlines}.issubset(selected)) for name in item.airlines}
    def stage(name):
        report["stage"] = name
        if progress:
            progress(name)
    try:
        if query.currency != "USD" or query.get_trip_type() != "round-trip" or not carriers:
            raise ValueError("A USD round-trip missing-price query is required")
        browser_query = copy.deepcopy(query)
        for flight in browser_query.flight_data:
            del flight.airlines[:]
        requests, bodies, rows, codes_by_name = {}, {}, [], {}
        def read_payload(text):
            from compare_flight_hars import framed_payloads
            for payload in framed_payloads(text):
                if isinstance(payload, list) and len(payload) > 7 and payload[7]:
                    for code, name in payload[7][1][1]:
                        codes_by_name[name] = code
        with ChromeSession(started + timeout_seconds) as chrome:
            def event(message):
                params = message.get("params", {})
                identifier = params.get("requestId")
                if message.get("method") == "Network.requestWillBeSent":
                    request = params["request"]
                    if "FlightsFrontendService/GetShoppingResults" in request["url"]:
                        requests[identifier] = request.get("postData", "")
                elif message.get("method") == "Network.loadingFinished" and identifier in requests:
                    bodies[chrome.send("Network.getResponseBody", {"requestId": identifier})] = requests.pop(identifier)
            chrome.on_event = event
            def drain():
                for identifier in list(bodies):
                    if identifier not in chrome.replies:
                        continue
                    post_data = bodies.pop(identifier)
                    reply = chrome.replies.pop(identifier)
                    try:
                        body = reply["result"]["body"]
                        if reply["result"].get("base64Encoded"):
                            body = base64.b64decode(body).decode()
                        read_payload(body)
                        codes = [codes_by_name[name] for name in carriers if name in codes_by_name]
                        if len(codes) == len(carriers) and matching_request(post_data, query, codes):
                            rows.extend(shopping_response_flights(body, query, carriers))
                    except (KeyError, IndexError, TypeError, ValueError):
                        report["response_errors"] = report.get("response_errors", 0) + 1
            def settled():
                end = min(chrome.deadline, time.monotonic() + 25)
                previous, stable = None, 0
                while time.monotonic() < end:
                    chrome.pause(.25)
                    drain()
                    state = chrome.evaluate(STATE)
                    if re.search(r"Oops, something went wrong|unusual traffic|not a robot", state["body"], re.I):
                        raise RuntimeError("Google could not complete this search")
                    ready = re.search(r"departing flights", state["body"], re.I) and re.search(r"\d+ results returned|No results returned", state["body"]) and not state["loading"]
                    key = json.dumps(state["labels"])
                    stable = stable + 1 if ready and key == previous else 0
                    previous = key
                    if stable >= 3:
                        return state
                raise TimeoutError("Google results did not finish loading")
            def click(role, pattern, optional=False):
                selectors = f"[role={role}]" + (",button" if role == "button" else ",input[type=checkbox]" if role == "checkbox" else "")
                clicked = chrome.evaluate(f"""(() => {{const name={NAME}; const e=[...document.querySelectorAll({json.dumps(selectors)})].find(e=>new RegExp({json.dumps(pattern)}).test(name(e)) && !e.closest('[aria-hidden=true]')); if(!e)return false; e.scrollIntoView({{block:'center'}}); e.click(); return true;}})()""")
                if not clicked and not optional:
                    raise RuntimeError("Expected Google Flights control is unavailable")
                return clicked
            chrome.call("Network.enable")
            chrome.call("Page.enable")
            stage("best")
            chrome.call("Page.navigate", {"url": browser_query.url() + "&gl=US&hl=en-US"})
            settled()
            stage("cheapest")
            click("tab", "Cheapest")
            chrome.pause(1)
            settled()
            report["sections_checked"].append("cheapest")
            if click("button", "^View more flights$", optional=True):
                settled()
                report["sections_checked"].append("expanded_cheapest")
            stage("airline_filter")
            click("button", "^Airlines(?:,|$)")
            chrome.pause(.4)
            if chrome.evaluate("document.querySelector('[role=switch][aria-label=\"Select all airlines\"]')?.getAttribute('aria-checked')") == "true":
                click("switch", "^Select all airlines$")
                chrome.pause(.4)
            for carrier in sorted(carriers):
                chrome.evaluate(f"""(() => {{const name={NAME}; const e=[...document.querySelectorAll('input[type=checkbox]')].find(e=>name(e)==={json.dumps(carrier)}); if(!e)throw new Error('Missing airline'); if(!e.checked)e.click();}})()""")
            for kind in ("keyDown", "keyUp"):
                chrome.call("Input.dispatchKeyEvent", {"type": kind, "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
            chrome.pause(1.5)
            settled()
            stage("verify_prices")
            chrome.pause(5)
            state = settled()
            drain()
            accepted = verified_rows(rows, state, carriers)
            chrome.pause(2)
            final = settled()
            drain()
            keys = {(_signature(row), row.price) for row in verified_rows(rows, final, carriers)}
            accepted = [row for row in accepted if (_signature(row), row.price) in keys]
            observed = {_signature(row) for row in accepted}
            resolved = {name for row in accepted for name in row.airlines}
            items[:] = [item for item in items if item.price is not None or
                        (item.flights and _signature(item) not in observed) or
                        (not item.flights and not set(item.airlines).issubset(resolved))]
            known = {(_signature(item), item.price) for item in items if item.flights}
            items.extend(row for row in accepted if (_signature(row), row.price) not in known)
            report.update(status="recovered" if accepted else "price_unavailable", recovered=len(accepted),
                          message="Verified individual Cheapest quotes." if accepted else "Google did not provide matching individual prices; saved fares were retained.")
    except Exception as error:
        report["failure_kind"] = "timeout" if isinstance(error, TimeoutError) else "setup" if isinstance(error, (ImportError, FileNotFoundError)) else "provider"
        report["message"] = ("Install Google Chrome for native retries." if isinstance(error, FileNotFoundError) else
                             "Chrome retry timed out; saved fares were retained." if isinstance(error, TimeoutError) else
                             "Chrome could not verify individual prices; saved fares were retained.")
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return report
