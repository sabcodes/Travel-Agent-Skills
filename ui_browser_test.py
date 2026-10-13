"""Opt-in live Playwright regression: add Dhaka, then verify five- and thirty-day searches."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit


def check_duration_change(page, args, report, expect):
    expect(page.locator("#results")).to_be_visible()
    expect(page.locator("#result-meta")).to_contain_text("5-day trips")
    page.locator("#duration").fill("30")
    expect(page.locator("#mode-help")).to_contain_text("30-day trips")
    expect(page.locator("#mode-help")).to_contain_text("departures every 30 days")
    expect(page.locator("#settings-changed")).to_be_visible()
    expect(page.locator("#settings-changed")).to_contain_text("previous 5-day search")
    expect(page.locator("#matrix")).to_contain_text("Jan 1 → Jan 5")
    page.screenshot(path=str(args.output_dir / "settings-changed.png"), full_page=True)
    if not page.locator(".advanced").evaluate("element => element.open"):
        page.locator(".advanced > summary").click()
    page.locator("#preview").click()
    expect(page.locator("#plan")).to_have_text("1 search · 1 date window")
    page.locator(".advanced > summary").click()
    with page.expect_response(lambda response: urlsplit(response.url).path == "/api/search") as response:
        page.locator("#search-button").click()
    assert response.value.request.post_data_json["trip_lengths"] == "30"
    expect(page.locator("#result-meta")).to_contain_text("30-day trips", timeout=180000)
    expect(page.locator("#settings-changed")).not_to_be_visible()
    expect(page.locator("#matrix")).to_contain_text("Jan 1 → Jan 30")
    payload = page.request.get(args.url + "/api/result").json()
    warnings = payload.get("source_warnings", [])
    if warnings:
        expect(page.locator("#unpriced-notice")).to_be_visible()
        for carrier in {name for warning in warnings for name in warning["airlines"]}:
            expect(page.locator("#unpriced-notice")).to_contain_text(carrier)
        expect(page.locator("#source-warnings")).to_be_visible()
        if any("Singapore Airlines" in warning["airlines"] for warning in warnings):
            expect(page.locator("#airline-options option[value='Singapore Airlines']")).to_have_count(1)
        report["checks"].append("unpriced carriers have a visible notice and airline suggestions")
    assert payload["query"]["trip_lengths"] == [30]
    assert payload["query"]["date_step_days"] == 30
    assert payload["query"]["date_pairs"] == [["2027-01-01", "2027-01-30"]]
    assert not payload["source_errors"]
    report["duration_change"] = {"query": payload["query"], "summary": payload["summary"], "source_warnings": warnings}
    report["checks"].append("editing 5 to 30 marks previous results; submitted request and table use Jan 1–30")
    (args.output_dir / "dhaka-30-day-results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    page.reload()
    expect(page.locator("#duration")).to_have_value("30")
    expect(page.locator("#result-meta")).to_contain_text("30-day trips")
    page.screenshot(path=str(args.output_dir / "30-day-results.png"), full_page=True)
    print("Duration change passed: 30-day request and Jan 1–30 results", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize seven live SFO–DAC lookups and persist the added UI location")
    parser.add_argument("--duration-change-only", action="store_true", help="Reuse a completed five-day Dhaka search and fetch only the one thirty-day lookup")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--browser", choices=["chromium", "chrome"], default="chromium")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True, help="Screenshot/report/download folder outside the repository")
    args = parser.parse_args()
    if not args.live:
        parser.error("This test adds a local location and fetches fares. Pass --live to run it.")
    if urlsplit(args.url).hostname != "127.0.0.1":
        parser.error("Use the local app's 127.0.0.1 URL")
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError:
        parser.error("Install Playwright for this optional test; see README Browser regression test")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"checks": [], "source_errors": []}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed, **({"channel": "chrome"} if args.browser == "chrome" else {}))
        page = browser.new_page(viewport={"width": 662, "height": 850}, accept_downloads=True)
        script_errors = []
        live_requests = []
        page.on("pageerror", lambda error: script_errors.append(str(error)))
        page.on("request", lambda request: live_requests.append(request.post_data_json) if urlsplit(request.url).path == "/api/search" else None)
        try:
            page.goto(args.url)
            expect(page.locator("#locations-summary")).not_to_have_text("Choose locations")
            if args.duration_change_only:
                expect(page.locator("#locations-summary")).to_have_text("Dhaka, Bangladesh")
                check_duration_change(page, args, report, expect)
                assert not script_errors, f"Browser errors: {script_errors}"
                return
            page.locator(".advanced > summary").click()
            page.locator("#locations-picker > summary").click()
            page.locator("#clear-locations").click()
            page.locator("#locations-picker > summary").click()
            for identifier in ("duration", "start-date", "end-date", "origin"):
                page.locator("#" + identifier).fill("")
            page.locator("#search-button").click()
            expect(page.locator("#error")).to_contain_text("Please fill out the required fields")
            for identifier in ("duration", "start-date", "end-date", "origin"):
                expect(page.locator("#" + identifier)).to_have_attribute("aria-invalid", "true")
            expect(page.locator("#locations-picker > summary")).to_have_attribute("aria-invalid", "true")
            assert not live_requests, "Invalid submission must not start a search"
            page.screenshot(path=str(args.output_dir / "validation.png"), full_page=True)
            report["checks"].append("required-field message and highlights; no search submitted")
            print("Required-field validation passed", flush=True)

            page.locator("#duration").fill("5")
            page.locator("#start-date").fill("2027-01-01")
            page.locator("#end-date").fill("2027-01-31")
            page.locator("#origin").fill("SFO")
            page.locator("#date-step").fill("")
            page.locator("#search-airlines").fill("")
            assert page.locator("#extra-lengths").count() == 0
            page.locator("#locations-picker > summary").click()
            page.locator("#location-search").fill("Dhaka")
            location = page.locator('input[value="dhaka_bangladesh"]')
            if location.count():
                location.check()
                page.locator("#locations-picker > summary").click()
            else:
                page.locator("#locations-picker > summary").click()
                page.locator("#add-location").click()
                page.locator("#new-name").fill("Dhaka, Bangladesh")
                page.locator("#new-airports").fill("DAC")
                page.locator("#save-location").click()
                expect(page.locator("#location-dialog")).not_to_be_visible()
            expect(page.locator("#locations-summary")).to_have_text("Dhaka, Bangladesh")
            report["checks"].append("Dhaka added/selected through the location UI")

            page.locator('input[name="mode"][value="deep"]').check()
            page.locator("#date-step").fill("3")
            page.locator("#preview").click()
            expect(page.locator("#plan")).to_have_text("9 searches · 9 date windows")
            report["checks"].append("deep three-day interval previews Jan 1, 4, 7…")
            page.locator('input[name="mode"][value="lite"]').check()
            page.locator("#date-step").fill("")
            page.locator("#preview").click()
            expect(page.locator("#plan")).to_have_text("6 searches · 6 date windows")
            page.locator(".advanced > summary").click()
            page.locator("#search-button").click()
            expect(page.locator("#progress-section")).to_be_visible()
            box = page.locator("#progress").bounding_box()
            assert box and 0 <= box["y"] and box["y"] + box["height"] <= 850, "Progress must be in the viewport"
            expect(page.locator("#progress-count")).to_contain_text("1 / 6", timeout=30000)
            expect(page.locator("#eta")).to_contain_text("left")
            page.screenshot(path=str(args.output_dir / "progress.png"))
            report["checks"].append("visible progress bar and measured ETA while live search runs")
            print("Progress and ETA are visible; waiting for six live lookups", flush=True)
            expect(page.locator("#results")).to_be_visible(timeout=180000)
            payload = page.request.get(args.url + "/api/result").json()
            report["source_errors"] = payload["source_errors"]
            report["summary"] = payload["summary"]
            report["query"] = payload["query"]
            assert len(live_requests) == 1 and live_requests[0]["trip_lengths"] == "5"
            assert payload["query"]["mode"] == "lite" and payload["query"]["date_step_days"] == 5
            assert payload["query"]["date_pairs"] == [[f"2027-01-{day:02d}", f"2027-01-{day+4:02d}"] for day in range(1, 27, 5)]
            assert payload["query"]["destinations"][0]["airports"] == ["DAC"]
            assert not payload["source_errors"], "Provider errors are recorded in report.json"
            assert payload["flight_deals"], "Expected live fares; see report.json"
            report["checks"].append("six five-day January windows, SFO to DAC, fares returned")

            airline = payload["cheapest"]["airline"].lower()
            page.locator("#filter-airlines").fill(airline)
            with page.expect_response(lambda response: urlsplit(response.url).path == "/api/filter") as response:
                page.locator("#apply-filters").click()
            filtered = response.value.json()
            carriers = {name.strip() for name in airline.split(",")}
            assert filtered["flight_deals"] and all({name.strip().lower() for name in fare["airline"].split(",")}.issubset(carriers) for fare in filtered["flight_deals"])
            assert filtered["checked_at"] == payload["checked_at"]
            with page.expect_response(lambda response: urlsplit(response.url).path == "/api/filter"):
                page.locator("#reset-filters").click()
            expect(page.locator("#filter-airlines")).to_have_value("")
            report["checks"].append("offline airline filter and clear; quote time unchanged")
            page.locator(".advanced > summary").click()
            page.locator("#search-airlines").fill(airline)
            page.locator("#preview").click()
            expect(page.locator("#plan")).to_have_text("6 searches · 6 date windows")
            page.locator("#search-airlines").fill("")
            report["checks"].append("advanced airline filter accepted without fetching new fares")

            for extension in ("csv", "json"):
                with page.expect_download() as download:
                    page.locator(f'a[href="/api/export.{extension}"]').click()
                download.value.save_as(str(args.output_dir / f"dhaka-results.{extension}"))
            page.reload()
            expect(page.locator("#locations-summary")).to_have_text("Dhaka, Bangladesh")
            expect(page.locator("#duration")).to_have_value("5")
            expect(page.locator("#start-date")).to_have_value("2027-01-01")
            expect(page.locator("#results")).to_be_visible()
            page.screenshot(path=str(args.output_dir / "results.png"), full_page=True)
            assert not script_errors, f"Browser errors: {script_errors}"
            report["checks"].append("CSV/JSON downloads and state restored after refresh")
            report["cheapest"] = payload["cheapest"]
            check_duration_change(page, args, report, expect)
            print(f'Passed {len(report["checks"])} browser checks; {payload["summary"]["total_flight_deals"]} fares', flush=True)
        finally:
            (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            browser.close()


if __name__ == "__main__":
    main()
