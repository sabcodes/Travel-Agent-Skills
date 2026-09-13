# Award Deal Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a free public-feed award-flight deal radar for the Travel Agent's eight configured destination regions.

**Architecture:** A focused `award_deal_monitor.py` module will normalize public feed entries, extract only stated award facts, match them against existing configuration, rank them, and attach relevant transfer bonuses. `main.py` and `notifier.py` expose the results without changing the existing cash-flight provider.

**Tech Stack:** Python 3, `feedparser`, `requests`, `unittest`, existing Rich terminal output

**Spec:** `docs/superpowers/specs/2026-09-13-award-deal-radar-design.md`

## Global Constraints

- The feature never buys, sells, holds, transfers, or books tickets.
- Use only public feeds; do not automate logins, private APIs, CAPTCHAs, proxies, or anti-bot evasion.
- Label every feed result as reported and requiring live verification.
- Support exactly the configured regions; the checked-in configuration must not include Dhaka.
- Preserve current uncommitted travel-agent work and existing command behavior.
- Keep verification bounded: fixture unit tests, the full local suite, one live feed smoke test, and one evaluator session reused before/after the skill edit.

---

### Task 1: Award lead extraction and eight-region matching

**Files:**
- Create: `award_deal_monitor.py`
- Create: `test_award_deal_monitor.py`
- Modify: `config.json`

**Interfaces:**
- Consumes: existing `config.json` fields `origins`, `destinations`, and `target_months`
- Produces: `parse_award_entry(entry, cfg, source) -> Optional[Dict[str, Any]]` and `match_configured_destinations(text, cfg) -> Tuple[List[str], List[str], str]`

- [ ] **Step 1: Write failing extraction and region tests**

Create literal feed-entry fixtures that assert a 25,000-mile SFO-CUN November business-class report becomes an `exact-route` lead, a named Jamaica report becomes a `regional-match`, all eight region names resolve, and Dhaka/DAC resolves to nothing.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/python -B -m unittest test_award_deal_monitor -v`

Expected: import failure because `award_deal_monitor` does not exist.

- [ ] **Step 3: Implement the smallest honest parser**

Add normalization, configured alias matching, ISO/month-name extraction, points/taxes/cabin/program extraction, award-intent gating, match reasons, and a bounded confidence score. Derive aliases from configuration rather than a hidden global destination list.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `.venv/bin/python -B -m unittest test_award_deal_monitor -v`

Expected: all extraction and region tests pass.

### Task 2: Public feed ingestion, isolation, and transfer matching

**Files:**
- Modify: `award_deal_monitor.py`
- Modify: `test_award_deal_monitor.py`
- Modify: `config.json`

**Interfaces:**
- Consumes: `award_deal_feeds`, `award_deal_max_age_days`, and normalized card deals
- Produces: `fetch_award_deals(config_path, origins=None, destinations=None, months=None, fetch_content=None) -> List[Dict[str, Any]]` and `attach_transfer_deals(award_deals, card_deals) -> List[Dict[str, Any]]`

- [ ] **Step 1: Write failing feed behavior tests**

Use in-memory RSS bytes to assert canonical-link deduplication, target-month exclusion, destination overrides, continued processing after one fetch error, and transfer-bonus attachment only when a named program overlaps.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/python -B -m unittest test_award_deal_monitor -v`

Expected: failures for missing feed and transfer functions.

- [ ] **Step 3: Implement feed orchestration**

Reuse the existing public-feed fetch helper, inject it for tests, support named feed objects and URL strings, preserve source attribution, report source errors, deduplicate normalized links, filter explicit out-of-window months, attach transfer matches, and sort by score/publication time.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/python -B -m unittest test_award_deal_monitor -v`

Expected: all award monitor tests pass.

### Task 3: CLI, JSON, and notifications

**Files:**
- Modify: `main.py`
- Modify: `notifier.py`
- Modify: `test_main_integration.py`
- Modify: `test_notifier.py`

**Interfaces:**
- Consumes: `fetch_award_deals(...)` and `attach_transfer_deals(...)`
- Produces: CLI flag `--award-deals`, JSON field `award_deals`, summary field `total_award_deals`, terminal table `format_terminal_award_deals(...)`, and explicit reported/verification webhook text

- [ ] **Step 1: Write failing integration and notification tests**

Assert an award-only scanner run passes configured filters to the monitor, includes award results in JSON, and prints/sends `Reported award lead` plus `verify live availability` without calling the cash-flight scanner.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/python -B -m unittest test_main_integration test_notifier -v`

Expected: failures for the absent award scan and formatter paths.

- [ ] **Step 3: Wire the award mode**

Add `scan_awards` to `run_scanner`, define explicit-mode selection without regressing default full scans or `--stays`, pass origin/destination/month overrides, attach transfer deals, emit JSON counts, and route terminal/webhook output through the award formatter.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/python -B -m unittest test_main_integration test_notifier -v`

Expected: all integration and notification tests pass.

### Task 4: Documentation and master skill

**Files:**
- Modify: `README.md`
- Modify: `.agents/skills/deal-tracker/SKILL.md`

**Interfaces:**
- Consumes: the verified CLI contract from Task 3
- Produces: concise user documentation and one unambiguous master-skill routing contract

- [ ] **Step 1: Preserve the baseline skill-eval failure**

Record that the pre-edit evaluator incorrectly routes award-news discovery through `--flights` because the skill has no award mode.

- [ ] **Step 2: Update README and the existing skill**

Document `--award-deals`, the eight configured regions, public sources, reported-versus-live semantics, zero-result semantics, and safety boundaries. Keep one master skill rather than introducing overlapping skill descriptions.

- [ ] **Step 3: Run the same evaluator session against the revised skill**

Success criteria: chooses `--award-deals` for public reported leads, labels `--flights` as cash only, refuses to equate zero stories with zero award seats, excludes Dhaka, and does not delegate or propose scraping.

### Task 5: End-to-end verification

**Files:**
- Modify only if a failing verification exposes a tested defect

**Interfaces:**
- Consumes: the complete award-deal workflow
- Produces: verification evidence for fixtures, CLI, public feed compatibility, and skill routing

- [ ] **Step 1: Run the full local suite**

Run: `.venv/bin/python -B -m unittest discover -v`

Expected: all tests pass with no tracebacks.

- [ ] **Step 2: Run the eight-region fixture verification**

Run: `.venv/bin/python -B -m unittest test_award_deal_monitor.AwardDestinationCoverageTests -v`

Expected: all eight regions match and Dhaka does not.

- [ ] **Step 3: Run one bounded live public-feed smoke test**

Run: `.venv/bin/python -B main.py --award-deals --json`

Expected: at least one configured feed parses successfully; matching lead count may be zero, but provider failures are reported separately and JSON remains valid after removing human status lines.

- [ ] **Step 4: Inspect the final diff and status**

Run: `git diff --check` and `git status --short`

Expected: no whitespace errors, no credentials, no Dhaka configuration, and only intended files changed in addition to the preserved pre-existing worktree changes.
