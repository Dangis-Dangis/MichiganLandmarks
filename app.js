/* Michigan Landmarks - app UI (bundled in the Capacitor Android app).
 * Loads the lightweight index up front, renders a clustered map + a list, and
 * lazy-loads full per-record details on demand. Pure vanilla JS + MapLibre GL.
 */
"use strict";

const DATA_BASE = "./data/";
const INDEX_URL = DATA_BASE + "landmarks.index.json";
const MAP_STYLE = "https://tiles.openfreemap.org/styles/positron";
const MICHIGAN_CENTER = [-85.6, 44.8];

const CATEGORIES = [
  { id: "lighthouse", label: "Lighthouses", color: "#1f77b4", emoji: "\uD83D\uDDFC" },
  { id: "historical_marker", label: "Historical markers", color: "#2ca02c", emoji: "\uD83E\uDEA7" },
  { id: "nrhp_site", label: "Historic places (NRHP)", color: "#9467bd", emoji: "\uD83C\uDFDB\uFE0F" },
  { id: "state_park", label: "State parks", color: "#ff7f0e", emoji: "\uD83C\uDF32" },
  { id: "national_park_unit", label: "National parks", color: "#8c564b", emoji: "\u26F0\uFE0F" },
  { id: "museum", label: "Museums", color: "#e377c2", emoji: "\uD83C\uDFA8" },
];
const CAT_BY_ID = Object.fromEntries(CATEGORIES.map((c) => [c.id, c]));

const state = {
  all: [],
  filtered: [],
  origin: null, // {lat, lon} for distance sort
  activeCategories: new Set(CATEGORIES.map((c) => c.id)),
  sort: "name",
  withImageOnly: false,
  hideLocalityPins: false,
  query: "",
  view: "map",
  map: null,
  mapReady: false,
  originMarker: null,
  detailSeq: 0,
  generated: null,
};

const $ = (sel) => document.querySelector(sel);

function showStatus(msg, ms) {
  const el = $("#status");
  el.textContent = msg;
  el.classList.remove("hidden");
  if (ms) setTimeout(() => el.classList.add("hidden"), ms);
}
function hideStatus() { $("#status").classList.add("hidden"); }

function haversineKm(a, b) {
  const R = 6371;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLon = ((b.lon - a.lon) * Math.PI) / 180;
  const la1 = (a.lat * Math.PI) / 180;
  const la2 = (b.lat * Math.PI) / 180;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
function fmtDist(km) {
  const mi = km * 0.621371;
  return mi < 10 ? mi.toFixed(1) + " mi" : Math.round(mi) + " mi";
}

/* -------------------------------------------------------------------------- */
/* Data loading                                                                */
/* -------------------------------------------------------------------------- */
async function loadIndex() {
  showStatus("Loading landmarks\u2026");
  const res = await fetch(INDEX_URL);
  if (!res.ok) throw new Error("index fetch failed: " + res.status);
  const data = await res.json();
  state.all = data.landmarks || [];
  state.generated = data.generated || null;
  hideStatus();
}

const detailCache = new Map();
async function loadDetail(record) {
  if (detailCache.has(record.id)) return detailCache.get(record.id);
  const res = await fetch(DATA_BASE + record.detail_file);
  if (!res.ok) throw new Error("detail fetch failed");
  const data = await res.json();
  detailCache.set(record.id, data);
  return data;
}

/* -------------------------------------------------------------------------- */
/* Filtering + sorting                                                         */
/* -------------------------------------------------------------------------- */
function applyFilters() {
  const q = state.query.trim().toLowerCase();
  let items = state.all.filter((lm) => {
    if (!categoryMatches(lm)) return false;
    if (state.withImageOnly && !lm.image_url) return false;
    if (state.hideLocalityPins && locationQuality(lm) === "locality") return false;
    if (q) {
      const hay = (lm.name + " " + (lm.county || "") + " " + (lm.summary || "")).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  if (state.sort === "distance" && state.origin) {
    items.forEach((lm) => { lm._dist = haversineKm(state.origin, { lat: lm.latitude, lon: lm.longitude }); });
    items.sort((a, b) => a._dist - b._dist);
  } else if (state.sort === "name" || (state.sort === "distance" && !state.origin)) {
    items.sort((a, b) => a.name.localeCompare(b.name));
  } else if (state.sort === "year_desc") {
    items.sort((a, b) => (b.year || -1e9) - (a.year || -1e9));
  } else if (state.sort === "year_asc") {
    items.sort((a, b) => (a.year || 1e9) - (b.year || 1e9));
  } else if (state.origin) {
    items.forEach((lm) => { lm._dist = haversineKm(state.origin, { lat: lm.latitude, lon: lm.longitude }); });
  }

  state.filtered = items;
  $("#resultCount").textContent = items.length.toLocaleString() + " of " +
    state.all.length.toLocaleString() + " shown";
  updateMapData();
  updateSearchHint();
  fitMapToSearchHits();
  updateFilterChrome();
  if (state.view === "list") renderList();
}

function updateSearchHint() {
  const el = $("#searchHint");
  if (!el) return;
  const q = state.query.trim();
  if (!q) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.classList.remove("hidden");
  const n = state.filtered.length;
  el.textContent = n === 0
    ? "No results found"
    : (n === 1 ? "1 landmark found" : n.toLocaleString() + " landmarks found");
}

function fitMapToSearchHits() {
  if (!state.query.trim()) return;
  if (!state.map || !state.mapReady) return;
  const items = state.filtered;
  if (!items.length) return;
  const bounds = new maplibregl.LngLatBounds();
  items.forEach((lm) => bounds.extend([lm.longitude, lm.latitude]));
  state.map.fitBounds(bounds, {
    padding: { top: 72, bottom: 48, left: 40, right: 40 },
    maxZoom: 14,
    duration: 700,
  });
}

/* -------------------------------------------------------------------------- */
/* Map                                                                         */
/* -------------------------------------------------------------------------- */
function toFeatureCollection(items) {
  return {
    type: "FeatureCollection",
    features: items.map((lm) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lm.longitude, lm.latitude] },
      properties: { id: lm.id, category: lm.category },
    })),
  };
}

