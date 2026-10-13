---
name: deal-tracker
description: Search and compare cash flights with lite or deep date grids, analyze saved fare matrices, and research publicly reported award deals, stays, and Chase, Amex, or Capital One travel offers.
---

# Travel Deal Tracker

Use the checked-in CLI for searches, date generation, filtering, and ranking. The agent translates requests into parameters and explains results. Run commands from this repository with `.venv/bin/python`.

For first-time installation, follow [README setup and requirements](../../../README.md#setup-and-requirements) before running the CLI.

## Local browser app

For a visual search/filter workflow, run `.venv/bin/python flight_ui.py` or the Mac launcher. The lightweight local app executes `flight_tools.py` for planning, live search, and offline filtering; it uses the same ranking and date rules below. Regular means lite. Progress counts completed attempts, including failures, and ETA is an estimate based on measured lookup times.

The picker contains all presets and locally added locations. Additions persist outside the repository; they do not modify the shared CLI pool. CSV exports the currently filtered matrix and best-fare details; JSON retains raw candidates for CLI replay. Search results are temporary until the app stops or a new search replaces them. See [README browser app](../../../README.md#local-browser-app) for installation, local storage, and compatibility, and [UI spec](../../../docs/local-flight-ui.md) for scope and verification.

## Cash-flight workflow

1. Translate requested airports, total travel window, trip lengths, search depth, and optional limits into a command. Named destinations restrict the search to those selections. Discover pool ids, names, airport alternatives, and gateway notes with `flight_tools.py destinations`.
2. Run `flight_tools.py search` and save the structured snapshot with `--output`. Use lite unless the user requests deep or exhaustive date comparison. `--dry-run` previews the exact search plan without network requests.
3. Read the saved `query`, `applied_filters` when present, `source_errors`, `summary`, `matrix`, and `cheapest_by_destination`. Use `flight_tools.py filter` for constraints or alternatives; it works offline and preserves raw candidates.
4. Present qualifying minima with airports, dates, airline, outbound connections, wait times, duration, and booking links. Distinguish sampled minima from results covering every eligible departure.

```bash
# Lite: six inclusive days and five-day departure spacing
.venv/bin/python flight_tools.py search --origin SFO --dest cancun,maui \
  --start-date 2027-01-01 --end-date 2027-01-31 --trip-lengths 6 \
  --output /tmp/january-lite.json --format table

# Deep: every departure for each explicitly requested length
.venv/bin/python flight_tools.py search --mode deep --origin SFO --dest cancun,maui \
  --start-date 2027-01-01 --end-date 2027-01-31 --trip-lengths 6 \
  --output /tmp/january-deep.json --format table

# Offline filtering and ranking
.venv/bin/python flight_tools.py filter --input /tmp/january-deep.json \
  --max-price 500 --max-stops 1 --max-duration-hours 12 --max-layover-hours 4 \
  --output /tmp/january-filtered.json --format table
```

Use `--dest all` for the pool, one name/id/IATA code for one selection, or a comma-separated subset. Arbitrary IATA codes work outside the pool. Named Tokyo searches HND/NRT; `--dest NRT` restricts it to Narita. Multiple origin airports are supported.

## Dates and filters

- Trip lengths count **inclusive calendar days**: six days means Jan 1–6. January lite windows are Jan 1–6, 6–11, 11–16, 16–21, 21–26, 26–31. Overnight travel reduces time at the destination.
- Lite defaults to a five-day departure step. `--date-step-days` accepts any positive integer, including 7, 8, or 9. Deep uses a one-day step for every requested length; `--trip-lengths 5,6` checks both lengths, not arbitrary return dates.
- Start/end parameters bound outbound and return **departure dates**. A January 31 end excludes February return departures. A departure-only request needs an end date extended enough for its returns. Selected return legs and final arrival dates are unavailable from this provider.
- Cash fares are USD economy quotes for **one adult**. `--adults` remains a hotel/BnB parameter in the combined tracker.
- Searches have **no implicit price ceiling**. Pass `--max-price` only for an explicit user budget; configured deal thresholds do not reduce search results.
- `--max-price` is inclusive. For a strict “below $400” budget, use a $399.99 ceiling.
- Nonstop becomes `--max-stops 0`; other stop limits become `--max-stops N`. `--max-layovers` is an alias for the connection count. Wait and journey limits use `--max-layover-hours` and `--max-duration-hours`.
- A live stop limit narrows Google's query in both directions. Exported stop counts, waits, and durations describe **outbound** legs. Offline filters cannot recover fares omitted by a provider-query limit or verify the selected return connections.

## Determine the cheapest

Use the tool's matrix/minima and structured arrays. It retains every fare returned by the provider, rather than only two per search. The provider itself may expose limited inventory.

Rank eligible fares by numeric price, fewer outbound stops, shorter outbound elapsed time, airline, then stable route/date/itinerary fields. Price is the primary objective. Show a more convenient itinerary separately when useful.

JSON includes `raw_flight_deals`, filtered `flight_deals`, the query, per-airport/date `searches`, destination/window `matrix`, and global/destination minima. `query.filters` records original live-search limits; `applied_filters` records the current offline limits. Offline filters can relax local price/duration limits using raw candidates. The timestamp remains the original quote time; filtering is not a fresh availability check.

Matrix statuses distinguish `ok`, `partial` (fares with incomplete airport coverage), `filtered_out`, valid empty searches (`no_matching_fares`), source failures (`unavailable`), and dry-run cells (`planned`). Exit code 1 preserves output with source errors; code 2 indicates invalid inputs. Report failures separately and qualify minima when coverage is incomplete. Missing through fares to Bocas del Toro do not rule out separate domestic tickets.

Gateway notes describe onward travel excluded from airfare. Display actual arrival airports, especially St. John via STT, Sanibel via RSW, Harbour Island via ELH, and Siquijor via CEB. Links preserve query settings but open searches, not held tickets. Recheck fares and baggage terms before booking.

If the provider fails, inspect errors and diagnose the local path. Use browser UI only when requested or the checked-in path remains unavailable after reasonable diagnosis; disclose the fallback.

## Add destinations

Append a record to `flight_destinations.json`, or pass an alternate file with `--pool PATH`:

```json
{"id": "honolulu", "name": "Honolulu", "airports": ["HNL"]}
```

Use a unique id and uppercase three-letter airports. Optional `aliases` add names; `gateway_note` describes unpriced onward travel. Multiple airports are compared within the destination's row. Validate the pool with `flight_tools.py destinations --pool PATH`. Keep it separate from award/stay configuration.

Keep the [README preset table](../../../README.md#included-destination-presets) synchronized when changing the pool; use `flight_destinations.json` and the CLI as the authoritative location/airport mapping.

## Other travel lanes

For public award reports, card/transfer offers, hotels, or BnBs, read [references/other-lanes.md](references/other-lanes.md). Existing workflows remain available; flight-only work uses `flight_tools.py`.

## Verification

```bash
.venv/bin/python -B -W error::DeprecationWarning -m unittest discover -v
.venv/bin/python /path/to/skill-creator/scripts/quick_validate.py .agents/skills/deal-tracker
```

Verify saved date bounds, inclusive lengths, airports, matrix coverage, errors, and ranking. Live-test lite/deep against two selected destinations before a broad sweep. Replay a saved snapshot to confirm identical filtering and minima. Tests and format validation do not prove live availability.

For authorized commits and pushes, keep README and skill guidance synchronized at each major stage and the final update. Use the installed `repo-security-gate` skill to check staged content before committing and the resulting commit before pushing. Supplement its credential patterns with personal-data and commit-metadata checks; keep generated reports and local fare snapshots outside commits. A clean staged diff does not certify the full history.
