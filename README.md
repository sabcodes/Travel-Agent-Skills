# Travel Agent Deal Tracker

A free, login-free research tool and Codex skill for comparing cash flights, public award-deal reports, card and transfer offers, Airbnb result cards, and hotel search links. It does not buy, sell, hold, or book travel.

The flight-only CLI defaults to **SFO**, with 50 selectable destinations. The combined tracker defaults to SFO/SJC. Both accept custom IATA airports.

## Flight-only CLI

Run these commands from the repository root. No agent is needed to search, filter, or generate a comparison matrix.

```bash
# View the destination pool (ids, names, airport alternatives, gateway notes)
.venv/bin/python flight_tools.py destinations

# Lite: one departure every five days, six inclusive calendar days per trip
.venv/bin/python flight_tools.py search --origin SFO --dest cancun,maui \
  --start-date 2027-01-01 --end-date 2027-01-31 --trip-lengths 6 \
  --output /tmp/january-lite.json --format table

# Preview all 50 destinations without making any requests
.venv/bin/python flight_tools.py search --dest all \
  --start-date 2027-01-01 --end-date 2027-01-31 --dry-run

# Use weekly departures instead; any positive spacing is supported
.venv/bin/python flight_tools.py search --dest cancun,maui \
  --start-date 2027-01-01 --end-date 2027-01-31 --date-step-days 7

# Deep: every departure day for each requested trip length; test two locations
.venv/bin/python flight_tools.py search --mode deep --dest cancun,maui \
  --start-date 2027-01-01 --end-date 2027-01-31 --trip-lengths 6 \
  --output /tmp/january-deep.json --format table

# Filter a saved snapshot without fetching fares again
.venv/bin/python flight_tools.py filter --input /tmp/january-deep.json \
  --max-price 500 --max-stops 1 --max-duration-hours 12 --max-layover-hours 4 \
  --output /tmp/january-filtered.json --format table
```

`--dest` accepts `all`, one destination, comma-separated names/ids, or IATA codes. Named Tokyo, Paris, and Tenerife searches compare both configured airports. Selecting `NRT` searches only Narita. `--origin` accepts one or more airports. Lite defaults to a five-day step; deep uses a one-day step. Deep checks every valid departure for each explicit length, not arbitrary return dates.

Trip lengths count **inclusive calendar days**: six days means Jan 1–6, not Jan 1–7. January lite windows are Jan 1–6, 6–11, 11–16, 16–21, 21–26, 26–31. The end date bounds the **return departure date**; the provider does not export the selected return itinerary or its final arrival date. Returns in February require an end date in February.

Prices are USD economy round-trip quotes for **one adult**. `--adults` remains an accommodation option in the combined tracker. Flight searches have **no implicit price ceiling**: configured destination thresholds and the old $2,000 discovery ceiling do not exclude fares. Use `--max-price` when a ceiling is wanted.

JSON is the default stdout format; progress goes to stderr. `--output` always saves structured JSON even when stdout is a table. Snapshots contain the query, timestamp, all provider-returned candidates, status for every airport/date pair, a destination/window matrix, and deterministic minima. Fares rank by price, stops, outbound elapsed time, airline, and stable itinerary fields. This retains all results exposed by the provider; it does not guarantee exhaustive airline inventory.

The offline filter reads `raw_flight_deals`, so local price/duration filters can be relaxed later. A `--max-stops` restriction used during live search narrows the provider query in both directions; offline filtering cannot recover fares omitted by that query. Saved connection counts, layover waits, and durations describe **outbound travel only**. All fares are retained; there is no top-two truncation.

Each matrix cell distinguishes `ok`, `partial`, `filtered_out`, `no_matching_fares`, `unavailable`, or `planned`. An unavailable source is never evidence of no flights. Any source error gives exit code 1 while still producing a snapshot; invalid input gives exit code 2. Successful and valid empty searches give exit code 0. For Bocas del Toro, an empty through-fare search does not rule out separate domestic tickets. Gateway notes flag unpriced onward travel.