/** Invisible tap target radius (~44 px diameter). Visual dots stay small. */
const POINT_HIT_RADIUS = 22;

function dist2ToPoint(map, feature, point) {
  const [lng, lat] = feature.geometry.coordinates;
  const px = map.project([lng, lat]);
  const dx = px.x - point.x;
  const dy = px.y - point.y;
  return dx * dx + dy * dy;
}

function nearestFeatureAt(map, features, point) {
  if (!features.length) return null;
  if (features.length === 1) return features[0];
  return features.reduce((best, f) =>
    dist2ToPoint(map, f, point) < dist2ToPoint(map, best, point) ? f : best
  );
}

function openLandmarkFromFeatures(map, features, point) {
  const hit = nearestFeatureAt(map, features, point);
  if (!hit) return;
  const rec = state.all.find((x) => x.id === hit.properties.id);
  if (rec) openDetail(rec);
}

function initMap() {
  let map;
  try {
    map = new maplibregl.Map({
      container: "map",
      style: MAP_STYLE,
      center: MICHIGAN_CENTER,
      zoom: 6,
      attributionControl: true,
    });
  } catch (e) {
    showStatus("Map failed to load; list view still works.", 4000);
    return;
  }
  state.map = map;
  map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "bottom-right");

  const colorMatch = ["match", ["get", "category"]];
  CATEGORIES.forEach((c) => colorMatch.push(c.id, c.color));
  colorMatch.push("#555");

  map.on("load", () => {
    state.mapReady = true;
    // All points rendered directly (no clustering) with zoom-scaled radius, so
    // landmarks are always visible. ~3.3k circles render fine.
    map.addSource("landmarks", {
      type: "geojson",
      data: toFeatureCollection(state.filtered),
    });

    map.addLayer({
      id: "points", type: "circle", source: "landmarks",
      paint: {
        "circle-color": colorMatch,
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 2.5, 7, 4, 11, 6.5, 15, 9],
        "circle-stroke-width": 1, "circle-stroke-color": "#fff", "circle-stroke-opacity": 0.9,
      },
    });

    map.addLayer({
      id: "points-hit", type: "circle", source: "landmarks",
      paint: { "circle-radius": POINT_HIT_RADIUS, "circle-opacity": 0 },
    });

    map.on("click", "points-hit", (e) => openLandmarkFromFeatures(map, e.features, e.point));
    map.on("click", (e) => {
      if (!map.getLayer("points-hit")) return;
      const hits = map.queryRenderedFeatures(e.point, { layers: ["points-hit"] });
      if (!hits.length) closeDetail();
    });
    map.on("mouseenter", "points-hit", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "points-hit", () => (map.getCanvas().style.cursor = ""));
  });

  map.on("error", () => {});
}

function updateMapData() {
  if (state.mapReady && state.map && state.map.getSource("landmarks")) {
    state.map.getSource("landmarks").setData(toFeatureCollection(state.filtered));
  }
}

