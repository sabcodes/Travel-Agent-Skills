# Local flight UI

## Agreed scope

A local browser app with a double-click Mac launcher after one-time Python setup. It supports Intel and Apple Silicon through the installed Python environment. No Node, React build, Electron runtime, hosted service, or travel-account login is required.

The server runs the checked-in `flight_tools.py` CLI as a subprocess using the same Python interpreter. Date generation, live fetching, filters, ranking, and matrix generation remain in the CLI. Live searches remain sequential to preserve the existing provider behavior.

## Search screen

- Searchable multi-select dropdown containing every preset, with select-all and clear actions.
- Add a named location with one or more IATA airports and an optional gateway note. Additions persist locally and do not edit the repository presets.
- Vacation duration in inclusive calendar days, default six.
- Start and end dates, bounding outbound and return departure.
- Regular search maps to lite, with a default interval equal to vacation length. Deep defaults to daily departures. An explicit interval can override either mode; deep intervals above 1 are sampled searches.
- Advanced options: origin airports (SFO default), departure interval with an explanation, airlines, optional price ceiling, maximum layovers, outbound duration, and connection wait. Additional trip lengths remain a CLI option.
- Required fields have visible markers. Submitting an incomplete form highlights the missing fields and shows a fill-in message before any search request.
- Preview the exact number of airport/date searches without fetching fares.
- Progress appears immediately above the form and is brought into view. It counts finished lookups, including source failures. ETA appears after the first lookup and uses average elapsed time; provider retries can change it. Finishing the last lookup is followed by snapshot generation.
- Stop a running search. The first version runs one live search at a time.

## Results

Display the cheapest qualifying fare, the destination/date comparison matrix, and matching itineraries with dates, airline, actual airport, outbound connections, outbound duration, and booking-search links. Preserve explicit partial, unavailable, filtered-out, and empty statuses. Display gateway notes and source failures.

Read both Google result sections through the shared adapter. Display `source_warnings` for carriers returned without numeric quotes, with route/date details and a visible notice above the comparison. Include these carrier names in airline suggestions; omit unpriced itineraries from minima. Missing prices do not establish missing flights.

Advanced Missing prices is off by default. Optional `--browser-missing` runs the selected browser after fast searches find eligible unpriced itineraries. A separate bottom retrieval button uses the saved result with `retry-missing` and never repeats the provider lookup. Native Chrome is the default engine; legacy headless Playwright engines remain selectable.

Result filters call the CLI's offline filter against the saved raw snapshot. Clearing a local filter can recover raw fares; it cannot undo a connection restriction used in the live provider query. Filters do not refresh quotes.

Airline filters use case-insensitive exact reported labels; all reported carriers must be selected for mixed itineraries. Blank means all airlines. Suggestions come from raw saved candidates. Carrier labels do not prove the operating airline or selected return carrier.

Download the currently filtered comparison table as UTF-8 CSV, with status values and best-fare details. Download JSON to retain the raw candidates and replay filters with the CLI. Search results last until the app stops or another search replaces them. There is no searchable history in this version. Refreshing the browser restores the submitted search settings and reconnects to the active search or current results.

When search settings change, label existing results as previous and explain that Find flights runs the edited query. Show the searched vacation length in the results summary. Keep duration and an explicit departure interval independent; a blank regular interval follows duration. Regression coverage changes a five-day Dhaka search to thirty days, checks the pending-settings notice, then verifies the submitted query and matrix use Jan 1–30.

## Local boundary and verification

Serve only on `127.0.0.1`. Accept fixed API actions and validated arguments; invoke subprocesses without a shell. Validate request host/origin and use a per-process CSRF token for mutations. Serve only the three known static assets. Escape displayed data and spreadsheet formula prefixes in CSV.

Test CLI progress on both successful and failed lookups; validate custom-location persistence and reserved names; exercise real offline CLI filtering/CSV and local HTTP boundaries. Browser-test regular/deep planning, selection, add-location, validation, progress, filtering, downloads, and cancellation. Keep live testing limited to the user-authorized destinations. Intel compatibility is supported by published dependency wheels but requires separate hardware testing for a verified Intel claim.

Run the backend integration checks with:

