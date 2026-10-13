"use strict";

const $ = id => document.getElementById(id);
const limitNames = ["max_price", "max_stops", "max_duration_hours", "max_layover_hours"];
const selected = new Set(["cancun", "maui"]);
let pool = [];
let polling = null;
let renderedJob = null;
let filterBusy = false;

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
  const extra = $("extra-lengths").value.trim();
  return {
    destinations: [...selected], start_date: $("start-date").value, end_date: $("end-date").value,
    trip_lengths: duration + (extra ? "," + extra : ""),
    mode: document.querySelector('input[name="mode"]:checked').value,
    origin: $("origin").value, date_step_days: $("date-step").value, ...filters("search")
  };
}

function updateSelection() {
  const names = pool.filter(location => selected.has(location.id)).map(location => location.name);
  $("locations-summary").textContent = names.length === 0 ? "Choose locations" : names.length <= 2 ? names.join(", ") : `${names.length} locations selected`;
  $("plan").textContent = "";
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
  $("date-step").disabled = deep;
  $("mode-help").textContent = deep ? "Every eligible departure for each trip length." : `One departure every ${$("date-step").value || 5} days.`;
  $("plan").textContent = "";
}

function seconds(value) {
  const rounded = Math.ceil(value);
  return rounded < 60 ? `${rounded}s` : rounded < 3600 ? `${Math.floor(rounded / 60)}m ${rounded % 60}s` : `${Math.floor(rounded / 3600)}h ${Math.ceil((rounded % 3600) / 60)}m`;
}

function renderProgress(state) {
  const active = state.status === "running";
  $("search-fields").disabled = active;
  $("progress-section").hidden = state.status === "idle";
  $("stop-search").hidden = !active;
  $("progress").value = state.total ? state.completed / state.total * 100 : 0;
  $("progress-count").textContent = `${state.completed || 0} / ${state.total || 0} searches · ${seconds(state.elapsed_seconds || 0)} elapsed`;
  const finishing = active && state.completed === state.total;
  $("eta").textContent = active ? finishing ? "Building your table…" : state.eta_seconds === null ? "ETA after the first lookup" : `About ${seconds(state.eta_seconds)} left` : "";
  $("current-route").textContent = state.current || "";
  $("progress-title").textContent = {running: "Searching flights", done: "Search complete", partial: "Search complete · some sources failed", cancelled: "Search stopped", error: "Search could not finish"}[state.status] || "Search progress";
}

async function poll() {
  clearTimeout(polling);
  try {
    const state = await api("/api/state");
    renderProgress(state);
    if (state.status === "running") {
      polling = setTimeout(poll, 1000);
    } else if (["done", "partial"].includes(state.status) && renderedJob !== state.id) {
      const payload = await api("/api/result");
      renderResults(payload, true);
      renderedJob = state.id;
    } else if (state.status === "error") {
      showError(new Error(state.error));
    }
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
  if (setFilters) {
    const values = payload.applied_filters || payload.query.filters;
    for (const key of limitNames) $("filter-" + key.replaceAll("_", "-")).value = values[key] ?? "";
  }
  const dateRange = `${payload.query.start_date} – ${payload.query.end_date}`;
  const quoted = payload.checked_at ? new Date(payload.checked_at).toLocaleString() : "not fetched";
  $("result-meta").textContent = `${payload.summary.total_flight_deals} matching fares · ${dateRange} · quoted ${quoted}`;
  const banner = $("best-fare");
  banner.replaceChildren();
  const best = payload.cheapest;
  if (best) {
    const info = node("div", undefined, "best-info");
    info.append(node("p", "LOWEST QUALIFYING FARE"), node("strong", `${best.destination_name || best.destination} · ${best.origin} → ${best.destination}`),
      node("p", `${best.departure_date} → ${best.return_date} · ${best.airline} · ${best.stops === 0 ? "Nonstop" : `${best.stops} outbound connection(s)`} · ${best.total_journey_duration}`));
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
    for (const value of [`${fare.destination_name || fare.destination} (${fare.origin} → ${fare.destination})`, `${fare.departure_date} → ${fare.return_date}`, money(fare.price), fare.airline, fare.stops, fare.total_journey_duration]) tr.append(node("td", value));
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
}

$("search-form").addEventListener("submit", async event => {
  event.preventDefault();
  showError(null);
  $("locations-picker").open = false;
  $("search-fields").disabled = true;
  try {
    const state = await api("/api/search", query());
    $("results").hidden = true;
    $("stop-search").disabled = false;
    $("stop-search").textContent = "Stop search";
    renderProgress(state);
    await poll();
  } catch (error) {
    $("search-fields").disabled = false;
    showError(error);
  }
});

$("preview").addEventListener("click", async () => {
  if (!$("search-form").reportValidity()) return;
  showError(null);
  $("preview").disabled = true;
  try {
    const plan = await api("/api/plan", query());
    $("plan").textContent = `${plan.total} searches · ${plan.windows} date windows`;
  } catch (error) { showError(error); }
  finally { $("preview").disabled = false; }
});

$("stop-search").addEventListener("click", async () => {
  $("stop-search").disabled = true;
  $("stop-search").textContent = "Stopping…";
  try { await api("/api/cancel", {}); await poll(); }
  catch (error) { showError(error); $("stop-search").disabled = false; }
});

async function applyFilters(reset = false) {
  if (filterBusy) return;
  filterBusy = true;
  showError(null);
  $("apply-filters").disabled = $("reset-filters").disabled = true;
  try {
    const values = reset ? {} : filters("filter");
    const payload = await api("/api/filter", values);
    renderResults(payload, reset);
  } catch (error) { showError(error); }
  finally {
    filterBusy = false;
    $("apply-filters").disabled = $("reset-filters").disabled = false;
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
$("search-form").addEventListener("input", () => { $("plan").textContent = ""; });
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
  try { pool = await api("/api/destinations"); renderPicker(); updateMode(); await poll(); }
  catch (error) { showError(error); }
}
init();
