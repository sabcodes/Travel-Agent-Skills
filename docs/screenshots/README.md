# App screenshots and diagnostic evidence

These PNGs show the local browser app and may be reused to introduce the project.

- `flight-search.png`: destination selection, inclusive vacation length, dates, regular/deep modes, and a network-free search preview.
- `flight-results.png`: an example Cancun/Maui date matrix, lowest qualifying fare, offline filters, and CSV/JSON export. Quotes came from a saved public-provider test captured October 13, 2026 UTC. The image labels them as an example; they are not current offers or guaranteed availability.
- `advanced-options.png`: departure interval, origins, airline/layover filters, optional limits, and the experimental headless retry. This screenshot predates the native Chrome integration.

Captured with headless Playwright against an isolated local app instance, without accessing an existing browser profile or the desktop. The images contain no browser chrome, account information, local paths, or credentials. Raw fare snapshots and browser/network captures are excluded from the repository. PNG metadata and the rendered images were inspected before publication.

When refreshing these images, keep example prices dated and visibly labeled, and match the app's actual behavior. Do not promote the experimental retry as verified airline coverage.

`singapore-native-chrome.png` is separate diagnostic evidence from October 14, 2026. It shows signed-out, automated visible Google Chrome with Singapore Airlines and Cheapest selected for SFO/DAC, January 12-February 13, 2027. Its five Singapore-only outbound rows have quotes starting at $1,067, matched to numeric network results. It contains public flight information and a Sign in button, with no account identity or local paths. This image demonstrates the [isolated prototype](../native-chrome-price-investigation.md), the original prototype before its later Python app integration.

## App recovery, October 15, 2026

`singapore-app-recovery.png` shows the real local app after its separate native Chrome retrieval button recovered five Singapore Airlines quotes for SFO/DAC, January 12–16, 2027. Singapore is applied as a saved-result filter. The lowest qualifying banner, matrix and itinerary table include the recovered quotes with browser provenance. The lowest observed starting quote was $1,573; prices are historical examples, not held tickets or current availability. It contains public fare data and local app controls, with no account/profile information. The optional `ui_native_retry_test.py` reproduces this screen and also tests cancellation.
