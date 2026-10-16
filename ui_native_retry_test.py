"""Opt-in live UI regression: add Dhaka, search, recover Singapore and export."""
import argparse
import copy
import time
import json
from pathlib import Path
import tempfile
import threading

from flight_ui import App, Handler, ThreadingHTTPServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error('Pass --live to authorize SFO/DAC provider requests and a disposable Chrome window')
    from playwright.sync_api import sync_playwright, expect
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'live_price_recovery_verified': False}
    with tempfile.TemporaryDirectory(prefix='native-ui-test-') as folder:
        app = App(Path(folder))
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.app = app
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, channel='chrome')
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1050}, accept_downloads=True)
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.locator('#add-location').click()
                    page.locator('#new-name').fill('Dhaka, Bangladesh')
                    page.locator('#new-airports').fill('DAC')
                    page.locator('#location-form button[type=submit]').click()
                    expect(page.locator('#location-dialog')).not_to_be_visible()
                    page.locator('#locations-picker > summary').click()
                    page.locator('#clear-locations').click()
                    page.locator('#location-search').fill('Dhaka')
                    page.locator('input[value=dhaka_bangladesh]').check()
                    page.locator('#locations-picker > summary').click()
                    page.locator('#duration').fill('5')
                    page.locator('#start-date').fill('2027-01-12')
                    page.locator('#end-date').fill('2027-01-16')
                    expect(page.locator('#browser-engine')).to_have_value('native-chrome')
                    page.locator('.advanced > summary').click()
                    page.locator('#search-max-stops').select_option('1')
                    page.locator('.advanced > summary').click()
                    page.locator('#search-button').click()
                    expect(page.locator('#progress')).to_be_visible()
                    expect(page.locator('#results')).to_be_visible(timeout=120000)
                    initial = app.result()
                    assert not initial['source_errors'], initial['source_errors']
                    assert initial['query']['date_pairs'] == [['2027-01-12', '2027-01-16']]
                    assert initial['query']['mode'] == 'lite'
                    assert initial['query']['filters']['max_stops'] == 1
                    assert any('Singapore Airlines' in w['airlines'] for w in initial['source_warnings'])
                    (args.output / 'initial.json').write_text(json.dumps(initial, indent=2))
                    report['checks'].append('added Dhaka and completed live five-day regular search')
                    page.locator('#filter-airlines').fill('Singapore Airlines')
                    page.locator('#apply-filters').click()
                    expect(page.locator('#retry-missing-count')).to_have_text('1 saved route/date check')
                    if not page.locator('#source-warnings').evaluate('e=>e.open'):
                        page.locator('#source-warnings > summary').click()
                    page.locator('#retry-missing').click()
                    expect(page.locator('#progress-title')).to_have_text('Retrieving missing prices')
                    expect(page.locator('#progress')).to_be_visible()
                    expect(page.locator('#eta')).to_contain_text('About')
                    page.screenshot(path=str(args.output / 'progress.png'), full_page=True)
                    expect(page.locator('#progress-title')).to_have_text('Browser retries complete', timeout=120000)
                    merged = app.result()
                    (args.output / 'merged.json').write_text(json.dumps(merged, indent=2))
                    recovered = [f for f in merged['flight_deals'] if f.get('price_source') == 'google_flights_native_chrome']
                    assert recovered, merged['browser_attempts']
                    assert all(f['airline'] == 'Singapore Airlines' for f in recovered)
                    assert len(merged['raw_flight_deals']) >= len(initial['raw_flight_deals'])
                    assert merged['cheapest']['price'] == min(f['price'] for f in merged['flight_deals'])
                    expect(page.locator('#best-fare')).to_contain_text('Singapore Airlines')
                    expect(page.locator('#best-fare')).to_contain_text('browser quote')
                    expect(page.locator('#matrix')).to_contain_text(f"${merged['cheapest']['price']:,.0f}")
                    assert merged['cheapest_by_destination'][0]['price'] == merged['cheapest']['price']
                    report['checks'].append('button recovers real Singapore prices and recomputes filtered minima')
                    page.reload()
                    expect(page.locator('#filter-airlines')).to_have_value('Singapore Airlines')
                    expect(page.locator('#best-fare')).to_contain_text('Singapore Airlines')
                    for extension in ('csv', 'json'):
                        with page.expect_download() as downloaded:
                            page.locator(f'a[href="/api/export.{extension}"]').click()
                        downloaded.value.save_as(str(args.output / ('recovered.' + extension)))
                    assert 'google_flights_native_chrome' in (args.output / 'recovered.csv').read_text(encoding='utf-8-sig')
                    page.locator('#fares-summary').click()
                    page.screenshot(path=str(args.output / 'recovered-results.png'), full_page=True)
                    page.locator('#reset-filters').click()
                    expect(page.locator('#filter-airlines')).to_have_value('')
                    expect(page.locator('#best-fare')).to_contain_text(merged['query']['origins'][0])
                    assert len(app.result()['raw_flight_deals']) == len(merged['raw_flight_deals'])
                    # Reuse the real initial snapshot to stop a new native check
                    # while its owned Chrome window is open.
                    app.worker.join(timeout=3)
                    restored = copy.deepcopy(initial)
                    restored['applied_filters'] = {**restored['query']['filters'], 'airlines': ['Singapore Airlines']}
                    snapshot = Path(app.temp.name) / 'cancel-seed.json'
                    snapshot.write_text(json.dumps(restored))
                    with app.lock:
                        app.job = {'id': 'live-cancel-check', 'kind': 'search', 'status': 'done',
                            'completed': 1, 'total': 1, 'started': time.monotonic(), 'finished': time.monotonic(),
                            'current': 'Ready', 'error': None, 'cancelled': False,
                            'snapshot': str(snapshot), 'result': restored, 'view': restored, 'query': restored['query']}
                    page.reload()
                    expect(page.locator('#results')).to_be_visible()
                    page.locator('#source-warnings > summary').click()
                    page.locator('#retry-missing').click()
                    expect(page.locator('#current-route')).to_contain_text('Best (slower)', timeout=20000)
                    page.locator('#stop-search').click()
                    expect(page.locator('#progress-title')).to_have_text('Browser retries stopped', timeout=15000)
                    assert app.result()['raw_flight_deals'] == initial['raw_flight_deals']
                    assert app.process is None or app.process.poll() is not None
                    report['checks'].append('cancelled a live native Chrome lookup and retained original fares')
                    assert not errors, errors
                    report.update(live_price_recovery_verified=True, recovered_quotes=len(recovered),
                                  lowest_singapore_quote=min(f['price'] for f in recovered), browser_attempts=merged['browser_attempts'])
                    report['checks'].append('refresh, airline clear, provenance and CSV/JSON exports')
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)
            app.close()
            (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
