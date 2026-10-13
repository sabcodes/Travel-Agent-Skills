# Local flight UI

## Agreed scope

A local browser app with a double-click Mac launcher after one-time Python setup. It supports Intel and Apple Silicon through the installed Python environment. No Node, React build, Electron runtime, hosted service, or travel-account login is required.

The server runs the checked-in `flight_tools.py` CLI as a subprocess using the same Python interpreter. Date generation, live fetching, filters, ranking, and matrix generation remain in the CLI. Live searches remain sequential to preserve the existing provider behavior.

## Search screen

- Searchable multi-select dropdown containing every preset, with select-all and clear actions.
- Add a named location with one or more IATA airports and an optional gateway note. Additions persist locally and do not edit the repository presets.
- Vacation duration in inclusive calendar days, default six.
- Start and end dates, bounding outbound and return departure.
- Regular search maps to lite: every five departure days by default. Deep checks each eligible departure.
- Advanced options: origin airports (SFO default), regular departure spacing, additional trip lengths, optional price ceiling, maximum connections, outbound duration, and connection wait.
- Preview the exact number of airport/date searches without fetching fares.
- Progress counts finished lookups, including source failures. ETA appears after the first lookup and uses average elapsed time; provider retries can change it. Finishing the last lookup is followed by snapshot generation.
- Stop a running search. The first version runs one live search at a time.

## Results

Display the cheapest qualifying fare, the destination/date comparison matrix, and matching itineraries with dates, airline, actual airport, outbound connections, outbound duration, and booking-search links. Preserve explicit partial, unavailable, filtered-out, and empty statuses. Display gateway notes and source failures.

Result filters call the CLI's offline filter against the saved raw snapshot. Clearing a local filter can recover raw fares; it cannot undo a connection restriction used in the live provider query. Filters do not refresh quotes.

Download the currently filtered comparison table as UTF-8 CSV, with status values and best-fare details. Download JSON to retain the raw candidates and replay filters with the CLI. Search results last until the app stops or another search replaces them. There is no searchable history in this version. Refreshing the browser reconnects to the active search or current results.

## Local boundary and verification

Serve only on `127.0.0.1`. Accept fixed API actions and validated arguments; invoke subprocesses without a shell. Validate request host/origin and use a per-process CSRF token for mutations. Serve only the three known static assets. Escape displayed data and spreadsheet formula prefixes in CSV.

Test CLI progress on both successful and failed lookups; validate custom-location persistence and reserved names; exercise real offline CLI filtering/CSV and local HTTP boundaries. Browser-test regular/deep planning, selection, add-location, validation, progress, filtering, downloads, and cancellation. Live-test only two destinations. Intel compatibility is supported by published dependency wheels but requires separate hardware testing for a verified Intel claim.
