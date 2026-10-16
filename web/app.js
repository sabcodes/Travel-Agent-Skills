"use strict";

const $ = id => document.getElementById(id);
const limitNames = ["max_price", "max_stops", "max_duration_hours", "max_layover_hours", "airlines"];
const selected = new Set(["cancun", "maui"]);
let pool = [];
let polling = null;
let renderedJob = null;
let filterBusy = false;
let submittedSettings = null;
let displayedTripDays = null;
let jobActive = false;
let retryEligible = 0;
let renderedProgress = null;
let displayedJobId = null;

async function api(path, values) {
  const options = values === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content},
    body: JSON.stringify(values)
  };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function showError(error, id = "error") {
  $(id).textContent = error ? error.message || String(error) : "";
  $(id).hidden = !error;
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function money(price) {
  return new Intl.NumberFormat("en-US", {style: "currency", currency: "USD", maximumFractionDigits: 2}).format(price);
}

function dateLabel(date) {
  return new Date(date + "T12:00:00").toLocaleDateString("en-US", {month: "short", day: "numeric"});
}

function bookingLink(fare, text) {
  const link = node("a", text, "fare-link");
  try {
    const url = new URL(fare.booking_url);
    if (url.protocol !== "https:") return node("span", text);
    link.href = url.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = `${fare.airline} · ${fare.origin} → ${fare.destination} · ${fare.stops} outbound connections · ${fare.total_journey_duration}`;
    return link;
  } catch {
    return node("span", text);
  }
}

function filters(prefix) {
  return Object.fromEntries(limitNames.map(key => [key, $(prefix + "-" + key.replaceAll("_", "-")).value]));
}

function query() {
  const duration = $("duration").value;
  return {
    destinations: [...selected], start_date: $("start-date").value, end_date: $("end-date").value,
    trip_lengths: duration,
    mode: document.querySelector('input[name="mode"]:checked').value,
    origin: $("origin").value, date_step_days: $("date-step").value, ...filters("search"),
    browser_missing: $("browser-missing").value === "on", browser_engine: $("browser-engine").value
  };
}

function updateSelection() {
  const names = pool.filter(location => selected.has(location.id)).map(location => location.name);
  $("locations-summary").textContent = names.length === 0 ? "Choose locations" : names.length <= 2 ? names.join(", ") : `${names.length} locations selected`;
  if (names.length) {
    const summary = document.querySelector("#locations-picker > summary");
    summary.classList.remove("invalid");
    summary.removeAttribute("aria-invalid");
  }
  $("plan").textContent = "";
  markSettingsChanged();
}

function renderPicker() {
  const term = $("location-search").value.toLocaleLowerCase();
  const options = $("location-options");
  options.replaceChildren();
  for (const location of [...pool].sort((a, b) => a.name.localeCompare(b.name))) {
    if (!`${location.name} ${location.airports.join(" ")}`.toLocaleLowerCase().includes(term)) continue;
    const label = node("label", undefined, "location-option");
    const input = node("input");
    input.type = "checkbox";
    input.value = location.id;
    input.checked = selected.has(location.id);
    input.addEventListener("change", () => {
      input.checked ? selected.add(location.id) : selected.delete(location.id);
      updateSelection();
    });
    label.append(input, node("span", location.name), node("small", location.airports.join(" / ")));
    if (location.gateway_note) label.title = location.gateway_note;
    options.append(label);
  }
  if (!options.children.length) options.append(node("p", "No matching locations.", "hint"));
  $("pool-count").textContent = `${pool.length} locations`;
  updateSelection();
}

function updateMode() {
  const deep = document.querySelector('input[name="mode"]:checked').value === "deep";
  const fallback = deep ? 1 : $("duration").value;
  const step = $("date-step").value || fallback;
  $("date-step").placeholder = String(fallback || "Vacation length");
  const trip = `${$("duration").value || "—"}-day trips`;
  $("mode-help").textContent = String(step) === "1" ? `${trip} · every departure day.` : `${trip} · departures every ${step || "vacation-length"} days${deep ? " · sampled deep search" : ""}.`;
  $("plan").textContent = "";
  markSettingsChanged();
}

function markSettingsChanged() {
  const changed = submittedSettings !== null && JSON.stringify(query()) !== submittedSettings;
  $("settings-changed").hidden = !changed || $("results").hidden;
  $("settings-changed").textContent = changed ? `Search settings changed. Click Find flights to run the ${$("duration").value || "new"}-day search. The table below is from your previous ${displayedTripDays || "saved"}-day search.` : "";
}

function validateSearch() {
  const missing = [], invalid = [];
  const labels = {duration: "Vacation length", "start-date": "Start date", "end-date": "End date", origin: "Origin airport(s)"};
  const summary = document.querySelector("#locations-picker > summary");
  summary.classList.toggle("invalid", !selected.size);
  if (!selected.size) { missing.push("Locations"); summary.setAttribute("aria-invalid", "true"); }
  else summary.removeAttribute("aria-invalid");
  for (const input of $("search-form").querySelectorAll("input, select")) {
    const bad = !input.validity.valid;
    input.classList.toggle("invalid", bad);
    if (bad) input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
    if (input.required && !input.value.trim()) missing.push(labels[input.id] || input.id);
    else if (bad) invalid.push(input);
  }
  if (missing.length || invalid.length) {
    showError(missing.length ? `Please fill out the required fields: ${missing.join(", ")}.` : "Please check the highlighted fields. Vacation length must be a whole number of at least 2 days; limits must use valid numbers.");
    if (missing.includes("Origin airport(s)")) document.querySelector(".advanced").open = true;
    $("error").scrollIntoView({block: "nearest"});
    return false;
  }
  return true;
}

function seconds(value) {
  const rounded = Math.ceil(value);
  return rounded < 60 ? `${rounded}s` : rounded < 3600 ? `${Math.floor(rounded / 60)}m ${rounded % 60}s` : `${Math.floor(rounded / 3600)}h ${Math.ceil((rounded % 3600) / 60)}m`;
}

function renderProgress(state) {
  const active = state.status === "running";
  const retry = state.kind === "retry_missing";
  jobActive = active;
  $("search-fields").disabled = active;
  for (const control of $("filter-form").querySelectorAll("input, select, button")) control.disabled = active || filterBusy;
  $("retry-missing").disabled = active || filterBusy || !retryEligible;
  $("progress-section").hidden = state.status === "idle";
  $("stop-search").hidden = !active;
  if (active && !state.total) $("progress").removeAttribute("value");
  else $("progress").value = state.total ? state.completed / state.total * 100 : 0;
  $("progress-count").textContent = active && !state.total ? "Preparing the search plan…" : `${state.completed || 0} / ${state.total || 0} ${retry ? "browser retries" : "searches"} · ${seconds(state.elapsed_seconds || 0)} elapsed`;
  const finishing = active && state.total > 0 && state.completed === state.total;
  $("eta").textContent = active ? finishing ? "Building your table…" : state.eta_seconds === null ? "ETA after the first lookup" : `About ${seconds(state.eta_seconds)} left` : "";
  $("current-route").textContent = state.current || "";
  $("progress-title").textContent = (retry ? {running: "Retrieving missing prices", done: "Browser retries complete", partial: "Browser retries complete · some checks failed", cancelled: "Browser retries stopped", error: "Browser retries could not finish"} : {running: "Searching flights", done: "Search complete", partial: "Search complete · some sources failed", cancelled: "Search stopped", error: "Search could not finish"})[state.status] || "Search progress";
  if (active && !state.cancelled) { $("stop-search").disabled = false; $("stop-search").textContent = retry ? "Stop retries" : "Stop search"; }
}

function restoreQuery(values) {
  selected.clear();
  values.destinations.forEach(location => selected.add(location.id));
  $("start-date").value = values.start_date;
  $("end-date").value = values.end_date;
  $("duration").value = values.trip_lengths[0];
  $("browser-missing").value = values.browser_missing ? "on" : "";
  $("browser-engine").value = values.browser_engine || "native-chrome";
  $("origin").value = values.origins.join(", ");
  const defaultStep = values.mode === "deep" ? 1 : values.trip_lengths[0];
  $("date-step").value = values.date_step_days === defaultStep ? "" : values.date_step_days;
  document.querySelector(`input[name="mode"][value="${values.mode}"]`).checked = true;
  for (const key of limitNames) $("search-" + key.replaceAll("_", "-")).value = Array.isArray(values.filters[key]) ? values.filters[key].join(", ") : values.filters[key] ?? "";
  renderPicker();
  updateMode();
}

async function poll(restore = false) {
  clearTimeout(polling);
  try {
    const state = await api("/api/state");
    if (restore && state.query) {
      restoreQuery(state.query);
      submittedSettings = JSON.stringify(query());
    }
    renderProgress(state);
    const resultVersion = `${state.id}:${state.completed}:${state.status}`;
    if (state.kind === "retry_missing" && state.has_result && renderedProgress !== resultVersion) {
      renderResults(await api("/api/result"), restore);
      displayedJobId = state.id;
      renderedProgress = resultVersion;
    }
    if (state.status === "running") {
      polling = setTimeout(poll, 1000);
    } else if ((["done", "partial"].includes(state.status) || state.has_result) && renderedJob !== state.id) {
      const payload = await api("/api/result");
      renderResults(payload, true);
      displayedJobId = state.id;
      renderedJob = state.id;
    }
    if (state.status === "error") showError(new Error(state.error || "The search could not finish. Existing results remain available."));
  } catch (error) {
    showError(new Error(`Cannot reach the local app. Keep its terminal open. ${error.message}`));
    polling = setTimeout(poll, 3000);
  }
}

function tableHead(table, headings) {
  table.replaceChildren();
  const head = node("thead"), row = node("tr"), body = node("tbody");
  for (const heading of headings) {
    const cell = node("th", heading);
    cell.scope = "col";
    row.append(cell);
  }
  head.append(row);
  table.append(head, body);
  return body;
}

function renderResults(payload, setFilters = false) {
  $("results").hidden = false;
  displayedTripDays = payload.query.trip_lengths.join("/");
  markSettingsChanged();
  if (setFilters) {
    const values = payload.applied_filters || payload.query.filters;
    for (const key of limitNames) $("filter-" + key.replaceAll("_", "-")).value = Array.isArray(values[key]) ? values[key].join(", ") : values[key] ?? "";
  }
  const warnings = payload.source_warnings || [];
  const unpricedCarriers = [...new Set(warnings.flatMap(warning => warning.airlines))].sort();
  const carriers = [...new Set([...(payload.raw_flight_deals || payload.flight_deals).flatMap(fare => (fare.airline || "").split(",").map(name => name.trim()).filter(Boolean)), ...unpricedCarriers])].sort();
  $("airline-options").replaceChildren(...carriers.map(carrier => { const option = node("option"); option.value = carrier; return option; }));
  const dateRange = `${payload.query.start_date} – ${payload.query.end_date}`;
  const quoted = payload.checked_at ? new Date(payload.checked_at).toLocaleString() : "not fetched";
  $("result-meta").textContent = `${displayedTripDays}-day trips · ${payload.summary.total_flight_deals} matching fares · ${dateRange} · quoted ${quoted}`;
  const banner = $("best-fare");
  banner.replaceChildren();
  const best = payload.cheapest;
  if (best) {
    const info = node("div", undefined, "best-info");
    info.append(node("p", "LOWEST QUALIFYING FARE"), node("strong", `${best.destination_name || best.destination} · ${best.origin} → ${best.destination}`),
      node("p", `${best.departure_date} → ${best.return_date} · ${best.airline} · ${best.stops === 0 ? "Nonstop" : `${best.stops} outbound connection(s)`} · ${best.total_journey_duration}${best.price_source?.startsWith("google_flights_") ? " · browser quote" : ""}`));
    if (best.gateway_note) info.append(node("p", best.gateway_note));
    banner.append(node("span", money(best.price), "best-price"), info, bookingLink(best, "View flight ↗"));
  } else {
    banner.append(node("strong", payload.source_errors.length ? "No qualifying fares; some source lookups failed." : "No fares match these filters."));
  }
  const restriction = payload.query.filters.max_stops;
  $("provider-limit").hidden = restriction === null;
  $("provider-limit").textContent = `The original live query limited connections to ${restriction}. Clearing filters cannot restore fares excluded by that query.`;
  const statuses = {partial: "Partial", unavailable: "Unavailable", no_matching_fares: "No fares", filtered_out: "Filtered out", planned: "Planned"};
  const matrixBody = tableHead($("matrix"), ["Destination", ...payload.query.date_pairs.map(([d, r]) => `${dateLabel(d)} → ${dateLabel(r)}`), "Best price"]);
  for (const row of payload.matrix) {
    const tr = node("tr"), location = node("th", row.destination_name);
    location.scope = "row";
    location.append(node("span", `${row.origin} → ${row.airports.join(" / ")}`, "subtext"));
    if (row.gateway_note) location.title = row.gateway_note;
    tr.append(location);
    for (const cell of row.cells) {
      const td = node("td");
      td.title = `${cell.departure_date} → ${cell.return_date}`;
      if (cell.cheapest) {
        td.append(bookingLink(cell.cheapest, money(cell.cheapest.price) + (cell.status === "partial" ? " *" : "")));
        if (cell.cheapest.price === row.cheapest?.price) td.className = "winner";
      } else {
        td.append(node("span", statuses[cell.status] || cell.status, "status"));
      }
      tr.append(td);
    }
    const minimum = node("td", undefined, "winner");
    if (row.cheapest) {
      minimum.append(bookingLink(row.cheapest, money(row.cheapest.price)), node("span", `${dateLabel(row.cheapest.departure_date)} → ${dateLabel(row.cheapest.return_date)}`, "subtext"));
    } else minimum.textContent = "—";
    tr.append(minimum);
    matrixBody.append(tr);
  }
  const fareBody = tableHead($("fares"), ["Destination / airports", "Dates", "Price", "Airline", "Outbound connections", "Outbound duration", "Flight"]);
  for (const fare of payload.flight_deals) {
    const tr = node("tr");
    for (const value of [`${fare.destination_name || fare.destination} (${fare.origin} → ${fare.destination})`, `${fare.departure_date} → ${fare.return_date}`, money(fare.price) + (fare.price_source?.startsWith("google_flights_") ? " · browser quote" : ""), fare.airline, fare.stops, fare.total_journey_duration]) tr.append(node("td", value));
    const booking = node("td");
    booking.append(bookingLink(fare, "View ↗"));
    tr.append(booking);
    if (fare.gateway_note) tr.title = fare.gateway_note;
    fareBody.append(tr);
  }
  $("fares-summary").textContent = `${payload.flight_deals.length} matching flights · lowest price first`;
  $("source-errors").hidden = !payload.source_errors.length;
  $("errors-summary").textContent = `${payload.source_errors.length} source lookup(s) failed`;
  $("error-list").replaceChildren(...payload.source_errors.map(error => node("li", `${error.origin} → ${error.destination} · ${error.departure_date}: ${error.message}`)));
  $("unpriced-notice").hidden = !warnings.length;
  $("unpriced-notice").textContent = `Google returned some itineraries without prices for ${unpricedCarriers.join(", ")}. These cannot be compared by price. Open “Itineraries without prices” for dates; check Google Flights or the airline for a quote.`;
  $("source-warnings").hidden = !warnings.length;
  $("warning-list").replaceChildren(...warnings.map(warning => node("li", `${warning.origin} → ${warning.destination} · ${warning.departure_date} → ${warning.return_date} · ${warning.airlines.join(", ")}: price unavailable`)));
  const selectedAirlines = (payload.applied_filters || payload.query.filters).airlines || [];
  const selectedNames = new Set(selectedAirlines.map(name => name.toLocaleLowerCase()));
  const eligible = warnings.filter(warning => warning.airlines.length && (!selectedNames.size || warning.airlines.some(name => selectedNames.has(name.toLocaleLowerCase()))));
  retryEligible = new Set(eligible.map(warning => [warning.origin, warning.destination, warning.departure_date, warning.return_date].join("|"))).size;
  $("retry-missing").disabled = jobActive || filterBusy || !retryEligible;
  $("retry-missing-count").textContent = retryEligible ? `${retryEligible} saved route/date ${retryEligible === 1 ? "check" : "checks"}` : "No missing prices match the applied airline filters.";
  const attempts = payload.browser_attempts || [];
  $("browser-retry-summary").hidden = !payload.query.browser_missing && !attempts.length;
  $("browser-retry-summary").textContent = attempts.length ? `Browser retries: ${attempts.length} date/route checks · ${attempts.reduce((total, attempt) => total + attempt.recovered, 0)} quotes recovered. ${attempts.filter(attempt => attempt.status === "unavailable").length} checks failed or timed out. Unresolved prices remain unavailable.` : "Browser retries were enabled; no eligible unpriced itineraries needed a retry.";
}

$("search-form").addEventListener("submit", async event => {
  event.preventDefault();
  showError(null);
  if (!validateSearch()) return;
  const values = query();
  $("locations-picker").open = false;
  renderProgress({status: "running", completed: 0, total: 0, elapsed_seconds: 0, eta_seconds: null, current: "Preparing your search…"});
  $("stop-search").disabled = true;
  $("stop-search").textContent = "Preparing…";
  $("progress-section").scrollIntoView({block: "start"});
  try {
    const state = await api("/api/search", values);
    submittedSettings = JSON.stringify(values);
    $("results").hidden = true;
    markSettingsChanged();
    $("stop-search").disabled = false;
    $("stop-search").textContent = "Stop search";
    renderProgress(state);
    await poll();
  } catch (error) {
    $("search-fields").disabled = false;
    $("progress-section").hidden = true;
    showError(error);
  }
});

$("preview").addEventListener("click", async () => {
  showError(null);
  if (!validateSearch()) return;
  $("preview").disabled = true;
  try {
    const plan = await api("/api/plan", query());
    $("plan").textContent = `${plan.total} ${plan.total === 1 ? "search" : "searches"} · ${plan.windows} date ${plan.windows === 1 ? "window" : "windows"}`;
  } catch (error) { showError(error); }
  finally { $("preview").disabled = false; }
});

$("stop-search").addEventListener("click", async () => {
  $("stop-search").disabled = true;
  $("stop-search").textContent = "Stopping…";
  try { await api("/api/cancel", {}); await poll(); }
  catch (error) { showError(error); $("stop-search").disabled = false; }
});

$("retry-missing").addEventListener("click", async () => {
  if (jobActive || filterBusy || !retryEligible) return;
  showError(null);
  renderProgress({kind: "retry_missing", status: "running", completed: 0, total: retryEligible, elapsed_seconds: 0, eta_seconds: null, current: "Preparing browser retries…"});
  $("progress-section").scrollIntoView({block: "start"});
  try {
    const state = await api("/api/retry-missing", {browser_engine: $("browser-engine").value, job_id: displayedJobId});
    renderProgress(state);
    await poll();
  } catch (error) { await poll(); showError(error); }
});

async function applyFilters(reset = false) {
  if (filterBusy || jobActive) return;
  filterBusy = true;
  showError(null);
  $("retry-missing").disabled = true;
  $("apply-filters").disabled = $("reset-filters").disabled = true;
  try {
    const values = reset ? {} : filters("filter");
    const payload = await api("/api/filter", values);
    renderResults(payload, reset);
  } catch (error) { showError(error); }
  finally {
    filterBusy = false;
    $("apply-filters").disabled = $("reset-filters").disabled = false;
    $("retry-missing").disabled = jobActive || !retryEligible;
  }
}
$("filter-form").addEventListener("submit", event => { event.preventDefault(); applyFilters(); });
$("reset-filters").addEventListener("click", () => applyFilters(true));
$("location-search").addEventListener("input", renderPicker);
$("select-all").addEventListener("click", () => { pool.forEach(location => selected.add(location.id)); renderPicker(); });
$("clear-locations").addEventListener("click", () => { selected.clear(); renderPicker(); });
document.addEventListener("click", event => { if (!$("locations-picker").contains(event.target)) $("locations-picker").open = false; });
document.addEventListener("keydown", event => { if (event.key === "Escape") $("locations-picker").open = false; });
$("search-form").addEventListener("change", updateMode);
$("search-form").addEventListener("input", event => {
  updateMode();
  if (event.target.validity?.valid) { event.target.classList.remove("invalid"); event.target.removeAttribute("aria-invalid"); }
});
$("add-location").addEventListener("click", () => { $("locations-picker").open = false; showError(null, "location-error"); $("location-dialog").showModal(); });
$("cancel-location").addEventListener("click", () => $("location-dialog").close());
$("location-form").addEventListener("submit", async event => {
  event.preventDefault();
  $("save-location").disabled = true;
  showError(null, "location-error");
  try {
    const location = await api("/api/locations", {name: $("new-name").value, airports: $("new-airports").value, gateway_note: $("new-note").value});
    pool = await api("/api/destinations");
    selected.add(location.id);
    $("location-search").value = "";
    renderPicker();
    $("location-dialog").close();
    $("location-form").reset();
  } catch (error) { showError(error, "location-error"); }
  finally { $("save-location").disabled = false; }
});

async function init() {
  // Start with the next complete month; January searches remain a date choice.
  const now = new Date(), first = new Date(now.getFullYear(), now.getMonth() + 1, 1), last = new Date(now.getFullYear(), now.getMonth() + 2, 0);
  const iso = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  $("start-date").value = iso(first);
  $("end-date").value = iso(last);
  try { pool = await api("/api/destinations"); renderPicker(); updateMode(); await poll(true); }
  catch (error) { showError(error); }
}
init();
