---
name: deal-tracker
description: Use when users ask to find or compare cash flights, publicly reported award-flight deals, Airbnb stays, or Chase, American Express, or Capital One travel and transfer offers.
---

# Travel Deal Tracker Skill

This is the project's master travel-search skill. It routes cash fares, public award reports, stays, and card/transfer offers through one shared configuration.

The checked-in defaults include 12 regions: Cancun, Jamaica, Puerto Rico, Costa Rica, Brazil, Peru, Guatemala's Pacific coast, Maui, Belize, Mexico City, St. Lucia, and Roatán/Bay Islands. They are examples rather than a constraint; use any IATA source airports, destinations, and travel dates worldwide. When a request names destinations, pass only those destinations (for this project: `belize,mexico_city,saint_lucia,roatan_bay_islands` or `BZE,MEX,UVF,RTB`), never the whole configured list.

## Execution Priority

Run the checked-in `.venv/bin/python main.py` workflow first. Flight searches use the open-source `fast-flights` package with `primp` browser-impersonating HTTP requests; they do not require Playwright or browser UI automation.

Choose the mode by the evidence the user needs:

| Need | Mode | Meaning |
|---|---|---|
| Current cash fares and itineraries | `--flights` | Cash results only; never present these as award inventory. |
| Publicly reported points/miles opportunities | `--award-deals` | Attributed news/feed leads that always require live verification. |
| Card offers or transfer bonuses | `--deals` | Public issuer and loyalty-program promotions. |
| Airbnb or hotel handoff | `--stays` | Public stay results or search links tied to travel dates. |
| Combined research | no primary mode flag | Runs all configured scanners and cross-references their output. |

If the user asks for a live, bookable award seat, use `--award-deals` for leads and `--flights` for cash comparison when useful, but state that the free feed layer cannot confirm live award inventory. Do not equate zero matching stories with zero available seats.

If the flight provider raises a connectivity or parser error, diagnose the project scanner and report the failure distinctly from “no fares.” Do not silently switch to computer-use browser automation. Use a browser only when the user explicitly requests it or the project path remains unavailable after reasonable diagnosis, and disclose the fallback.

For a flights-plus-points request that excludes stays, always invoke all three modes explicitly:

```bash
.venv/bin/python main.py --flights --award-deals --deals --origin ORIGIN --dest DESTINATION --dates DEPARTURE:RETURN --json
```

Add the user's `--max-price` and `--max-stops` constraints when supplied. Do not omit the three mode flags: running without a primary mode also starts the stays workflow.

Before running or presenting a command, translate every explicit request constraint and verify that it appears in the command:

- “under,” “up to,” or “maximum” cash budget → `--max-price AMOUNT`
- “nonstop” → `--max-stops 0`
- “no more than one stop” or another stop limit → `--max-stops NUMBER`
- exact departure and return dates → `--dates DEPARTURE:RETURN`
- flights + public award reports + card/transfer offers, without stays → include `--flights --award-deals --deals` and omit `--stays`

When selecting the “cheapest” flight, inspect the complete structured `flight_deals` array rather than a truncated terminal table. First discard any item that violates the requested origin, destination, dates, price ceiling, or stop limit; then rank qualifying items by numeric `price` ascending. Break exact price ties by fewer `stops`, then shorter `total_journey_duration`, then airline name. Never replace the cash-price winner with a more convenient or points-capable itinerary unless the user requested a different objective. If useful, show such an itinerary separately as an alternative.

For diagnostic coverage, temporarily pass a realistic discovery ceiling such as `--max-price 2000`; this overrides the configured destination thresholds, so treat results as candidates and compare them with `config.json` before calling them deals. Omit the override for normal monitoring. One command can exercise representative seven-night departures on 2026-11-13, 2026-12-11, and 2027-01-08: use `--date-range 2026-11-13:2027-01-22 --trip-lengths 7 --date-step-days 28`. For flexible dates, start with a coarse sweep, then search the most promising departures and adjacent dates (typically ±3 days) as exact `--dates` pairs. A weekly grid alone can miss the cheapest weekday. Treat `--date-range` as a total travel window whose returns must fit before its end; when the user gives a departure-only window, include date pairs whose returns extend beyond that window.

---

## When to Use

Use this skill when:
- The user asks to scan flight deals from the Bay Area (SFO / SJC) or any other airport.
- The user asks for layover counts, specific layover cities, layover durations, or total elapsed journey times.
- The user asks to filter by nonstop or maximum 1-stop flights (`--max-stops 0` or `--max-stops 1`).
- The user asks about Chase, Amex, or Capital One card deals, welcome offers, or airline transfer bonuses.
- The user asks for award-flight deals, award space reports, points prices, miles redemptions, or opportunities reported by travel sites.
- The user wants to know if a cash flight deal can be booked with transferred Chase Ultimate Rewards points.

