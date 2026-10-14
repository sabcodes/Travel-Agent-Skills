# Singapore Airlines missing-price investigation

October 14 update: an isolated, visible native Chrome/CDP prototype recovered live Singapore quotes, including a five-day January trip. See [the experiment, controlled comparisons, and reproducible commands](native-chrome-price-investigation.md). The default headless retry remains unchanged. The evidence below records the earlier October 13 investigation.

## What the captures establish

The second supplied HAR and matching screenshots show the same San Francisco–Dhaka search for **January 12–February 13, 2027**, one adult, with Singapore Airlines selected. Best shows “Price unavailable”; Cheapest shows numeric round-trip quotes.

| Outbound departure | Outbound duration | Recorded USD quote |
|---|---|---|
| 09:40 | 23 hours | $1,039 |
| 09:40 | 47 hours | $1,258 |
| 09:40 | 71 hours | $1,258 |
| 20:15 | 36 hours 25 minutes | $2,117 |
| 20:15 | 60 hours 25 minutes | $2,205 |

These are captured amounts, not freshly verified fares. The longer evening options can include mixed cabins; do not assume every row is an economy-only itinerary. Currency is established by the matching user-supplied screenshots, not independently decoded from every fare context.

In the second HAR, zero-based records 94 and 117 contain these prices in framed `GetShoppingResults` updates. Existing `flight_browser.shopping_response_flights` decodes them. Repeated streamed updates must be deduplicated by itinerary and amount. A mixed JetBlue/Singapore result is separate from the five Singapore-only rows above.

The first HAR's January 14–February 9 shopping responses contain empty Singapore price fields. Its cheaper-price header cannot be assigned to an individual flight. The third HAR contains the homepage, assets and autocomplete activity, but no `GetShoppingResults` record.

## Live checks

All live checks used separate headless Chrome contexts. No desktop access, open-browser connection, profile reuse, captured cookies or authentication replay was used.

The following paths did not produce a numeric Singapore-only quote:

- Direct provider URLs, including normalized Google-compatible protobuf fields.
- Best, expanded Best, Cheapest and expanded Cheapest.
- Singapore filters encoded into the query and selected through Google's own controls.
- The supplied Google Flights homepage, selecting SFO/DAC and dates through the native form.
- The San Francisco city selector used in the captured request, followed by the same dates and Singapore filter.

For the native city-origin check, the main shopping filters matched the second HAR exactly. Expanded Cheapest also used the same four mode flags, `[0, 1, 0, 2]`, as the recorded priced response. Its Singapore price fields nevertheless remained empty. This comparison covers search filters and mode flags, not every piece of page or session context. Some other runs returned a Google RPC error despite HTTP 200; those are provider failures, not successful empty fare searches.

Selecting the 23-hour Singapore outbound and 21-hour-55-minute return reached **Booking options**. Google displayed:

> Price hidden because it might be incorrect

It offered “Visit site for price.” The collected booking response did not expose a numeric fare in its decoded JSON fields; its numeric values described the itinerary. This establishes an explicit price-suppression state for this live selected pair. It does not establish why the captured Cheapest search received prices or prove that all Singapore fares are suppressed.

## What is ruled out and what remains open

The recorded priced payload is readable by our existing decoder. Pagination alone, an incorrect airline-filter selector, and the generated URL alone do not explain the live gap.

An initial user report of a signed-out failure was corrected: that check used SJC rather than SFO. The subsequent Incognito screenshots show SFO/DAC and the matching dates: Best has unpriced rows, while Cheapest has individual Singapore quotes of $1,039 and $1,258, including the 23-hour itinerary. **Sign-in is therefore not required for the observed priced result.** The exact server or page-context rule behind the headless difference remains unknown.

Obtaining a live headless quote requires reproducing the priced Google response or finding an independently priced source. Reading the existing priced HAR works offline, but does not provide updated inventory. The alternate order, unfiltered search → Cheapest → airline filter, reached unfiltered Cheapest on retry but stalled after filtering with no numeric Singapore quote. It did not complete the expanded filtered view. A HAR from the priced Incognito **SFO** flow would allow a closer anonymous-to-anonymous comparison than the earlier city-origin capture.

One further independent handoff attempt failed while fetching the selected return, before reaching the airline site. This is a Google return-search failure, not evidence that the airline's website blocks headless searches. An airline-site quote remains unverified.

The REA HAR command failed in its local Swift helper compilation, so these findings come from direct offline HAR decoding and fresh headless Playwright observations. They are not successful REA Evidence results.

Raw HARs and HTML captures stay outside commits; `*.har` is ignored. Captured quotes must stay separate from live fare rankings. The app's provider and browser retry behavior have not changed as a result of this investigation.

Verification: all 93 offline tests pass, including a reconstructed two-leg Cheapest-response test using the real provider parser. The skill validator passes. These checks verify decoding and existing app behavior; they do not establish live Singapore price recovery.