/* -------------------------------------------------------------------------- */
/* List view                                                                   */
/* -------------------------------------------------------------------------- */
function renderList() {
  const root = $("#listView");
  const items = state.filtered.slice(0, 500); // cap DOM for performance
  const frag = document.createDocumentFragment();
  items.forEach((lm) => {
    const cat = CAT_BY_ID[lm.category];
    const card = document.createElement("div");
    card.className = "list-card";
    const thumb = lm.image_url
      ? `<img class="list-thumb" loading="lazy" src="${escapeAttr(lm.image_url)}" alt="" onerror="this.style.display='none'"/>`
      : `<div class="list-thumb placeholder">${cat ? cat.emoji : "\uD83D\uDCCD"}</div>`;
    const dist = lm._dist != null ? `<span class="list-dist">${fmtDist(lm._dist)}</span>` : "";
    const quality = locationQuality(lm);
    const approx = quality && quality !== "site"
      ? `<span class="approx-badge" title="Approximate location">approx. location</span>`
      : "";
    card.innerHTML = `${thumb}
      <div class="list-main">
        <p class="list-name">${escapeHtml(lm.name)}</p>
        <div class="list-meta">
          ${categoryPillsHtml(lm)}
          ${lm.year ? `<span>${lm.year}</span>` : ""}
          ${lm.county ? `<span>${escapeHtml(lm.county)} Co.</span>` : ""}
          ${approx}
          ${dist}
        </div>
      </div>`;
    card.addEventListener("click", () => {
      openDetail(lm);
      if (state.map) state.map.flyTo({ center: [lm.longitude, lm.latitude], zoom: 13 });
    });
    frag.appendChild(card);
  });
  root.innerHTML = items.length
    ? ""
    : `<p class="muted" style="padding:16px">${state.query.trim() ? "No results found" : "No landmarks match your filters."}</p>`;
  root.appendChild(frag);
  if (state.filtered.length > items.length) {
    const more = document.createElement("p");
    more.className = "muted";
    more.style.padding = "8px 16px";
    more.textContent = `Showing first ${items.length}. Narrow filters or search to see more.`;
    root.appendChild(more);
  }
}

/* -------------------------------------------------------------------------- */
/* Detail panel                                                                */
/* -------------------------------------------------------------------------- */
async function openDetail(record) {
  const seq = ++state.detailSeq;
  const panel = $("#detailPanel");
  const body = $("#detailBody");
  body.innerHTML = '<p class="muted">Loading\u2026</p>';
  body.scrollTop = 0;
  panel.classList.remove("hidden", "detail-expanded");

  let d;
  try {
    d = await loadDetail(record);
  } catch (e) {
    d = record; // fall back to index fields when offline and uncached
  }
  if (seq !== state.detailSeq) return;

  const datesBlock = datesRecognitionsHtml(d);
  const dateLabel = !datesBlock.hasBlock && d.date_type && d.year
    ? `${capitalize(d.date_type)} ${d.year}`
    : (!datesBlock.hasBlock && d.year ? String(d.year) : "");
  const text = (d.attributes && d.attributes.marker_text) || d.description || "";
  const plaque = plaqueHtml(text);
  const official = isVenueOfficialUrl(d.official_url) ? d.official_url : "";
  const wiki = wikipediaUrl(d);
  const nara = d.attributes && d.attributes.nara_url;

  const facts = [];
  if (official) {
    facts.push(factButton("Official website", factHostLabel(official), official, "globe"));
  }
  if (wiki) {
    facts.push(factButton("Wikipedia", "Wikipedia article", wiki, "wiki"));
  }
  if (nara) {
    facts.push(factButton("Nomination", "National Archives", nara, "archive"));
  }
  const webQ = webSearchQuery(d);
  if (webQ) {
    facts.push(factButton(
      "Search the web",
      webQ,
      "https://www.google.com/search?q=" + encodeURIComponent(webQ),
      "search",
    ));
  }
  sourceDataFacts(d).forEach((row) => facts.push(row));

  const descCredit = descriptionAttribution(d);
  const locWarn = locationWarningHtml(d, record);

  body.innerHTML = `
    ${d.image_url ? `<img class="detail-img" src="${escapeAttr(d.image_url)}" alt="" onerror="this.style.display='none'"/>` : ""}
    <h2 class="detail-title">${escapeHtml(d.name)}</h2>
    <div class="detail-sub">
      ${categoryPillsHtml(d)}
      ${d.subtype ? `<span>${escapeHtml(d.subtype)}</span>` : ""}
      ${dateLabel ? `<span>${escapeHtml(String(dateLabel))}</span>` : ""}
      ${d.county ? `<span>${escapeHtml(d.county)} County</span>` : ""}
    </div>
    ${datesBlock.html ? `<div class="detail-meta-block">${datesBlock.html}</div>` : ""}
    ${locWarn}
    ${plaque}
    ${descCredit}
    ${addressRowHtml(d)}
    ${mapsActionRowsHtml(d)}
    ${facts.length ? `<div class="detail-facts">${facts.join("")}</div>` : ""}
    ${d.image_credit ? `<p class="detail-credit">Photo: ${escapeHtml(d.image_credit)}${d.image_license ? " (" + escapeHtml(d.image_license) + ")" : ""}</p>` : ""}
    ${sourcesHtml(d)}
    <p class="detail-credit"><a href="#wiki/legal">Legal, privacy &amp; sources</a> \u00b7 Unofficial app, not affiliated with Michigan DNR or NPS.</p>
  `;
}

