---
name: deal-tracker
description: Scan worldwide cash flights, Airbnb stays, and public Chase, American Express, or Capital One transfer/card deals. Use for flexible travel dates, routes, and points offers.
---

# Flight & Credit Card Deal Tracker Skill

This skill searches flights, Airbnb stays, and public Chase, American Express, and Capital One card offers/transfer bonuses, then cross-references routes with points-and-miles offers.

While pre-configured for **SFO / SJC** to **Cancun**, **Jamaica**, **Puerto Rico**, and **Costa Rica** across **November, December, and January**, it supports **any origin, destination airport, and date range worldwide**.

---

## When to Use

Use this skill when:
- The user asks to scan flight deals from the Bay Area (SFO / SJC) or any other airport.
- The user asks for layover counts, specific layover cities, layover durations, or total elapsed journey times.
- The user asks to filter by nonstop or maximum 1-stop flights (`--max-stops 0` or `--max-stops 1`).
- The user asks about Chase, Amex, or Capital One card deals, welcome offers, or airline transfer bonuses.
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

### 3. Scan Card Deals & Transfer Bonuses
```bash
.venv/bin/python main.py --deals
```

### 4. Search Flexible Dates and Worldwide Stays
```bash
.venv/bin/python main.py --flights --stays --origin SFO --dest CDG --stay-location "Paris, France" \
  --date-range 2027-03-01:2027-04-15 --trip-lengths 4,7 --date-step-days 7
```

Use `--dates DEPARTURE:RETURN` for one fixed trip. Use `--date-range START:END` with `--trip-lengths` for arbitrary windows; generated stays inherit each returned flight's dates. `--dest` accepts preset regions or any IATA airport code.

Stay results automatically include room type, beds, bedrooms, bathrooms, and approximate coordinates where the public card exposes them. Add `--stay-details` only when richer public listing data is needed; it fetches amenities, photos, rules, review signals, capacity, and available description for the returned top stays.

### 5. Full Sweep (Flights + Stays + Deals + Points Synergy)
```bash
.venv/bin/python main.py --dest puerto_rico
```

### 6. Structured JSON Output (For Agent Processing)
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
