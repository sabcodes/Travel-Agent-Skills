# Shareable announcement

We built a deterministic Chrome/CDP prototype that retrieves Singapore Airlines prices when our tested flight-search paths returned flights without fares.

For SFO-Dhaka, it recovered five Singapore-only outbound options with Singapore selected in both directions. Network quotes matched the final Google Flights Cheapest rows. Three fresh sessions passed for January 12-February 13, 2027, starting at $1,067; a five-day January 12-16 search passed, starting at $1,573. Those are observed USD economy round-trip starting quotes from October 14, 2026.

No login, personal browser profile, or agent-driven clicking is required: the experiment runs with CLI commands. We publish the reproducible method, comparison findings, screenshot, and verifier. The verifier rejects header-only amounts, stale/transient prices, wrong dates, and missing return-side airline filters.

The prototype runs in visible installed Chrome on an Apple Silicon Mac, with Python and Node.js 24+. App integration, Intel testing, and native headless mode remain next steps.

[Code, demo and instructions](https://github.com/sabcodes/Travel-Agent-Skills/releases/tag/native-chrome-prototype-2026-10-14).

![Verified automated Singapore pricing](screenshots/singapore-native-chrome.png)

Comparison claims apply to our recorded tests of fast-flights, fli and ordinary Playwright. We have not established an industry-wide ranking or exclusive capability.