function closeDetail() {
  const panel = $("#detailPanel");
  panel.classList.add("hidden");
  panel.classList.remove("detail-expanded");
}

function locationQuality(d, record) {
  const q = (d && d.location_quality) || (record && record.location_quality);
  if (q === "site" || q === "name" || q === "locality") return q;
  const attrs = (d && d.attributes) || {};
  const via = attrs.geocode_via;
  const prec = attrs.geocode_precision;
  if (via === "nominatim_city" || prec === "locality" || prec === "city") return "locality";
  if (via === "nominatim_name" || prec === "name") return "name";
  return null;
}

function locationWarningHtml(d, record) {
  const q = locationQuality(d, record);
  if (q === "locality") {
    return `<p class="location-warning" role="status">Location is approximate — the pin is the city, township, or county, not the building.</p>`;
  }
  if (q === "name") {
    return `<p class="location-warning location-warning-mild" role="status">Location is approximate — geocoded from the name and may be off the building.</p>`;
  }
  return "";
}

// Keep in sync with pipeline/plaque.py (split rules + English function-word list).
const EN_FUNCTION_WORDS = new Set([
  "the", "of", "and", "to", "in", "a", "is", "was", "for", "that",
  "with", "as", "on", "by", "from", "this", "were", "are", "at",
  "which", "its", "his", "her", "their", "been", "had", "have",
  "has", "or", "an",
]);

function plaqueWords(text) {
  return (String(text || "").match(/[A-Za-z']+/g) || []).map((w) => w.toLowerCase());
}

function isSameAsFrontStub(text) {
  const t = String(text || "").trim();
  if (!/^(?:[\s\S]*\n)?same(?:\s+text)?(?:\s+as(?:\s+the)?\s+front)?\.?\s*$/i.test(t)) {
    return false;
  }
  return plaqueWords(t).length < 24;
}

function looksEnglishPlaque(text) {
  const words = plaqueWords(text);
  if (words.length < 24) return true;
  const hits = words.filter((w) => EN_FUNCTION_WORDS.has(w)).length;
  return hits >= 4 && hits / words.length >= 0.08;
}

function splitPlaqueText(text) {
  const raw = String(text || "").trim();
  if (!raw) return { english: "", other: "" };
  const sides = raw.split(/\n\n+/).map((s) => s.trim()).filter(Boolean);
  const english = [];
  const other = [];
  sides.forEach((side) => {
    if (isSameAsFrontStub(side)) return;
    if (looksEnglishPlaque(side)) english.push(side);
    else other.push(side);
  });
  if (!english.length) return { english: raw, other: "" };
  return { english: english.join("\n\n"), other: other.join("\n\n") };
}

function plaqueHtml(text) {
  const { english, other } = splitPlaqueText(text);
  if (!english) {
    return '<p class="muted">No description available for this record yet.</p>';
  }
  let html = `<div class="detail-text">${escapeHtml(english)}</div>`;
  if (other) {
    html += `<details class="detail-plaque-other">
      <summary>Also inscribed on the marker</summary>
      <div class="detail-text">${escapeHtml(other)}</div>
    </details>`;
  }
  return html;
}

function descriptionAttribution(d) {
  const src = d.attributes && d.attributes.description_source;
  const lic = d.attributes && d.attributes.description_license;
  const wiki = wikipediaUrl(d);
  if (src === "Wikipedia" && wiki) {
    return `<p class="detail-credit">Description from <a href="${escapeHtml(wiki)}" target="_blank" rel="noopener">Wikipedia</a> (${escapeHtml(lic || "CC BY-SA 4.0")})</p>`;
  }
  if (src && lic) {
    return `<p class="detail-credit">Description: ${escapeHtml(src)} (${escapeHtml(lic)})</p>`;
  }
  return "";
}

/* -------------------------------------------------------------------------- */
/* UI wiring                                                                    */
/* -------------------------------------------------------------------------- */
function buildFilterUI() {
  const catRoot = $("#categoryFilters");
  CATEGORIES.forEach((c) => {
    const label = document.createElement("label");
    label.className = "checkbox";
    label.innerHTML = `<input type="checkbox" value="${c.id}" checked />
      <span class="swatch" style="background:${c.color}"></span>${c.label}`;
    label.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) state.activeCategories.add(c.id);
      else state.activeCategories.delete(c.id);
      applyFilters();
    });
    catRoot.appendChild(label);
  });
}

function showAllFilters() {
  state.activeCategories = new Set(CATEGORIES.map((c) => c.id));
  $("#categoryFilters").querySelectorAll("input[type=checkbox]").forEach((el) => {
    el.checked = true;
  });
  applyFilters();
}

function hideAllFilters() {
  state.activeCategories = new Set();
  $("#categoryFilters").querySelectorAll("input[type=checkbox]").forEach((el) => {
    el.checked = false;
  });
  applyFilters();
}

