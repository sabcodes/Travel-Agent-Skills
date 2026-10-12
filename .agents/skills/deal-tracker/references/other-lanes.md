# Public awards, offers, and stays

Read this reference when the request includes these lanes. Use `main.py` with explicit modes and `--json --output PATH`; the saved file is canonical because legacy workflows can log to stdout. Cash-only work uses `flight_tools.py`.

| Need | Mode | Evidence |
|---|---|---|
| Public award stories | `--award-deals` | Reported leads requiring live verification |
| Issuer offers or transfer bonuses | `--deals` | Public promotions |
| Stay research | `--stays` | Public Airbnb cards and hotel/Airbnb links |
| Cash + awards + offers, excluding stays | `--flights --award-deals --deals` | Explicit flags keep stays out |

No primary flag runs all configured scanners, including stays. This configuration retains 12 regions/15 airports; the cash-only pool is separate. Named destinations constrain the run to those selections.

```bash
.venv/bin/python main.py --award-deals --origin SFO \
  --dest belize,mexico_city,saint_lucia,roatan_bay_islands \
  --months 2027-01 --json --output /tmp/award-leads.json

.venv/bin/python main.py --deals --json --output /tmp/card-offers.json

.venv/bin/python main.py --flights --award-deals --deals --origin SFO --dest MEX \
  --dates 2027-01-13:2027-01-18 --json --output /tmp/cash-and-points.json

.venv/bin/python main.py --stays --origin SFO --dest belize \
  --dates 2027-01-13:2027-01-18 --max-nightly-price 500 --adults 4 \
  --json --output /tmp/stays.json
```

Carry explicit budgets and stop limits into `--max-price` and `--max-stops`. Exact dates use `--dates DEPARTURE:RETURN`; generated lengths use inclusive calendar days.

## Public award evidence

Preserve `availability_status: reported` and `verification_required: true`. The feed layer cannot confirm live award seats. Verify inventory with the named loyalty program before recommending a points transfer. Cash itineraries are not award inventory.

Retain original publisher/program links and only reported facts: routes, months, cabins, points, taxes, seats, programs. Empty results mean “no matching reported leads,” not no award seats. `blocked`, `rate-limited`, and `unavailable` are errors, not empty results.

Use public RSS/Atom metadata and attributed links. Identify requests as `TravelAgentDealTracker` and respect robots policies. Disallowed paths and HTTP 401/403 are `blocked`; HTTP 429 is `rate-limited`, preserving Retry-After and deferring until eligible. Other failures are `unavailable`. One browser-compatible HTTP/TLS retry is allowed after transport/TLS failure on a permitted public endpoint, never to bypass denial. The tracker does not automate loyalty logins, CAPTCHAs, proxies, private APIs, bookings, or transfers.

## Transfer relevance

Tag offers with matching issuers: Chase, American Express, and/or Capital One. Preserve the Chase partner cross-reference. `chase_partner_info` describes possible programs, not points prices, live inventory, or proof of award bookability. A bonus is relevant only when its receiving program overlaps a usable program for that itinerary; issuer/alliance membership alone is insufficient.

## Stay evidence

`--stays` enables flights internally. Preserve flight failures in `source_errors` and independently report hotel/Airbnb search links. Hotel links are handoffs, not ranked live prices. Public Airbnb cards can include room type, beds, bedrooms, bathrooms, approximate coordinates; `--stay-details` requests richer public details.

Packages inherit actual flight dates. Preserve totals versus nightly estimates, capacity, fee/tax limitations, provider errors, and listing descriptions. Adults remain accommodation guests, not flight passengers.