---

## Tool Execution Reference

All commands run with the local virtual environment Python: `.venv/bin/python`.

### 1. Sweep Flights with Duration & Layover Analysis
```bash
# Filter by destination region and date window
.venv/bin/python main.py --flights --dest costa_rica --dates 2027-01-15:2027-01-22

# Filter for max 1 layover / stop
.venv/bin/python main.py --flights --dest costa_rica --dates 2027-01-15:2027-01-22 --max-stops 1

# Nonstop flights only
.venv/bin/python main.py --flights --dest cancun --dates 2026-11-13:2026-11-20 --max-stops 0
```

### 2. Search Any Custom Origin & Destination Worldwide
You can pass any standard IATA airport codes to `--origin` and `--dest`:
```bash
# SFO to Tokyo (Haneda/Narita)
.venv/bin/python main.py --flights --origin SFO --dest HND --dates 2027-01-15:2027-01-25

# SFO or SJC to Honolulu (HNL) or Maui (OGG)
.venv/bin/python main.py --flights --origin SFO,SJC --dest HNL,OGG --dates 2026-12-05:2026-12-12

# SFO to London (LHR) with max 1 stop
.venv/bin/python main.py --flights --origin SFO --dest LHR --dates 2026-11-10:2026-11-20 --max-stops 1
```

Use `--origin`, `--origins`, or `--home-airports` with comma-separated IATA codes for a request. To make another traveler's airports persistent, copy `config.json` to the Git-ignored `config.local.json`, change `origins`, then use `--config config.local.json`. Do not overwrite the checked-in SFO/SJC defaults merely to serve another user.

### 3. Scan Public Award-Deal Reports

```bash
# Uses all 12 checked-in regions; Dhaka is not configured
.venv/bin/python main.py --award-deals --origin SFO,SJC --months 2026-11,2026-12,2027-01

# Narrow to one region and return structured leads
.venv/bin/python main.py --award-deals --dest jamaica --months 2026-11,2026-12,2027-01 --json

# Only the requested configured destinations
.venv/bin/python main.py --award-deals --origin SFO,SJC --dest belize,mexico_city,saint_lucia,roatan_bay_islands --months 2026-11,2026-12,2027-01 --json
```

Every result has `availability_status: reported` and `verification_required: true`. Preserve those meanings in summaries. Reported articles are leads, not live inventory; never claim seats, points prices, taxes, or transferability are currently available. Link to the original publisher or loyalty program so the user can verify availability before transferring points. If the command returns no leads, say “no matching reported leads”; never say that no award seats exist. A source `blocked`, `rate-limited`, or `unavailable` status is a provider error and must remain distinct from an empty result.

### 4. Scan Card Deals & Transfer Bonuses
```bash
.venv/bin/python main.py --deals
```

### 5. Search Flexible Dates and Worldwide Stays
```bash
.venv/bin/python main.py --flights --stays --origin SFO --dest CDG --stay-location "Paris, France" \
  --date-range 2027-03-01:2027-04-15 --trip-lengths 4,7 --date-step-days 7
```

Use `--dates DEPARTURE:RETURN` for one fixed trip. Use `--date-range START:END` with `--trip-lengths` for arbitrary windows; generated stays inherit each returned flight's dates. `--dest` accepts preset regions or any IATA airport code.

For a stay-focused check that must still produce Google Hotels and Airbnb links when flights are unavailable, use `--stays` with an exact pair and the requested location/budget/party size, for example:
```bash
.venv/bin/python main.py --stays --origin SFO,SJC --dest belize,mexico_city,saint_lucia,roatan_bay_islands --dates 2026-11-13:2026-11-20 --max-nightly-price 500 --adults 4 --json
```
Run it for each representative pair. `--stays` also enables flights internally; preserve any flight provider error from `source_errors` and independently report generated public hotel/Airbnb links rather than calling the result “no stays.”

Stay results automatically include room type, beds, bedrooms, bathrooms, and approximate coordinates where the public card exposes them. Add `--stay-details` only when richer public listing data is needed; it fetches amenities, photos, rules, review signals, capacity, and available description for the returned top stays.

### 6. Full Sweep (Cash + Awards + Stays + Deals + Points Synergy)
```bash
.venv/bin/python main.py --dest puerto_rico

# Four-destination diagnostic sweep across one week in each target month.
# No primary mode flag means cash, public award reports, card/transfer offers,
# Airbnb cards, and hotel/Airbnb links all run together.
.venv/bin/python main.py --origin SFO,SJC \
  --dest belize,mexico_city,saint_lucia,roatan_bay_islands \
  --date-range 2026-11-13:2027-01-22 --trip-lengths 7 --date-step-days 28 \
  --max-price 2000 --max-nightly-price 500 --adults 4 --json
```

