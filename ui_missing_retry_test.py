"""Headless UI/CLI regression with an isolated fixture provider; no live fares."""
import argparse
import copy
import json
import os
import tempfile
import threading
from pathlib import Path

from flight_tools import ROOT
from flight_ui import App, Handler, ThreadingHTTPServer
from test_missing_retry import snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=["chromium", "chrome"], default="chromium")
    parser.add_argument("--output", default="/tmp/flight-ui-missing-retry-test")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright, expect

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {"provider": "fixture", "live_price_recovery_verified": False}
    with tempfile.TemporaryDirectory(prefix="retry-ui-test-") as folder:
        app = App(Path(folder) / "data")
        baseline = snapshot()
        baseline["source_warnings"].append({**baseline["source_warnings"][0], "destination": "OGG", "airlines": ["United"]})
        def install():
            path = Path(app.temp.name) / "baseline.json"
            path.write_text(json.dumps(baseline))
            app.job = {"id": "fixture", "kind": "search", "status": "done", "completed": 2, "total": 2,
                       "current": "Fixture search complete", "error": None, "cancelled": False,
                       "started": 0, "finished": 1, "snapshot": str(path), "result": copy.deepcopy(baseline),
                       "view": copy.deepcopy(baseline), "query": baseline["query"]}
        install()
        # Patch only child CLI processes in this isolated test server. The real
        # retry command, HTTP API, worker, exports and frontend still execute.
        Path(folder, "sitecustomize.py").write_text(f'''
import sys
sys.path.insert(0, {str(ROOT)!r})
if sys.argv[0].endswith("flight_tools.py"):
    import time
    import flight_scanner
    def lookup(origin, destination, departure, returning, **options):
        options["browser_callback"]()
        time.sleep(4)
        carrier = "Singapore Airlines" if destination == "CUN" else "United"
        price = 400 if destination == "CUN" else 350
        options["browser_attempts"].append({{"origin": origin, "destination": destination,
            "departure_date": departure, "return_date": returning, "status": "recovered",
            "recovered": 1, "engine": options["browser_engine"], "elapsed_seconds": 4}})
        return [{{"origin": origin, "destination": destination, "departure_date": departure,
            "return_date": returning, "price": price, "airline": carrier, "stops": 0,
            "legs": [], "layovers": [], "total_journey_duration": "5h 0m",
            "booking_url": "https://www.google.com/travel/flights",
            "price_source": "google_flights_browser", "price_checked_at": "2026-10-13T12:01:00+00:00"}}]
    flight_scanner.scan_route = lookup
''')
        previous = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = folder + (os.pathsep + previous if previous else "")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.app = app
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, **({"channel": "chrome"} if args.browser == "chrome" else {}))
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1050})
                    page.goto(f"http://127.0.0.1:{server.server_port}/")
                    expect(page.locator("#results")).to_be_visible()
                    page.locator("#source-warnings > summary").click()
                    page.screenshot(path=str(output / "missing-prices.png"), full_page=True)
                    page.locator("#duration").fill("30")
                    page.locator(".advanced").evaluate("element => element.open = true")
                    page.locator("#browser-engine").select_option("native-chrome")
                    page.locator("#retry-missing").click()
                    expect(page.locator("#progress-title")).to_have_text("Retrieving missing prices")
                    expect(page.locator("#progress")).to_be_visible()
                    expect(page.locator("#eta")).to_contain_text("About")
                    expect(page.locator("#retry-missing")).to_be_disabled()
                    expect(page.locator("#filter-airlines")).to_be_disabled()
                    expect(page.locator("#results")).to_be_visible()
                    expect(page.locator("#progress-count")).to_contain_text("1 / 2", timeout=15000)
                    expect(page.locator("#eta")).to_contain_text("About")
                    page.screenshot(path=str(output / "retry-progress.png"), full_page=True)
                    page.reload()
                    expect(page.locator("#results")).to_be_visible()
                    expect(page.locator("#progress-title")).to_have_text("Browser retries complete", timeout=15000)
                    result = app.result()
                    assert result["query"] == baseline["query"]
                    assert sorted(f["price"] for f in result["raw_flight_deals"]) == [350, 400, 500]
                    assert result["source_warnings"] == []
                    assert result["cheapest"]["price"] == 350
                    expect(page.locator("#best-fare")).to_contain_text("$350")
                    expect(page.locator("#matrix")).to_contain_text("$350")
                    assert result["cheapest_by_destination"][0]["price"] == 350
                    assert all(a["engine"] == "native-chrome" for a in result["browser_attempts"])
                    assert all(a["departure_date"] == "2027-01-01" and a["return_date"] == "2027-01-06" for a in result["browser_attempts"])
                    with page.expect_download() as downloaded:
                        page.get_by_role("link", name="Save CSV").click()
                    downloaded.value.save_as(str(output / "merged.csv"))
                    csv_text = (output / "merged.csv").read_text(encoding="utf-8-sig")
                    assert "400.00" in csv_text and "350.00" in csv_text
                    page.screenshot(path=str(output / "merged-results.png"), full_page=True)
                    report["complete_retry"] = "passed"

                    app.worker.join(timeout=2)
                    install()
                    page.reload()
                    expect(page.locator("#results")).to_be_visible()
                    page.locator("#source-warnings > summary").click()
                    page.locator("#retry-missing").click()
                    expect(page.locator("#progress-count")).to_contain_text("1 / 2", timeout=15000)
                    page.locator("#stop-search").click()
                    expect(page.locator("#progress-title")).to_have_text("Browser retries stopped", timeout=10000)
                    assert sorted(f["price"] for f in app.result()["raw_flight_deals"]) == [400, 500]
                    page.locator("#reset-filters").click()
                    expect(page.locator("#error")).to_be_hidden()
                    report["cancel_preserves_incremental_quotes"] = "passed"
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            app.close()
            if previous is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = previous
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