### Add a location

Append a record to `flight_destinations.json`, or copy it and pass `--pool PATH`:

```json
{"id": "honolulu", "name": "Honolulu", "airports": ["HNL"]}
```

Use a unique id and uppercase three-letter airport codes. Optional `aliases` accept alternate names; optional `gateway_note` describes onward travel excluded from the fare. Multiple `airports` are searched independently and the matrix selects the cheapest qualifying airport. Validate the pool with `.venv/bin/python flight_tools.py destinations --pool PATH`. The flight pool is separate from the existing award/stay configuration.

## What It Searches

| Data lane | What the tool returns | Important limitation |
|---|---|---|
| Cash flights | Current cash fares, airlines, stops, layovers, durations, and Google Flights links | Prices can change before booking |
| Award deals | Attributed reports from public travel-news feeds | Reports are leads, not confirmed live award seats |
| Card and transfer offers | Public Chase, American Express, Capital One, and loyalty-program promotions | Relevance does not prove an itinerary is bookable with points |
| Airbnb | Up to three public result cards under the nightly budget | Totals may be estimates and can exclude final fees or taxes |
| Hotels | Date- and guest-aware Google Hotels links | Search handoff only; no hotel prices are retrieved |

Flight results are ranked deterministically by cash price, then fewer stops, shorter total journey, and airline name. Airbnb results are deduplicated by listing ID and ranked by nightly price, total price, and listing ID.

Provider failures appear in the JSON `source_errors` array instead of being reported as an empty search.

## Included Destination Presets

The combined tracker and public award/stay configuration retain these 12 regions and 15 airport records. The flight-only pool in `flight_destinations.json` contains all 50 requested locations:

- Cancun (`CUN`)
- Jamaica (`MBJ`, `KIN`)
- Puerto Rico (`SJU`, `BQN`)
- Costa Rica (`SJO`, `LIR`)
- Brazil (`GIG`)
- Peru (`LIM`)
- Guatemala Pacific Coast (`GUA`, with Monterrico stay searches)
- Maui (`OGG`)
- Belize (`BZE`)
- Mexico City (`MEX`)
- St. Lucia (`UVF`)
- Roatán and the Bay Islands (`RTB`)

These presets are examples, not a restriction. Dhaka (`DAC`) is intentionally not configured.

## Install the Local Tool

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

No Playwright browser installation or private travel-account credential is required.

Confirm the CLI is available:

```bash
.venv/bin/python main.py --help
```

## Load the Skill in Codex

### Recommended: use the project-local skill

1. Clone or pull this repository.
2. Open the repository folder as the workspace for a Codex task.
3. Keep the skill at `.agents/skills/deal-tracker/SKILL.md`.
4. Start a new Codex task after cloning or pulling if the existing task does not show the updated skill.

Codex discovers project skills from `.agents/skills/` when the repository is the active workspace. Invoke this skill explicitly with `$deal-tracker`, or ask a matching travel question naturally.

Examples:

```text
$deal-tracker Find the cheapest SFO or SJC flight to Belize for November 8–15, 2026. Include public award reports and transfer bonuses, but skip hotels.
```

```text
$deal-tracker Compare flights and Airbnb stays for four adults in St. Lucia from January 18–25, 2027. Allow at most one stop and keep stays below $500 per night.
```

```text
$deal-tracker Search the flight destination pool for January trips lasting six calendar days. Use a lite five-day departure grid and save the comparison matrix.
```

The skill translates the request into deterministic CLI arguments, runs the checked-in Python tools, and summarizes the structured result. The Python scripts are local workspace tools; this repository does not require an MCP server, Codex plugin, Booking.com credential, or OpenAI API key.

### Optional: install the skill for every Codex project

To make a copy available from the user-level Codex skills directory:

```bash
mkdir -p "$HOME/.codex/skills/deal-tracker"
cp .agents/skills/deal-tracker/SKILL.md "$HOME/.codex/skills/deal-tracker/SKILL.md"
```

