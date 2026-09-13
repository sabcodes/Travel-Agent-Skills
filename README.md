# Flight, Award, Stay & Card Deal Tracker

Automated, login-free tracker and reusable skill for cheap cash flights, publicly reported award-flight opportunities, public Airbnb stays, and public Chase, Amex, and Capital One deals/transfer bonuses. Its checked-in defaults remain tailored to **SFO** and **SJC**, while every user can choose their own airports and destinations.

---

## Features

- **Login-Free & Secure**: Operates without user credentials or private API keys.
- **Flexible dates & global routes**: Pre-configured presets remain available, while any IATA origin/destination and any date range can be searched. A city can be supplied for worldwide Airbnb lookup when the airport code is ambiguous.
- **Preset Vacation Hotspots**:
  - 🇲🇽 **Cancun** (`CUN`)
  - 🇯🇲 **Jamaica** (`MBJ` Montego Bay, `KIN` Kingston)
  - 🇵🇷 **Puerto Rico** (`SJU` San Juan, `BQN` Aguadilla)
  - 🇨🇷 **Costa Rica** (`SJO` San José, `LIR` Liberia)
  - 🇧🇷 **Brazil** (`GIG` Rio de Janeiro)
  - 🇵🇪 **Peru** (`LIM` Lima)
  - 🇬🇹 **Guatemala Pacific Coast** (`GUA` Guatemala City, with Monterrico stays)
  - 🌺 **Maui, Hawaii** (`OGG` Kahului)
- **Detailed Layover & Duration Intelligence**:
  - Exact layover counts and stopover cities (e.g. `LAX`, `SAL`, `DFW`)
  - Individual layover wait times (e.g. `2h 31m`)
  - In-air flight duration vs. total door-to-door elapsed journey duration
  - Max stops filter (`--max-stops 0` for nonstop, `--max-stops 1` for max 1 layover)
- **Winter Travel Windows**: Sweeps representative date windows across **November 2026**, **December 2026**, and **January 2027**, or generates departures across any custom date range.
- **Public Feed Monitoring**: Tracks public Chase, American Express Membership Rewards, and Capital One deals and transfer bonuses. The scanner uses an identified feed-reader user agent, respects robots rules, and uses the bundled browser-compatible TLS client only after a transport failure—not after an HTTP denial.
- **Free Award-Deal Radar**: Reads public travel-news feeds, extracts stated routes, months, cabins, points, taxes, and loyalty programs, then ranks reports against the selected travel scope. These are attributed leads—not guaranteed live award inventory—and every result includes a verification link.
- **Accommodation Search**: Chains each flight's dates into public Airbnb searches, returning up to three live listings beneath the nightly budget. If no flight matches, it still provides date-specific Google Hotels and Airbnb search links.
- **Points Synergy Engine**: Flags when a cash flight deal can be booked with transferred Chase Ultimate Rewards points (United/Aeroplan for Star Alliance, British Airways/Iberia Avios for Oneworld, Flying Blue/Virgin for SkyTeam).
- **Versatile Alerts**: Rich terminal tables and Discord/Slack webhook dispatching.
- **Antigravity Agent Skill**: Fully integrated into `.agents/skills/deal-tracker/` for natural language interaction.

---

## Installation

```bash
# 1. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browser
playwright install chromium
```

---

## Usage

### 1. Default Combined Sweep
Scans active card/transfer deals, reported award leads, the checked-in SFO/SJC winter presets, stays, and points synergy:
```bash
.venv/bin/python main.py
```

### 2. Scan Flights with Layover & Duration Metrics
```bash
# Scan Costa Rica with duration and layover breakdown
.venv/bin/python main.py --flights --dest costa_rica --dates 2027-01-15:2027-01-22

# Filter for max 1 stop
.venv/bin/python main.py --flights --dest costa_rica --dates 2027-01-15:2027-01-22 --max-stops 1

# Nonstop flights only
.venv/bin/python main.py --flights --dest cancun --dates 2026-11-13:2026-11-20 --max-stops 0
```

### 3. Query Any Destination Worldwide
```bash
# SFO to Tokyo (HND)
.venv/bin/python main.py --flights --origin SFO --dest HND --dates 2027-01-15:2027-01-25

# SFO or SJC to Hawaii (HNL, OGG)
.venv/bin/python main.py --flights --origin SFO,SJC --dest HNL,OGG --dates 2026-12-05:2026-12-12
```