function updateFilterChrome() {
  const showAll = $("#filtersShowAll");
  const hideAll = $("#filtersHideAll");
  if (!showAll || !hideAll) return;
  const allOn = CATEGORIES.every((c) => state.activeCategories.has(c.id));
  showAll.disabled = allOn;
  hideAll.disabled = state.activeCategories.size === 0;
  const photo = $("#withImageOnly");
  const locality = $("#hideLocalityPins");
  if (photo && photo.closest("label")) {
    photo.closest("label").classList.toggle("active", state.withImageOnly);
  }
  if (locality && locality.closest("label")) {
    locality.closest("label").classList.toggle("active", state.hideLocalityPins);
  }
  const nonDefault = !allOn || state.withImageOnly || state.hideLocalityPins;
  $("#menuToggle").classList.toggle("has-filters", nonDefault);
}

function setView(view) {
  state.view = view;
  $("#map").classList.toggle("hidden", view !== "map");
  $("#listView").classList.toggle("hidden", view !== "list");
  if (view === "list") renderList();
  else if (state.map) state.map.resize();
}

function setFiltersOpen(open) {
  $("#filters").classList.toggle("hidden", !open);
  $("#filtersBackdrop").classList.toggle("hidden", !open);
  $("#menuToggle").setAttribute("aria-expanded", open ? "true" : "false");
}

function wireEvents() {
  $("#menuToggle").addEventListener("click", () => {
    setFiltersOpen($("#filters").classList.contains("hidden"));
  });
  $("#filtersClose").addEventListener("click", () => setFiltersOpen(false));
  $("#filtersShowAll").addEventListener("click", showAllFilters);
  $("#filtersHideAll").addEventListener("click", hideAllFilters);
  $("#filtersBackdrop").addEventListener("click", () => setFiltersOpen(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#filters").classList.contains("hidden")) {
      setFiltersOpen(false);
    }
  });
  $("#viewToggle").addEventListener("click", () => setView(state.view === "map" ? "list" : "map"));
  $("#detailClose").addEventListener("click", closeDetail);
  wireSheetGestures();
  $("#detailBody").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    e.preventDefault();
    const text = btn.getAttribute("data-copy") || "";
    if (!text) return;
    const done = () => showStatus("Copied address", 1500);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => {
        fallbackCopy(text);
        done();
      });
    } else {
      fallbackCopy(text);
      done();
    }
  });
  $("#sortSelect").value = state.sort;
  $("#sortSelect").addEventListener("change", (e) => { state.sort = e.target.value; applyFilters(); });
  $("#withImageOnly").addEventListener("change", (e) => { state.withImageOnly = e.target.checked; applyFilters(); });
  $("#hideLocalityPins").addEventListener("change", (e) => { state.hideLocalityPins = e.target.checked; applyFilters(); });

  let debounce;
  const input = $("#searchInput");
  input.addEventListener("input", (e) => {
    state.query = e.target.value;
    clearTimeout(debounce);
    debounce = setTimeout(applyFilters, 180);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    clearTimeout(debounce);
    state.query = input.value;
    applyFilters();
    input.blur();
  });
  $("#searchClear").addEventListener("click", () => {
    input.value = ""; state.query = ""; applyFilters(); input.focus();
  });

  $("#aboutBtn").addEventListener("click", () => {
    if (window.Wiki && window.Wiki.isOpen() && (!location.hash || location.hash === "#wiki")) {
      window.Wiki.close();
      return;
    }
    if (window.Wiki) window.Wiki.open("home");
  });

  $("#locateBtn").addEventListener("click", async () => {
    showStatus("Locating you\u2026");
    try {
      const pos = await getPosition();
      state.origin = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      state.sort = "distance";
      const distOpt = $("#sortSelect").querySelector('option[value="distance"]');
      if (distOpt) distOpt.disabled = false;
      $("#sortSelect").value = "distance";
      if (state.map) {
        state.map.flyTo({ center: [state.origin.lon, state.origin.lat], zoom: 11 });
        if (state.originMarker) state.originMarker.remove();
        state.originMarker = new maplibregl.Marker({ color: "#0b3d2e" })
          .setLngLat([state.origin.lon, state.origin.lat])
          .addTo(state.map);
      }
      applyFilters();
      showStatus("Sorted by distance from you.", 2500);
    } catch (err) {
      const msg = err && err.message ? String(err.message).toLowerCase() : "";
      showStatus(msg.includes("denied") || msg.includes("permission")
        ? "Location permission denied. Enable it in app settings."
        : msg.includes("disabled") || msg.includes("unavailable")
          ? "Location services are off. Turn them on in device settings."
          : "Could not get your location.", 3500);
    }
  });
}