The user-level copy does not update automatically. Repeat the copy after pulling repository changes. The project-local version is recommended because it stays synchronized with the code and configuration.

### If Codex does not detect the skill

- Confirm the active Codex workspace is this repository root.
- Confirm `.agents/skills/deal-tracker/SKILL.md` exists.
- Start a new task after installing or updating the skill.
- Ask Codex directly: `Read .agents/skills/deal-tracker/SKILL.md and use it for this travel search.`
- Ensure the local `.venv` exists and `main.py --help` succeeds.

OpenAI describes plugins as bundles that can extend Codex with skills, MCP servers, and optional UI. This repository currently needs only its project-local skill and Python CLI; no plugin installation is necessary. See [OpenAI Developers](https://developers.openai.com/).

## Use the CLI Directly

All examples run from the repository root with `.venv/bin/python`.

### Default combined scan

With no primary mode flag, the tracker runs cash flights, public award reports, card and transfer offers, Airbnb cards, and hotel/Airbnb handoff links:

```bash
.venv/bin/python main.py
```

### Cash flights

```bash
# Exact dates and one destination
.venv/bin/python main.py --flights --origin SFO --dest BZE \
  --dates 2026-11-08:2026-11-15 --max-price 1000

# Multiple origins and destinations
.venv/bin/python main.py --flights --origin SFO,SJC --dest HNL,OGG \
  --dates 2026-12-05:2026-12-12

# At most one stop
.venv/bin/python main.py --flights --origin SFO --dest UVF \
  --dates 2027-01-18:2027-01-25 --max-stops 1

# Nonstop only
.venv/bin/python main.py --flights --origin SFO --dest CUN \
  --dates 2026-11-13:2026-11-20 --max-stops 0
```

### Flexible dates

`--date-range` is the complete travel window, so every generated return date must fit before the end date.

```bash
.venv/bin/python main.py --flights --origin SFO,SJC --dest costa_rica \
  --date-range 2026-11-01:2027-01-31 --trip-lengths 4,7,10 --date-step-days 7
```

For flight-only research, use `flight_tools.py search`: choose lite for sampling or deep for every eligible departure. The legacy month/date-range trip lengths also use inclusive calendar days.

### Cash flights plus points research, without stays

Use all three flags explicitly so the command does not start accommodation searches:

```bash
.venv/bin/python main.py --flights --award-deals --deals \
  --origin SJC --dest MEX --dates 2026-12-02:2026-12-09 \
  --max-price 900 --json
```

### Public award-deal reports

```bash
# All configured regions
.venv/bin/python main.py --award-deals --origin SFO,SJC \
  --months 2026-11,2026-12,2027-01

# One region
.venv/bin/python main.py --award-deals --dest jamaica \
  --months 2026-11,2026-12,2027-01 --json
```

Every award result has `availability_status: reported` and `verification_required: true`. “No matching reported leads” means no matching article was found; it does not mean no award seats exist. Verify availability and pricing with the loyalty program before transferring points.

### Card and transfer offers

```bash
.venv/bin/python main.py --deals
```

`chase_partner_info` identifies possible loyalty programs through which an airline might be bookable. It is not an award price, live inventory, or a guarantee that the captured cash itinerary can be booked with transferred points. A transfer bonus is relevant only when its receiving loyalty program overlaps a usable program for that itinerary.

### Flights and Airbnb stays

```bash
.venv/bin/python main.py --flights --stays --origin SFO --dest BZE \
  --dates 2026-11-08:2026-11-15 --max-price 1000 \
  --max-nightly-price 500 --adults 4 --json
```

Use `--stay-details` to enrich only the selected Airbnb cards with public amenities, photos, house rules, review signals, capacity, and description:

```bash
.venv/bin/python main.py --flights --stays --stay-details --dest CUN \
  --dates 2026-11-13:2026-11-20 --adults 4 --json
```

If an airport code is not a useful accommodation location, pass a city explicitly:

```bash
.venv/bin/python main.py --flights --stays --origin SFO --dest CDG \
  --stay-location "Paris, France" --dates 2027-03-08:2027-03-15
```

Google Hotels entries in `accommodation_searches` have `inventory_status: search_link_only`. Live Airbnb cards are attached under `flight_stay_packages[].stays`. If Airbnb fails, inspect `source_errors` rather than interpreting an empty list as proof that no stays exist.

### Structured output

Print JSON:

```bash
.venv/bin/python main.py --flights --dest costa_rica --json
```

Save JSON outside the repository:

```bash
.venv/bin/python main.py --flights --dest costa_rica --output /tmp/travel-results.json
```

## Personal Defaults

Use any IATA origin for one search:

```bash
.venv/bin/python main.py --flights --origin ORD,MDW --dest LHR \
  --dates 2027-05-10:2027-05-17
```

For persistent personal settings, create the ignored `config.local.json`:

```bash
cp config.json config.local.json
# Edit config.local.json locally.
.venv/bin/python main.py --config config.local.json
```

Do not replace the checked-in SFO/SJC defaults with personal airports merely to run a private search.

## Booking.com Status

Booking.com is not currently used. Its official Demand API can return accommodation inventory, but production and sandbox access require registration as a Booking.com Managed Affiliate Partner, Partner Centre access, an API token, and an affiliate ID. See Booking.com's [prerequisites](https://developers.booking.com/demand/docs/getting-started/prerequisites) and [authentication guide](https://developers.booking.com/demand/docs/development-guide/authentication).

Until authenticated access is configured, hotel output remains a clearly labeled Google Hotels search handoff rather than a ranked hotel-price result.

## Notifications

If `WEBHOOK_URL` is blank, alerts appear in the terminal. To send notifications, provide a private endpoint through the environment instead of committing it:

```bash
export WEBHOOK_URL="YOUR_PRIVATE_WEBHOOK_URL"
.venv/bin/python main.py
```

Discord and Slack incoming webhooks are supported. For Telegram, use a Bot API `sendMessage` endpoint containing the destination `chat_id`; keep the complete URL private.

## Security and Access Policy

- The tracked `config.json` contains no credentials.
- Never commit `.env`, `.env.*`, `config.local.json`, credentials, private keys, webhooks, API tokens, or generated result exports.
- Public feed access checks each publisher's robots policy.
- Disallowed paths and HTTP 401/403 responses are `blocked`; HTTP 429 is `rate-limited`; other failures are `unavailable`.
- A browser-compatible HTTP/TLS retry is allowed once after a transport failure, never to bypass an HTTP denial.
- The tracker does not automate loyalty logins, CAPTCHAs, proxies, private APIs, purchases, reservations, or ticket transfers.

## Test and Validate

For major implementation stages and the final update, keep the README and project skill synchronized with the CLI, run the tests below, then scan the exact staged changes before committing. When a push is authorized, scan the resulting commit before pushing it.

The locally installed `repo-security-gate` skill supplies the offline gate:

```bash
python3 "$HOME/.codex/skills/repo-security-gate/scripts/security-scan" check-staged
python3 "$HOME/.codex/skills/repo-security-gate/scripts/security-scan" check-commit HEAD
```

The bundled gate checks credential patterns; supplement it with a personal-data check of staged files and commit metadata. Keep reports, generated fare snapshots, credentials, and local paths outside commits. A staged/commit scan does not establish that the entire repository history is clean.

Run the complete unit suite:

```bash
.venv/bin/python -B -m unittest discover -v
```

Validate the skill when the Codex skill validator is installed:

```bash
python /path/to/skill-creator/scripts/quick_validate.py .agents/skills/deal-tracker
```

For live smoke tests, save output outside the repository, inspect every requested destination, and keep provider errors distinct from valid empty results.

## Scheduling

Example daily cron entry using a generic installation path:

```cron
0 8 * * * cd /path/to/Travel-Agent-Skills && .venv/bin/python main.py >> tracker.log 2>&1
```

Choose your own private local path. Logs and generated result files are ignored or should remain outside the repository.
