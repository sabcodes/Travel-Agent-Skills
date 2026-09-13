# Award Deal Radar Design

## Purpose

Add a free, public-source award-flight deal radar to the existing Travel Agent. It saves users from manually checking many travel-news sites while remaining a research tool: it never buys, sells, holds, transfers, or books tickets.

## Scope

The first release ingests public RSS/Atom deal reporting, extracts useful award facts, matches those leads to the user's configured origins, destinations, and months, ranks them, and links to the original publisher for verification. It supports the checked-in SFO/SJC configuration for these eight regions: Cancun, Jamaica, Puerto Rico, Costa Rica, Brazil, Peru, Guatemala, and Maui. Dhaka is not part of the configuration or fallback matching.

This release does not scrape authenticated airline or award-search sites, call private APIs, evade anti-bot controls, solve CAPTCHAs, handle loyalty credentials, or claim that a reported seat remains live. Official provider APIs can be added later behind the same normalized result contract if a free, permitted option becomes available.

## Sources and attribution

Direct publisher feeds are the primary sources. An optional public aggregator feed may supplement them, but the tool must preserve each item's publisher name and canonical source URL. The tool stores and emits only the feed metadata, a short plain-text excerpt, and extracted facts; it does not reproduce full articles.

Feed failures are isolated. One unavailable or malformed source must not suppress valid results from other feeds, and a source failure must remain distinguishable from zero matching deals.

## Data contract

Each normalized award lead contains:

- `title`, `source`, `source_url`, `published`, and a short `summary`
- `origins`, `destinations`, and `matched_regions`
- `travel_months`, `cabin`, `programs`, `points`, and `taxes_usd` when stated
- `match_level`: `exact-route`, `regional-match`, or `general-sale`
- `confidence_score` from 0 through 100 and human-readable `match_reasons`
- `availability_status: reported` and `verification_required: true`
- matching transfer bonuses from the existing card-deal feed when a loyalty program overlaps

Missing facts remain `null` or empty; the parser must not invent values.

## Matching and ranking

Destination matching uses the configured IATA codes, normalized region keys, and names found in each configured display name. Exact configured airport codes outrank regional name matches. An origin match is optional because many useful sale reports are region-wide, but a configured-origin match raises confidence.

Travel months recognize ISO year-month strings and English month names with a year. Leads naming one of the requested months outrank undated sale reports. Leads that explicitly name only months outside the requested window are excluded.

A candidate must contain award intent such as a stated points/miles amount, award space/availability, or an award sale/deal. Generic loyalty-program commentary is excluded. Duplicate canonical links are removed. Results sort by confidence and then publication time.

## User experience

`main.py --award-deals` runs only the award-news scan. Existing `--origin`, `--dest`, `--months`, `--json`, and `--output` options narrow it. A normal all-in-one run includes award leads alongside cash flights, stays, and transfer/card deals.

Terminal and webhook output clearly says `Reported award lead — verify live availability`. JSON adds an `award_deals` array and `total_award_deals` count. A zero-result message says no matching reported leads; it does not say no award seats exist.

## Skill design

The existing `deal-tracker` skill remains the single master travel-agent skill because cash flights, stays, transfer bonuses, and award leads share the same configuration and frequently need cross-referencing. Its routing guidance must distinguish:

- cash fare lookup: `--flights`
- public award-news lead lookup: `--award-deals`
- card and transfer offers: `--deals`
- live award inventory: unsupported by the free feed layer and requiring user verification

The skill must not direct agents to subagents, private endpoints, automated logins, or anti-bot techniques.

## Verification

Use test-first development. Fixture-based tests cover extraction, all eight configured regions, exclusion of Dhaka, target-month filtering, deduplication, source-failure isolation, CLI wiring, JSON output, and terminal/webhook labeling. Live verification is a bounded smoke test proving that at least one configured public feed can be fetched and parsed; zero destination matches is acceptable because current published deals vary.

Skill evaluation uses one bounded evaluator session before and after the skill update. Success means it chooses `--award-deals` for reported leads, does not misrepresent `--flights` as live award inventory, preserves the eight-region/Dhaka boundary, and recommends verification without delegating or scraping.