/* -------------------------------------------------------------------------- */
/* Helpers + bootstrap                                                          */
/* -------------------------------------------------------------------------- */
// Resolve the device position. In the native app, use the Capacitor Geolocation
// plugin (it requests the Android runtime permission); on the web, fall back to
// the browser API.
async function getPosition() {
  const cap = window.Capacitor;
  const native = cap && typeof cap.isNativePlatform === "function" && cap.isNativePlatform();
  // Reach the native plugin via registerPlugin (works without a JS bundler;
  // cap.Plugins.Geolocation is only populated when the wrapper is imported).
  const Geo = native && typeof cap.registerPlugin === "function"
    ? cap.registerPlugin("Geolocation")
    : null;
  if (Geo) {
    try {
      const perm = await Geo.requestPermissions({ permissions: ["location"] });
      const permState = perm && (perm.location || perm.coarseLocation);
      if (permState && permState !== "granted" && permState !== "prompt") {
        throw new Error("denied");
      }
    } catch (e) {
      if (e && e.message === "denied") throw e;
      // some versions don't return a usable object; let getCurrentPosition decide
    }
    return Geo.getCurrentPosition({ enableHighAccuracy: true, timeout: 10000 });
  }
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("unsupported"));
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true, timeout: 10000,
    });
  });
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function escapeAttr(s) { return escapeHtml(s); }
function capitalize(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

function categoryMatches(lm) {
  if (state.activeCategories.has(lm.category)) return true;
  for (const t of lm.tags || []) {
    if (t.startsWith("also_") && state.activeCategories.has(t.slice(5))) return true;
  }
  return false;
}

function urlHost(url) {
  try { return new URL(url).hostname.toLowerCase(); } catch (e) { return ""; }
}

function isEncyclopediaUrl(url) {
  const h = urlHost(url);
  return h.endsWith("wikipedia.org") || h.endsWith("wikimedia.org");
}

function isNaraUrl(url) {
  const h = urlHost(url);
  return h.endsWith("archives.gov") || h.endsWith("nara.gov");
}

function isVenueOfficialUrl(url) {
  if (!url || !/^https?:\/\//i.test(url)) return false;
  if (isEncyclopediaUrl(url) || isNaraUrl(url)) return false;
  const lower = url.toLowerCase();
  const h = urlHost(url);
  if (!h) return false;
  if (h.includes("arcgis.com") && (lower.includes("/query") || lower.includes("/featureserver"))) return false;
  if (h.endsWith("imls.gov") && lower.endsWith(".zip")) return false;
  return true;
}

function isStreetAddress(address) {
  if (!address) return false;
  const s = String(address).trim();
  if (!s || /^(MI|MICHIGAN|USA|US)$/i.test(s)) return false;
  return /^\d+\s/.test(s);
}

function streetAddressLine(d) {
  if (!isStreetAddress(d.address)) return "";
  let line = d.address.trim();
  if (d.city && line.toLowerCase().indexOf(d.city.toLowerCase()) === -1) line += ", " + d.city;
  if (!/\bMI\b/i.test(line)) line += ", MI";
  return line;
}

function nameAddressQuery(d) {
  const name = (d.name || "").trim();
  const street = isStreetAddress(d.address) ? d.address.trim() : "";
  const city = (d.city || "").trim();
  const parts = [];
  if (name) parts.push(name);
  if (street) parts.push(street);
  if (city && (!street || street.toLowerCase().indexOf(city.toLowerCase()) === -1)) parts.push(city);
  if (parts.length >= 2) {
    const q = parts.join(", ");
    return /\bMI\b/i.test(q) ? q : q + ", MI";
  }
  if (name && d.county) return name + ", " + d.county + " County, MI";
  return "";
}

function mapsDestinations(d) {
  const dests = [];
  if (d.latitude != null && d.longitude != null) {
    dests.push({ short: "GPS coordinates", query: String(d.latitude) + "," + String(d.longitude) });
  }
  const named = nameAddressQuery(d);
  if (named) dests.push({ short: "Name + address", query: named });
  const addr = streetAddressLine(d);
  if (addr) dests.push({ short: "Address", query: addr });
  return dests;
}

function mapsSearchUrlFor(query) {
  return "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(query);
}

function mapsDirectionsUrlFor(query) {
  return "https://www.google.com/maps/dir/?api=1&destination=" + encodeURIComponent(query);
}

function mapsActionRowsHtml(d) {
  const dests = mapsDestinations(d);
  if (!dests.length) return "";
  function row(label, urlFn) {
    const chips = dests.map((dest) =>
      `<a class="dest-chip" href="${escapeAttr(urlFn(dest.query))}" target="_blank" rel="noopener">${escapeHtml(dest.short)}</a>`
    ).join("");
    return `<div class="maps-row"><div class="maps-row-label">${escapeHtml(label)}</div><div class="maps-row-dests">${chips}</div></div>`;
  }
  return `<div class="maps-actions">${row("Open in Maps", mapsSearchUrlFor)}${row("Directions to location", mapsDirectionsUrlFor)}</div>`;
}

function addressRowHtml(d) {
  const addr = streetAddressLine(d);
  if (!addr) return "";
  return `<div class="address-row">
    <a class="address-text" href="${escapeAttr(mapsSearchUrlFor(addr))}" target="_blank" rel="noopener">${escapeHtml(addr)}</a>
    <button type="button" class="address-copy" data-copy="${escapeAttr(addr)}" aria-label="Copy address">${iconSvg("copy")}</button>
  </div>`;
}

function fallbackCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); } catch (e) { /* ignore */ }
  document.body.removeChild(ta);
}

