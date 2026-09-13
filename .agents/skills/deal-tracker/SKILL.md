---
name: deal-tracker
description: Use when users ask to find or compare cash flights, publicly reported award-flight deals, Airbnb stays, or Chase, American Express, or Capital One travel and transfer offers.
---

# Travel Deal Tracker Skill

This is the project's master travel-search skill. It routes cash fares, public award reports, stays, and card/transfer offers through one shared configuration.

The checked-in defaults include SFO/SJC beach presets for Cancun, Jamaica, Puerto Rico, Costa Rica, Rio de Janeiro, Lima, Guatemala's Pacific coast, and Maui. They are examples rather than a constraint; use any IATA source airports, destinations, and travel dates worldwide.

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

For long-haul routes, pass a realistic `--max-price`; the checked-in default may filter out every valid fare. For flexible dates, start with a coarse sweep, then search the most promising departures and adjacent dates (typically ±3 days) as exact `--dates` pairs. A weekly grid alone can miss the cheapest weekday. Treat `--date-range` as a total travel window whose returns must fit before its end; when the user gives a departure-only window, include date pairs whose returns extend beyond that window.

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
# Uses all eight checked-in regions; Dhaka is not configured
.venv/bin/python main.py --award-deals --origin SFO,SJC --months 2026-11,2026-12,2027-01

# Narrow to one region and return structured leads
.venv/bin/python main.py --award-deals --dest jamaica --months 2026-11,2026-12,2027-01 --json
```

Every result has `availability_status: reported` and `verification_required: true`. Preserve those meanings in summaries. Link to the original publisher or loyalty program so the user can verify availability before transferring points. If the command returns no leads, say “no matching reported leads”; never say that no award seats exist.

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

Stay results automatically include room type, beds, bedrooms, bathrooms, and approximate coordinates where the public card exposes them. Add `--stay-details` only when richer public listing data is needed; it fetches amenities, photos, rules, review signals, capacity, and available description for the returned top stays.

### 6. Full Sweep (Cash + Awards + Stays + Deals + Points Synergy)
```bash
.venv/bin/python main.py --dest puerto_rico
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

## Award-Deal Safety and Accuracy

- This tool helps users research free travel deals. It never buys, sells, holds, transfers, or books tickets.
- Use public RSS/Atom metadata and attributed links only. Do not automate loyalty logins, private APIs, CAPTCHA handling, proxies, or anti-bot evasion.
- Never invent missing routes, months, cabins, points, taxes, seats, or programs.
- Treat article and feed results as time-sensitive leads. Verify live inventory with the named loyalty program before recommending a points transfer.
- The checked-in scope is Cancun, Jamaica, Puerto Rico, Costa Rica, Brazil, Peru, Guatemala, and Maui. Dhaka/DAC is not a fallback destination.

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