```bash
.venv/bin/python -B -W error::DeprecationWarning -m unittest test_flight_ui -v
```

Verified on October 12, 2026: January regular planning produced 12 lookups and deep planning 52 for Cancun/Maui. The regular January live run completed 12 lookups; a small deep January 1–7 run completed four. Both returned fares with no source errors. Browser checks covered adding a location, stopping a search, offline price filtering, CSV/JSON downloads, CLI replay, and restored settings/results after refresh. Quote snapshots and screenshots stay outside the repository; these checks validate behavior, not future prices or availability.

The later Playwright regression added Dhaka/DAC through the UI and completed six five-day regular January 2027 windows with fares and no source errors. Eight browser checks passed, including required-field feedback, progress/ETA within a 662×850 viewport, a three-day deep interval preview, airline filtering and clearing, downloads, and refresh recovery. Regular now defaults to vacation length; the earlier Cancun/Maui count used the original five-day interval.

After correcting both fare sections, an isolated Playwright run passed ten checks: six five-day Dhaka windows returned 53 priced fares with no source errors, then a thirty-day Jan 1–30 request returned seven priced fares. Singapore Airlines appeared in a visible unpriced-itinerary notice and airline suggestions. The test also verified the edited-settings notice and the thirty-day request, matrix, and refresh recovery. These counts describe that run, not guaranteed inventory.

The headless browser-option UI check passed seven checks on an isolated server: default off, exact one-window preview, browser/airline settings submitted, progress visible, 32-day matrix, explicit retry outcome, and refresh restoration. Its live Singapore retry completed with zero recovered quotes and retained the unpriced warning. Other live attempts returned Google search errors. This validates the command/UI path and honest unresolved-state handling, not recovery of the screenshot's $995/$1,214 fares.

## Native Chrome recovery

`flight_native_browser.py` launches installed Chrome directly with a disposable profile and a loopback CDP connection. It uses Python and the existing curl_cffi dependency; Node and Playwright are not runtime requirements. Fixed commands open Cheapest, expand additional flights, then select missing airlines. Native Chrome opens a visible window, which closes and removes its profile after completion, timeout, error or cancellation. It never attaches to a personal profile.

Verify both request routes, departure/return dates, airline codes on both directions, one adult, economy and original live maximum stops. Accept only numeric network prices matching final individual USD Cheapest labels in two stable observations. Reject header-only, ambiguous, mixed-cabin, withdrawn and mismatched quotes. Use a 90-second overall lookup budget, bounded CDP operations and sanitized failure messages. Unresolved prices remain excluded from comparisons.

The retry job retains the current saved query and applied filters even if the user edits the form. It emits stage progress, completed counts and approximate ETA (initial 45 seconds per native lookup, then measured average). Each completed cell atomically saves merged raw fares and recomputes filters, matrix/global/destination minima and exports. Prior fares and completed cells survive cancellation or later failure. Quote provenance is `google_flights_native_chrome` with a per-quote timestamp; prices are round-trip starting quotes with selected return legs unavailable.

`test_native_browser.py` checks request scope, network/DOM agreement, rejected prices, setup failures, deadlines and owned-browser cleanup. `test_missing_retry.py` checks fixed saved targets, separate provider execution, merging, live limits and failure retention. `ui_missing_retry_test.py` drives real HTTP/CLI/frontend with a fixture provider to verify progress, refresh, CSV, incremental merge and cancellation. `ui_native_retry_test.py --live --output PATH` drives real Dhaka/Singapore recovery through the app; it creates its own server and removes it afterward. Neither test uses personal Chrome profiles. Intel hardware remains untested.

Verified October 15, 2026 on Apple Silicon: all 121 offline tests, the fixture HTTP/CLI/UI retry regression, and all ten checks in the live January Dhaka UI regression passed. The native UI regression recovered five Singapore quotes for January 12–16 (lowest $1,573 starting quote), preserved the one-layover live limit on both directions, updated filtered global/destination/matrix minima, restored results after refresh and exported CSV/JSON with provenance. A second live native lookup was stopped through the UI while Chrome was open; original fares were retained and all owned native profiles were removed. Test app servers were stopped after verification. These checks establish this tested route/date behavior, not exhaustive carrier coverage or Intel hardware compatibility.