function isMobileSheet() {
  return window.matchMedia("(max-width: 719px)").matches;
}

function wireSheetGestures() {
  const panel = $("#detailPanel");
  const body = $("#detailBody");
  if (!panel || !body) return;
  let startY = 0;
  let tracking = false;

  panel.addEventListener("touchstart", (e) => {
    if (!isMobileSheet() || panel.classList.contains("hidden")) return;
    const t = e.changedTouches[0];
    const onHandle = e.target.closest("#detailHandle");
    const expanded = panel.classList.contains("detail-expanded");
    if (onHandle || !expanded || body.scrollTop <= 0) {
      tracking = true;
      startY = t.clientY;
    } else {
      tracking = false;
    }
  }, { passive: true });

  panel.addEventListener("touchend", (e) => {
    if (!tracking) return;
    tracking = false;
    if (!isMobileSheet() || panel.classList.contains("hidden")) return;
    const dy = e.changedTouches[0].clientY - startY;
    const expanded = panel.classList.contains("detail-expanded");
    if (dy > 56) {
      if (expanded) panel.classList.remove("detail-expanded");
      else closeDetail();
    } else if (dy < -56) {
      panel.classList.add("detail-expanded");
    }
  }, { passive: true });
}

function wikipediaUrl(d) {
  const fromAttr = d.attributes && d.attributes.wikipedia_url;
  if (fromAttr && !isMuseumListUrl(fromAttr)) return fromAttr;
  if (d.official_url && isEncyclopediaUrl(d.official_url) && !isMuseumListUrl(d.official_url)) {
    return d.official_url;
  }
  return "";
}

function isMuseumListUrl(url) {
  const path = (url || "").split("?")[0];
  return /\/wiki\/List_of_museums_in_Michigan\/?$/i.test(path);
}

function sourceDataUrl(d) {
  if (!d.source_url || isMuseumListUrl(d.source_url)) return "";
  return d.source_url;
}

function sourceDataFacts(d) {
  const seen = new Set();
  const rows = [];
  function add(url) {
    if (!url || isMuseumListUrl(url) || seen.has(url)) return;
    seen.add(url);
    rows.push(factButton("Source data", factHostLabel(url), url, "source"));
  }
  const listed = (d.attributes && d.attributes.sources) || [];
  listed.forEach((s) => add(s && s.url));
  add(sourceDataUrl(d));
  return rows;
}

function sourcesHtml(d) {
  const listed = (d.attributes && d.attributes.sources) || [];
  const rows = listed.length
    ? listed
    : (d.source ? [{ name: d.source, url: d.source_url, license: d.data_license }] : []);
  return rows.map((s) => {
    const name = escapeHtml(s.name || "Source");
    const lic = s.license ? " \u00b7 " + escapeHtml(s.license) : "";
    if (s.url && !isMuseumListUrl(s.url)) {
      return `<p class="detail-credit">Source: <a href="${escapeAttr(s.url)}" target="_blank" rel="noopener">${name}</a>${lic}</p>`;
    }
    return `<p class="detail-credit">Source: ${name}${lic}</p>`;
  }).join("");
}

function formatFactDate(value) {
  if (!value) return "";
  const s = String(value);
  const jan1 = s.match(/^(\d{4})-01-01/);
  if (jan1) return jan1[1];
  const ymd = s.match(/^(\d{4}-\d{2}-\d{2})/);
  if (ymd) return ymd[1];
  const y = s.match(/^(\d{4})/);
  return y ? y[1] : s;
}

function datesRecognitionsHtml(d) {
  const attrs = d.attributes || {};
  const dates = Array.isArray(attrs.dates) ? attrs.dates : [];
  const recs = Array.isArray(attrs.recognitions) ? attrs.recognitions : [];
  let html = "";
  if (dates.length) {
    const items = dates.map((ev) => {
      const label = escapeHtml(ev.label || capitalize(ev.type) || "Date");
      const when = formatFactDate(ev.date);
      return `<li>${label}${when ? ": " + escapeHtml(when) : ""}</li>`;
    }).join("");
    html += `<div class="detail-dates"><h3>Dates</h3><ul>${items}</ul></div>`;
  }
  if (recs.length) {
    const items = recs.map((r) => {
      const when = formatFactDate(r.date);
      return `<li>${escapeHtml(r.name || "")}${when ? " (" + escapeHtml(when) + ")" : ""}</li>`;
    }).join("");
    html += `<div class="detail-recognitions"><h3>Recognitions</h3><ul>${items}</ul></div>`;
  }
  return { html, hasBlock: Boolean(html) };
}

