# Flight backend comparison — October 13, 2026

Keep the current `fast-flights` adapter as the app's default. The tested `fli` source did not recover Singapore Airlines prices or reduce the cheapest starting quote. Its return-selection workflow is useful, but the evaluated CLI mislabels higher-priced return combinations with their outbound starting price.

## Scope and source identity

- Current adapter: this repository's `flight_scanner.py`, using `fast-flights` 3.1.0 in the app environment.
- Alternative: `flights` 0.10.0 built from [punitarani/fli commit 881aee5](https://github.com/punitarani/fli/tree/881aee5ff4321e81ea2157cb44be94ce6a21dc1b), downloaded with `gh` and installed in a separate temporary environment.
- SFO round trips, one adult, economy, USD, no price or stop ceiling; two destinations and four date pairs. Three repetitions of each backend/date pair, followed by three `fli` return-expansion operations: **27 operations total**. Preliminary probes and one independent headless validation were additional investigation steps.
- Tested on Apple Silicon. Intel hardware, other origins, cabins, party sizes, and an entire month were not tested.
- Complete source was available. Following the REA skill's routing rule, source inspection and runtime probes were sufficient; no REA engine installation, decompilation, user browser/profile access, or desktop control was used.

The like-for-like `fli-page` probe calls its private `_fetch_flights` method solely to inspect an outbound board without extra return requests. The `fli-return` probe calls the public `SearchFlights.search` API with `top_n=3`, two expansion workers, and a local `SQ` filter for Dhaka. Each backend uses its own transport/query encoding; these are matched search settings, not identical HTTP requests or a shared response fixture.

## Observed results

All 24 repeated page operations succeeded. Both backends returned the same minimum starting quote on all four date pairs in all three repetitions. These are historical checks, not current booking guarantees.

| Route and dates | Current priced rows per run | `fli` priced rows per run | Minimum starting quote, both | Current median | `fli` median |
|---|---|---|---|---|---|
| SFO–CUN, Jan 1–5, 2027 | 8 / 8 / 8 | 8 / 8 / 8 | $618 | 0.987 s | 1.165 s |
| SFO–DAC, Jan 1–5, 2027 | 9 / 9 / 8 | 8 / 8 / 8 | $2,152 | 1.495 s | 1.170 s |
| SFO–DAC, Jan 14–Feb 9, 2027 | 10 / 10 / 10 | 10 / 10 / 10 | $960 | 0.897 s | 1.065 s |
| SFO–DAC, Jan 14–Feb 14, 2027 | 10 / 10 / 10 | 10 / 10 / 10 | $960 | 0.929 s | 1.127 s |

Counts exclude unpriced rows. Our adapter emitted Singapore missing-price notices for every Dhaka check; `fli` retained an unpriced `SQ` row. The variable extra current-backend row on the short Dhaka trip shows that sequential live results are not identical inventories. Its cause was not established by this comparison.

Measured time is worker-internal lookup time, including imports and each provider's built-in retries, excluding process launch and the benchmark's one-second spacing. Request order is fixed, samples are small, and network state can change. These measurements do not establish a general speed winner.

### Singapore and return expansion

With `SQ` selected, both screenshot date pairs produced one outbound/return pair. The outbound was SFO–SIN–DAC; the return was DAC–SIN–SFO. Both price fields and currencies remained unknown. Expansion succeeded in 1.412 s and 1.703 s, respectively, without recovering a quote. This answers the missing-price question for those settings only; it does not establish that Singapore never publishes prices.

For Cancun, expanding three outbound candidates returned 12 pairs in 1.924 s. Every outbound carried a $618 starting quote; the selected-return pages carried $618, $730, $749, or $821 round-trip quotes. Nine pairs had a higher selected-return quote than their outbound starting quote.

An independent, isolated headless Chrome check of the first selected Cancun outbound showed Google Flights' **Returning flights** list with those same four prices, explicitly labeled **round trip**. It also showed the cheapest return arriving at SFO on January 6 despite departing Cancun on January 5. This demonstrates why a return departure bound is different from a final arrival bound.

### Evaluated `fli` CLI price mismatch

The pinned source's [round-trip JSON serializer](https://github.com/punitarani/fli/blob/881aee5ff4321e81ea2157cb44be94ce6a21dc1b/fli/cli/utils.py#L262) and display select `outbound.price` for every two-segment combination. The source, parsed return-page quotes, and headless Google display corroborate a specific problem: a Cancun pair with a $749 selected return would be presented as $618 by that serializer. The library retains the $749 value on the returned second segment; an adapter must use that contextually correct pair quote and never add the two round-trip quotes together.

This conclusion concerns the pinned source's serialization behavior. It is not a claim that all versions or all routes misprice, and it does not mean our current outbound-only starting quote is a confirmed price for any arbitrary return flight.

## What can improve our app

The useful design is an explicit optional second step: select an outbound, fetch returns, and associate each pair with its own reported quote and final arrival date. It could support return-side stop, duration, layover, and arrival filters that our current outbound-only result model cannot verify.

Before adding it, preserve starting quotes separately, handle missing pair quotes/currencies, validate both segment identities/dates, and expose the bounded outbound expansion count and extra request cost. Carrier filtering in the evaluated `fli` page transport happens locally, so it cannot guarantee more carrier inventory than Google initially returned. Do not replace the current date-grid/ranking/export contract with `fli`'s experimental CLI JSON schema.

The richer `fli` models also expose flight numbers, layovers, mixed-cabin and self-transfer signals. Those are promising metadata additions, not evidence that an itinerary's fare includes particular baggage or that inventory is bookable. No production backend migration or UI behavior change is part of this evaluation.

## Reproduce

Install the normal flight requirements first. The optional environment needs Python 3.10+, pip, Git, and network access; the pinned `fli` dependency also installs its HTTP, model, and CLI packages. It does not install Playwright, MCP extras, or a browser.

```bash
.venv/bin/python -m venv /tmp/travel-fli-eval
/tmp/travel-fli-eval/bin/python -m pip install -r requirements-fli-eval.txt
.venv/bin/python evaluate_flight_backends.py compare \
  --fli-python /tmp/travel-fli-eval/bin/python \
  --repeats 3 --top-n 3 --output /tmp/flight-backend-evaluation.json

# A single explicit Singapore round-trip probe:
/tmp/travel-fli-eval/bin/python evaluate_flight_backends.py probe \
  --backend fli-return --destination DAC \
  --departure 2027-01-14 --return-date 2027-02-09 --airline SQ

# Offline guards for unknown prices and pair-price comparisons:
.venv/bin/python -B -m unittest test_backend_eval -v
```

`compare` checkpoints JSON after each operation, then adds timing/count summaries. It reports `ok`, `unpriced_only`, `no_rows`, `unavailable`, `timeout`, and `worker_error`. A failure produces exit code 1 while retaining completed results. Unknown quotes do not become zero. `probe` produces an observation JSON object whose status must be inspected. Defaults bound each worker at 60 seconds and `fli` HTTP requests at 15 seconds; provider retries and return expansion can use additional requests within that budget.

The four comparison dates are fixed investigation fixtures and eventually expire; use `probe` with future dates afterward. The current-backend probe rejects carrier filters so it cannot silently pretend to issue a restricted live query. `fli` accepts IATA carrier codes, whereas our app's user-facing filters use reported airline names.

Structured reports contain fare/query fields, missing-carrier notices, timestamps, versions and summary statistics. They deliberately omit request/booking tokens, response headers, cookies, page HTML, exception text, and local environment paths. Keep generated reports and validation screenshots outside commits. The original local investigation artifacts were named `backend-evaluation.json`, `cancun-return-dom.json`, and `cancun-return-validation.png`; the concise source-linked findings above are the durable record.