### 7. Structured JSON Output (For Agent Processing)
```bash
.venv/bin/python main.py --flights --dest cancun --json
```

---

## Duration & Layover Data Structure

Every flight deal extracted contains full duration and stopover metrics:
- `layovers_count`: Integer count of stops (e.g., `0`, `1`, `2`)
- `layover_summary`: Formatted summary of stopover cities and wait times (e.g., `"LAX (2h 31m), SAL (2h 35m)"` or `"Nonstop"`)
- `flight_duration_air`: Time spent in the air across all flight legs (e.g., `"7h 29m"`)
- `total_journey_duration`: Elapsed door-to-door travel duration (e.g., `"14h 35m"`)
- `legs`: Full flight segment breakdown including departure/arrival times, airport codes, and aircraft types.
- `booking_url`: Direct pre-populated Google Flights booking link.

---

## Transfer and Card-Offer Handling

- Capture only public offers and transfer bonuses; never request or handle account credentials.
- Tag every deal with matching issuer names (`Chase`, `American Express`, and/or `Capital One`) so consumers can filter them reliably.
- Preserve the existing Chase transfer-partner cross-reference. Amex and Capital One offers are surfaced even when no direct airline-partner model applies.
- Treat `chase_partner_info` as possible programs through which the operating airline might be bookable. It is not a points price, live award inventory, or proof that a transfer will work for the captured cash itinerary.
- Mention a transfer bonus as relevant only when its receiving loyalty program overlaps a usable program for the selected itinerary. Do not infer relevance from the card issuer or airline alliance alone.

## Award-Deal Safety and Accuracy

- This tool helps users research free travel deals. It never buys, sells, holds, transfers, or books tickets.
- Use public RSS/Atom metadata and attributed links only. Do not automate loyalty logins, private APIs, CAPTCHA handling, proxies, or anti-bot evasion.
- Identify the tool as `TravelAgentDealTracker` and check the source's published robots policy before fetching. A disallowed path is `blocked`; do not fetch or work around it.
- A browser-compatible HTTP/TLS client is allowed for one retry only after a transport or TLS failure on an otherwise permitted public endpoint. Never use it to retry or disguise an HTTP 401 or 403 response.
- Treat HTTP 401/403 as `blocked` and HTTP 429 as `rate-limited`. Preserve `Retry-After` when supplied and wait until a later eligible run; do not hammer the source. Treat other source failures as `unavailable`.
- Keep `blocked`, `rate-limited`, and `unavailable` distinct from “no matching reported leads” in user-facing results.
- Never invent missing routes, months, cabins, points, taxes, seats, or programs.
- Treat article and feed results as time-sensitive leads. Verify live inventory with the named loyalty program before recommending a points transfer.
- The checked-in scope is Cancun, Jamaica, Puerto Rico, Costa Rica, Brazil, Peru, Guatemala, Maui, Belize, Mexico City, St. Lucia, and Roatán/Bay Islands. Dhaka/DAC is not a fallback destination.

## Verification

- Run `.venv/bin/python -B -W error::DeprecationWarning -m unittest discover -v`; this project uses `unittest` and does not require `pytest`.
- For live smoke tests, save structured output with `--output PATH`, inspect every requested destination, and report provider errors separately from valid empty results.
- A cash fare's `chase_partner_info` is a possible transfer path, not proof of live award space. Only a sourced award lead belongs under award results, and it still requires live loyalty-program verification.

## Chase Points Synergy & Partner Rules

1. **Star Alliance (United, Air Canada, COPA, Avianca)**:
   - Direct Chase UR transfer: **United MileagePlus** (1:1), **Air Canada Aeroplan** (1:1).
   - Sweet spot: Aeroplan frequently offers 20–30% transfer bonuses.
2. **Oneworld (American Airlines, Alaska, British Airways, Iberia)**:
   - Indirect Chase UR transfer: Transfer to **British Airways Executive Club** or **Iberia Plus** (Avios) to book American/Alaska flights.
3. **SkyTeam (Delta, Air France, KLM, Virgin Atlantic, Aeromexico)**:
   - Indirect Chase UR transfer: Transfer to **Air France/KLM Flying Blue** or **Virgin Atlantic Flying Club**.
4. **Southwest & JetBlue**:
   - Direct 1:1 transfer partners from Chase Ultimate Rewards.
