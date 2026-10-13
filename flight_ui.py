"""Local browser UI backed by the flight_tools CLI; no web dependencies."""
import argparse
import csv
import io
import json
import math
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from flight_tools import ROOT, load_pool, normalized

LIMITS = ("max_price", "max_stops", "max_duration_hours", "max_layover_hours")


def cli(arguments, timeout=30):
    result = subprocess.run([sys.executable, "-u", str(ROOT / "flight_tools.py"), *arguments],
                            cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if result.returncode not in (0, 1):
        raise ValueError(result.stderr.strip()[-2000:] or "Flight CLI failed")
    return json.loads(result.stdout)


def filter_arguments(values):
    arguments = []
    for key in LIMITS:
        value = values.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError("Limits must be numbers")
        number = float(value)
        if not math.isfinite(number) or number < 0 or (key == "max_price" and number == 0):
            raise ValueError("Limits must be nonnegative; price must be positive")
        if key == "max_stops":
            if not number.is_integer():
                raise ValueError("Connections must be a whole number")
            value = int(number)
        arguments.extend(["--" + key.replace("_", "-"), str(value)])
    return arguments


def search_arguments(values, pool):
    destinations = values.get("destinations")
    if not isinstance(destinations, list) or not destinations or any(not isinstance(d, str) for d in destinations):
        raise ValueError("Select at least one location")
    if set(destinations) - {d["id"] for d in pool}:
        raise ValueError("Unknown location; add it to the picker first")
    mode = values.get("mode", "lite")
    if mode not in ("lite", "deep"):
        raise ValueError("Choose regular or deep search")
    origins = str(values.get("origin", "SFO")).upper().replace(" ", "")
    if not re.fullmatch(r"[A-Z]{3}(,[A-Z]{3})*", origins):
        raise ValueError("Origins must be three-letter airport codes")
    lengths = str(values.get("trip_lengths", "6")).replace(" ", "")
    if not re.fullmatch(r"\d+(,\d+)*", lengths):
        raise ValueError("Trip lengths must be whole days, optionally separated by commas")
    arguments = ["search", "--origin", origins, "--dest", ",".join(destinations),
                 "--start-date", str(values.get("start_date", "")),
                 "--end-date", str(values.get("end_date", "")), "--trip-lengths", lengths, "--mode", mode]
    if mode == "lite":
        step = str(values.get("date_step_days", "5"))
        if not re.fullmatch(r"[1-9]\d*", step):
            raise ValueError("Departure spacing must be a positive whole number")
        arguments.extend(["--date-step-days", step])
    return arguments + filter_arguments(values)


def csv_table(payload):
    """Export the visible matrix, including statuses and complete ISO dates."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)

    def safe(value):
        value = str(value) if value is not None else ""
        return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value

    windows = payload["query"]["date_pairs"]
    writer.writerow(["Destination", "Origin", "Airports", *[f"{d} to {r} (USD)" for d, r in windows],
                     "Cheapest USD", "Departure", "Return departure", "Airline", "Outbound connections",
                     "Outbound duration", "Gateway note", "Checked at", "Booking URL"])
    for row in payload["matrix"]:
        best = row["cheapest"] or {}
        cells = [f'{cell["cheapest"]["price"]:.2f}' + (" (partial)" if cell["status"] == "partial" else "")
                 if cell["cheapest"] else cell["status"] for cell in row["cells"]]
        writer.writerow([safe(v) for v in [row["destination_name"], row["origin"], ",".join(row["airports"]),
                         *cells, best.get("price", ""), best.get("departure_date", ""), best.get("return_date", ""),
                         best.get("airline", ""), best.get("stops", ""), best.get("total_journey_duration", ""),
                         row.get("gateway_note", ""), payload.get("checked_at", ""), best.get("booking_url", "")]])
    return stream.getvalue().encode("utf-8-sig")


class App:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.custom_path = self.data_dir / "locations.json"
        self.lock = threading.RLock()
        self.temp = tempfile.TemporaryDirectory(prefix="flight-ui-")
        self.job = None
        self.process = None
        self.worker = None
        self.csrf = secrets.token_urlsafe(32)

    def pool(self):
        presets = load_pool(ROOT / "flight_destinations.json")
        custom = load_pool(self.custom_path) if self.custom_path.exists() else []
        # A future preset with the same id supersedes a locally added location.
        return presets + [d for d in custom if d["id"] not in {p["id"] for p in presets}]

    def add_location(self, values):
        name = str(values.get("name", "")).strip()
        codes = str(values.get("airports", "")).upper().replace(" ", "").split(",")
        if not name or len(name) > 100 or not normalized(name) or not all(re.fullmatch(r"[A-Z]{3}", code) for code in codes):
            raise ValueError("Enter a location name and comma-separated three-letter airport codes")
        entry = {"id": normalized(name), "name": name, "airports": list(dict.fromkeys(codes))}
        if entry["id"] == "all":
            raise ValueError("The location name 'All' is reserved for whole-pool searches")
        note = str(values.get("gateway_note", "")).strip()
        if note:
            entry["gateway_note"] = note[:500]
        with self.lock:
            pool = self.pool()
            if any(normalized(d["id"]) == entry["id"] or normalized(d["name"]) == entry["id"] for d in pool):
                raise ValueError("This location name already exists")
            custom = load_pool(self.custom_path) if self.custom_path.exists() else []
            self.data_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.custom_path.with_suffix(".tmp")
            temporary.write_text(json.dumps([*custom, entry], indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.custom_path)
        return entry

    def plan(self, values):
        with self.lock:
            pool = self.pool()
        arguments = search_arguments(values, pool)
        # The planning pool is isolated from an in-flight search's pool.
        with tempfile.TemporaryDirectory(dir=self.temp.name) as folder:
            path = Path(folder) / "pool.json"
            path.write_text(json.dumps(pool), encoding="utf-8")
            plan = cli([*arguments, "--pool", str(path), "--dry-run"])
        return plan, arguments, pool

    def start(self, values):
        plan, arguments, pool = self.plan(values)
        with self.lock:
            if self.job and self.job["status"] == "running":
                raise ValueError("A search is running; stop it before starting another")
            folder = Path(self.temp.name) / "search"
            folder.mkdir(exist_ok=True)
            pool_path = folder / "pool.json"
            pool_path.write_text(json.dumps(pool), encoding="utf-8")
            snapshot = folder / "result.json"
            snapshot.unlink(missing_ok=True)
            self.job = {"id": uuid.uuid4().hex, "status": "running", "completed": 0,
                        "total": plan["summary"]["planned_searches"], "started": time.monotonic(),
                        "current": "Fetching the first fare…", "error": None, "cancelled": False,
                        "snapshot": str(snapshot), "result": None, "view": None}
            self.worker = threading.Thread(target=self.run, args=(self.job, [*arguments, "--pool", str(pool_path),
                                           "--output", str(snapshot), "--progress-json"]), daemon=True)
            self.worker.start()
            return self.state()

    def run(self, job, arguments):
        errors = []
        process = None
        try:
            with self.lock:
                if job["cancelled"]:
                    return
                process = subprocess.Popen([sys.executable, "-u", str(ROOT / "flight_tools.py"), *arguments],
                                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                self.process = process
            for line in process.stderr:
                try:
                    event = json.loads(line)
                except ValueError:
                    errors.append(line.strip())
                    errors = errors[-10:]
                    continue
                if event.get("event") == "progress":
                    with self.lock:
                        job["completed"] = event["completed"]
                        job["current"] = f'{event["origin"]} → {event["destination"]} · {event["departure_date"]} to {event["return_date"]}'
            code = process.wait()
            process.stderr.close()
            with self.lock:
                if job["cancelled"]:
                    job["status"] = "cancelled"
                elif code in (0, 1) and Path(job["snapshot"]).exists():
                    job["result"] = json.loads(Path(job["snapshot"]).read_text(encoding="utf-8"))
                    job["view"] = job["result"]
                    job["status"] = "partial" if code == 1 else "done"
                else:
                    job["status"] = "error"
                    job["error"] = "\n".join(errors)[-2000:] or "Flight CLI failed"
        except Exception as error:
            with self.lock:
                job["status"] = "cancelled" if job["cancelled"] else "error"
                job["error"] = str(error)
        finally:
            with self.lock:
                job["finished"] = time.monotonic()
                if job["cancelled"]:
                    job["status"] = "cancelled"
                if self.process is process:
                    self.process = None

    def state(self):
        with self.lock:
            if not self.job:
                return {"status": "idle"}
            job = self.job
            elapsed = job.get("finished", time.monotonic()) - job["started"]
            completed, total = job["completed"], job["total"]
            # Estimate only after an actual lookup; provider retries make it approximate.
            remaining = max(0, elapsed / completed * total - elapsed) if completed else None
            return {key: job[key] for key in ("id", "status", "completed", "total", "current", "error")} | {
                "elapsed_seconds": elapsed, "eta_seconds": remaining if job["status"] == "running" else 0}

    def result(self):
        with self.lock:
            if not self.job or self.job["view"] is None:
                raise ValueError("No completed search yet")
            return self.job["view"]

    def filter(self, values):
        arguments = filter_arguments(values)
        with self.lock:
            if not self.job or self.job["result"] is None or self.job["status"] == "running":
                raise ValueError("Wait for a completed search before filtering")
            # Serializes filtering with replacement of the one active snapshot.
            view = cli(["filter", "--input", self.job["snapshot"], *arguments])
            self.job["view"] = view
            return view

    def cancel(self):
        with self.lock:
            if self.job and self.job["status"] == "running":
                self.job["cancelled"] = True
                if self.process and self.process.poll() is None:
                    self.process.terminate()
        return self.state()

    def close(self):
        self.cancel()
        if self.worker:
            self.worker.join(timeout=5)
        if self.process and self.process.poll() is None:
            self.process.kill()
            if self.worker:
                self.worker.join(timeout=5)
        self.temp.cleanup()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send(self, data, content_type="application/json", status=200, download=None):
        body = json.dumps(data, ensure_ascii=False).encode() if content_type == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(body)

    def allowed_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def do_GET(self):
        if not self.allowed_host():
            self.send({"error": "Use the local 127.0.0.1 address"}, status=403)
            return
        path = urlsplit(self.path).path
        app = self.server.app
        try:
            if path == "/api/destinations":
                self.send(app.pool())
            elif path == "/api/state":
                self.send(app.state())
            elif path == "/api/result":
                self.send(app.result())
            elif path == "/api/export.csv":
                self.send(csv_table(app.result()), "text/csv; charset=utf-8", download="flight-comparison.csv")
            elif path == "/api/export.json":
                self.send(json.dumps(app.result(), indent=2, ensure_ascii=False).encode(), "application/octet-stream", download="flight-results.json")
            elif path in ("/", "/app.js", "/style.css"):
                filename = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[path]
                body = (ROOT / "web" / filename).read_bytes().replace(b"__CSRF_TOKEN__", app.csrf.encode())
                kind = {"/": "text/html", "/app.js": "text/javascript", "/style.css": "text/css"}[path]
                self.send(body, kind + "; charset=utf-8")
            else:
                self.send({"error": "Not found"}, status=404)
        except (ValueError, OSError) as error:
            self.send({"error": str(error)}, status=400)

    def do_POST(self):
        app = self.server.app
        origin = f"http://127.0.0.1:{self.server.server_port}"
        if not self.allowed_host() or self.headers.get("Origin") not in (None, origin) or not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), app.csrf):
            self.send({"error": "Invalid local request"}, status=403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("Invalid request size")
            values = json.loads(self.rfile.read(length))
            if not isinstance(values, dict):
                raise ValueError("Expected a JSON object")
            path = urlsplit(self.path).path
            if path == "/api/plan":
                plan, _, _ = app.plan(values)
                self.send({"total": plan["summary"]["planned_searches"], "windows": len(plan["query"]["date_pairs"])})
            elif path == "/api/search":
                self.send(app.start(values))
            elif path == "/api/locations":
                self.send(app.add_location(values), status=201)
            elif path == "/api/filter":
                self.send(app.filter(values))
            elif path == "/api/cancel":
                self.send(app.cancel())
            else:
                self.send({"error": "Not found"}, status=404)
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            self.send({"error": str(error)}, status=400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="Local port; 0 selects an available port")
    parser.add_argument("--no-browser", action="store_true")
    default_data = Path.home() / ("Library/Application Support/Travel Agent" if sys.platform == "darwin" else ".local/share/travel-agent")
    parser.add_argument("--data-dir", type=Path, default=default_data, help="Local storage for added destinations")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    app = App(args.data_dir)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as error:
        app.close()
        parser.error(f"{error}; try --port 0")
    server.app = app
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Travel Agent: {url}\nKeep this terminal open. Press Control-C to stop.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()