```bash
# Flexible window, 4- or 7-night trips, and worldwide Airbnb search
.venv/bin/python main.py --flights --stays --origin SFO --dest CDG --stay-location "Paris, France" \
  --date-range 2027-03-01:2027-04-15 --trip-lengths 4,7 --date-step-days 7
```

### 4. Set Airports for Another User

Use any IATA sources for one search:

```bash
.venv/bin/python main.py --flights --origin ORD,MDW --dest LHR --dates 2027-05-10:2027-05-17
```

For durable personal defaults without modifying tracked settings, create an ignored local profile:

```bash
cp config.json config.local.json
# Edit config.local.json and set "origins" to your own airport codes.
.venv/bin/python main.py --config config.local.json
```

### 5. Scan Reported Award-Flight Deals Only

```bash
# All eight checked-in regions for November 2026 through January 2027
.venv/bin/python main.py --award-deals --origin SFO,SJC --months 2026-11,2026-12,2027-01

# One configured region
.venv/bin/python main.py --award-deals --dest jamaica --months 2026-11,2026-12,2027-01 --json
```

The award radar consumes public RSS/Atom metadata from configured publishers such as Frequent Miler, One Mile at a Time, View from the Wing, and AwardWallet Blog. It does not log in to loyalty accounts or scrape private award-search endpoints. It checks each publisher's robots policy before fetching a feed. A TLS or transport failure may receive one compatibility retry; 401/403 responses and disallowed paths are reported as blocked, while 429 responses are reported as rate-limited with any `Retry-After` value preserved. These access states are never presented as an empty search. A result means that a publisher reported an opportunity; points prices and seats can disappear, so verify on the linked loyalty program before transferring points. “No matching reported leads” does not mean that no award seats exist.

The checked-in configuration contains Cancun, Jamaica, Puerto Rico, Costa Rica, Brazil, Peru, Guatemala, and Maui—eleven airport records across eight regions. Dhaka is not included.

### 6. Scan Chase, Amex, and Capital One Deals Only
```bash
.venv/bin/python main.py --deals
```

### 7. Search Hotels and Airbnb
```bash
# Scans matching flights, then attaches the top Airbnb stays under budget
.venv/bin/python main.py --flights --stays --dest cancun --dates 2026-11-13:2026-11-20 --adults 4 --max-nightly-price 250
```

`--stays` is login-free and uses public Airbnb result cards. Availability, fees, and taxes can change before booking; verify the final price at Airbnb. A regular run with no primary scan flag also includes this flight-to-stay handoff.

Every stay includes its room type, bedrooms, beds, bathrooms, and approximate map coordinates when the public result card supplies them. Add `--stay-details` to enrich only the selected stays with amenities, photos, house rules, review scores, recent reviews, capacity, and public description when available:

```bash
.venv/bin/python main.py --flights --stays --stay-details --dest CUN --dates 2026-11-13:2026-11-20 --adults 4 --json
```

### 8. Export Structured JSON
```bash
.venv/bin/python main.py --flights --dest costa_rica --json
```

---

## Webhook Notifications (Discord / Slack / Telegram)

Edit `config.json` and set `"webhook_url"` to your Discord webhook URL:
```json
{
  "webhook_url": "https://discord.com/api/webhooks/YOUR/WEBHOOK/URL"
}
```
When configured, alerts will be formatted with duration, layover summaries, and booking links, and posted directly to your channel. If blank, alerts display in the terminal.

Slack incoming webhooks are detected automatically. For Telegram, provide a Bot API `sendMessage` URL with the destination chat in its query string through `WEBHOOK_URL`, for example `https://api.telegram.org/bot<token>/sendMessage?chat_id=<chat-id>`; keep it out of tracked configuration.

## Security

The tracked `config.json` deliberately contains no credentials. Keep `webhook_url` blank and provide a private notification endpoint through the local `WEBHOOK_URL` environment variable instead. Never commit `.env`, `config.local.json`, credentials, private keys, or API tokens; these paths are ignored by Git. The award radar is a research assistant only: it never buys, sells, holds, transfers, or books tickets and does not use automated logins, private APIs, CAPTCHA bypasses, proxies, or anti-bot evasion.

---

## Daily Scheduling

You can schedule the tracker to run every morning at 8:00 AM using cron:

```bash
# Crontab entry:
0 8 * * * cd "/Users/sabarnoislam/Desktop/AI projects/Travel Agent" && .venv/bin/python main.py >> tracker.log 2>&1
```