function webSearchQuery(d) {
  const name = (d.name || "").trim();
  if (!name) return "";
  const parts = [name];
  if (d.city && !/^(MI|MICHIGAN)$/i.test(String(d.city).trim())) parts.push(d.city.trim());
  else if (d.county) parts.push(d.county + " County");
  parts.push("Michigan");
  return parts.join(" ");
}

function categoryPillsHtml(record) {
  const ids = [];
  function add(id) {
    if (id && CAT_BY_ID[id] && ids.indexOf(id) === -1) ids.push(id);
  }
  add(record.category);
  (record.tags || []).forEach((t) => {
    if (t && t.indexOf("also_") === 0) add(t.slice(5));
  });
  return ids.map((id) => {
    const c = CAT_BY_ID[id];
    return `<span class="cat-pill"><span class="swatch" style="background:${c.color}"></span>${escapeHtml(c.label)}</span>`;
  }).join("");
}

function iconSvg(name, size) {
  const s = size || 16;
  const paths = {
    directions: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10A15.3 15.3 0 0 1 12 2z"/>',
    pin: '<path d="M12 21s-6-4.6-6-10a6 6 0 1 1 12 0c0 5.4-6 10-6 10z"/><circle cx="12" cy="11" r="2"/>',
    wiki: '<path d="M4 19V5M8 19 12 7l4 12M9.2 15h5.6M20 5v14"/>',
    archive: '<rect x="3" y="7" width="18" height="13" rx="1"/><path d="M3 7V5h18v2M10 12h4"/>',
    source: '<path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 5.5 5.5"/>',
    copy: '<rect x="9" y="9" width="11" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  };
  const inner = paths[name] || "";
  return `<svg class="btn-icon" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
}

function outboundBtn(href, label, icon, outline, hint) {
  if (!urlHost(href)) return "";
  const cls = outline ? "btn-link btn-link-outline" : "btn-link";
  const hintHtml = hint ? `<span class="btn-hint">${escapeHtml(hint)}</span>` : "";
  return `<a class="${cls}" href="${escapeAttr(href)}" target="_blank" rel="noopener">${iconSvg(icon)}<span class="btn-label"><span>${escapeHtml(label)}</span>${hintHtml}</span></a>`;
}

function factButton(label, value, href, icon) {
  if (!urlHost(href)) return "";
  return `<a class="fact-btn" href="${escapeAttr(href)}" target="_blank" rel="noopener">
    ${iconSvg(icon, 20)}
    <span class="fact-btn-text">
      <span class="fact-label">${escapeHtml(label)}</span>
      <span class="fact-value">${escapeHtml(value)}</span>
    </span>
  </a>`;
}

function factHostLabel(url) {
  const h = urlHost(url);
  if (!h) return "Open link";
  if (isMuseumListUrl(url)) return "Wikipedia museum list";
  if (h.endsWith("wikipedia.org")) return "Wikipedia article";
  if (h.endsWith("wikidata.org")) return "Wikidata item";
  if (h.endsWith("imls.gov")) return "IMLS Museum Data Files";
  if (h.includes("arcgis.com")) return "Open data record";
  if (h.endsWith("nps.gov")) return "National Park Service";
  if (h.endsWith("michigan.gov")) return "Michigan.gov";
  return h.replace(/^www\./, "");
}

function initWiki() {
  if (!window.Wiki) return;
  window.Wiki.init({
    onAction: function (name) {
      if (name === "filters") setFiltersOpen(true);
      else if (name === "locate") $("#locateBtn").click();
      else if (name === "list") setView("list");
      else if (name === "map") setView("map");
      else if (name === "search") {
        const input = $("#searchInput");
        if (input) input.focus();
      }
    },
    getAboutContext: function () {
      const cap = window.Capacitor;
      const native = !!(cap && typeof cap.isNativePlatform === "function" && cap.isNativePlatform());
      return {
        landmark_count: String(state.all.length),
        generated: state.generated || "Unknown — rebuild the pipeline to record a timestamp",
        runtime: native ? "Android app" : "Local browser preview",
      };
    },
  });
}

async function main() {
  buildFilterUI();
  wireEvents();
  initMap();
  try {
    await loadIndex();
    applyFilters();
  } catch (e) {
    showStatus("Could not load landmark data.", 5000);
  }
  initWiki();

  // In the native Capacitor app the assets are already local, so skip the SW to
  // avoid serving a stale cache after an app update. sw.js is for local browser dev only.
  const inNativeApp = !!(window.Capacitor && typeof window.Capacitor.isNativePlatform === "function" && window.Capacitor.isNativePlatform());
  if (!inNativeApp && "serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }
}

main();
