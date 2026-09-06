/* Michigan Landmarks - app UI (bundled in the Capacitor Android app).
 * Loads the lightweight index up front, renders a clustered map + a list, and
 * lazy-loads full per-record details on demand. Pure vanilla JS + MapLibre GL.
 */
"use strict";

const DATA_BASE = "./data/";
const INDEX_URL = DATA_BASE + "landmarks.index.json";
const MAP_STYLE = "https://tiles.openfreemap.org/styles/positron";
const MICHIGAN_CENTER = [-85.6, 44.8];
// Nominatim usage policy: identify the app. Browsers may ignore User-Agent on fetch;
// Capacitor WebView and some runtimes honor it. See legal.html.
const APP_USER_AGENT = "MichiganLandmarks/1.0 (personal project; legal: ./legal.html)";

const CATEGORIES = [
  { id: "lighthouse", label: "Lighthouses", color: "#1f77b4", emoji: "\uD83D\uDDFC" },
  { id: "historical_marker", label: "Historical markers", color: "#2ca02c", emoji: "\uD83E\uDEA7" },
  { id: "nrhp_site", label: "Historic places (NRHP)", color: "#9467bd", emoji: "\uD83C\uDFDB\uFE0F" },
  { id: "state_park", label: "State parks", color: "#ff7f0e", emoji: "\uD83C\uDF32" },
  { id: "national_park_unit", label: "National parks", color: "#8c564b", emoji: "\u26F0\uFE0F" },
  { id: "museum", label: "Museums", color: "#e377c2", emoji: "\uD83C\uDFA8" },
];
const CAT_BY_ID = Object.fromEntries(CATEGORIES.map((c) => [c.id, c]));
const REGIONS = [
  { id: "Western UP", label: "Western UP" },
  { id: "Eastern UP", label: "Eastern UP" },
  { id: "Northwest", label: "Northwest" },
  { id: "Northeast", label: "Northeast" },
  { id: "West Michigan", label: "West Michigan" },
  { id: "Central", label: "Central" },
  { id: "East/Thumb", label: "East / Thumb" },
  { id: "Southwest", label: "Southwest" },
  { id: "Southeast", label: "Southeast" },
];

const state = {
  all: [],
  filtered: [],
  origin: null, // {lat, lon} for distance sort
  activeCategories: new Set(CATEGORIES.map((c) => c.id)),
  activeRegions: new Set(REGIONS.map((r) => r.id)),
  sort: "name",
  withImageOnly: false,
  query: "",
  view: "map",
  map: null,
  mapReady: false,
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
    if (!state.activeCategories.has(lm.category)) return false;
    if (lm.region && !state.activeRegions.has(lm.region)) return false;
    if (state.withImageOnly && !lm.image_url) return false;
    if (q) {
      const hay = (lm.name + " " + (lm.county || "") + " " + (lm.summary || "")).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  if (state.origin && state.sort === "distance") {
    items.forEach((lm) => { lm._dist = haversineKm(state.origin, { lat: lm.latitude, lon: lm.longitude }); });
    items.sort((a, b) => a._dist - b._dist);
  } else if (state.sort === "name") {
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
  if (state.view === "list") renderList();
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
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

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
      ? `<img class="list-thumb" loading="lazy" src="${lm.image_url}" alt="" onerror="this.style.display='none'"/>`
      : `<div class="list-thumb placeholder">${cat ? cat.emoji : "\uD83D\uDCCD"}</div>`;
    const dist = lm._dist != null ? `<span class="list-dist">${fmtDist(lm._dist)}</span>` : "";
    card.innerHTML = `${thumb}
      <div class="list-main">
        <p class="list-name">${escapeHtml(lm.name)}</p>
        <div class="list-meta">
          <span class="cat-pill"><span class="swatch" style="background:${cat ? cat.color : "#555"}"></span>${cat ? cat.label : lm.category}</span>
          ${lm.year ? `<span>${lm.year}</span>` : ""}
          ${lm.county ? `<span>${escapeHtml(lm.county)} Co.</span>` : ""}
          ${dist}
        </div>
      </div>`;
    card.addEventListener("click", () => {
      openDetail(lm);
      if (state.map) state.map.flyTo({ center: [lm.longitude, lm.latitude], zoom: 13 });
    });
    frag.appendChild(card);
  });
  root.innerHTML = items.length ? "" : '<p class="muted" style="padding:16px">No landmarks match your filters.</p>';
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
  const panel = $("#detailPanel");
  const body = $("#detailBody");
  const cat = CAT_BY_ID[record.category];
  body.innerHTML = '<p class="muted" style="margin-top:48px">Loading\u2026</p>';
  panel.classList.remove("hidden");

  let d;
  try {
    d = await loadDetail(record);
  } catch (e) {
    d = record; // fall back to index fields when offline and uncached
  }

  const dateLabel = d.date_type && d.year ? `${capitalize(d.date_type)} ${d.year}` : (d.year || "");
  const text = (d.attributes && d.attributes.marker_text) || d.description || "";
  const links = [];
  if (d.official_url) links.push(`<a class="btn-link" href="${d.official_url}" target="_blank" rel="noopener">Official / more information</a>`);
  if (d.attributes && d.attributes.wikipedia_url && d.attributes.wikipedia_url !== d.official_url)
    links.push(`<a class="btn-link" href="${d.attributes.wikipedia_url}" target="_blank" rel="noopener">Wikipedia</a>`);
  links.push(`<a class="btn-link" href="https://www.google.com/maps/dir/?api=1&destination=${d.latitude},${d.longitude}" target="_blank" rel="noopener">Directions</a>`);

  const overlapTags = (d.tags || []).filter((t) => t.startsWith("also_"))
    .map((t) => `<span class="tag">also ${CAT_BY_ID[t.slice(5)] ? CAT_BY_ID[t.slice(5)].label.toLowerCase() : t.slice(5)}</span>`).join("");

  const descCredit = descriptionAttribution(d);

  body.innerHTML = `
    ${d.image_url ? `<img class="detail-img" src="${d.image_url}" alt="" onerror="this.style.display='none'"/>` : `<div style="height:44px"></div>`}
    <h2 class="detail-title">${escapeHtml(d.name)}</h2>
    <div class="detail-sub">
      <span class="cat-pill"><span class="swatch" style="background:${cat ? cat.color : "#555"}"></span>${cat ? cat.label : d.category}</span>
      ${d.subtype ? `<span>${escapeHtml(d.subtype)}</span>` : ""}
      ${dateLabel ? `<span>${escapeHtml(String(dateLabel))}</span>` : ""}
      ${d.county ? `<span>${escapeHtml(d.county)} County</span>` : ""}
    </div>
    ${text ? `<div class="detail-text">${escapeHtml(text)}</div>` : '<p class="muted">No description available for this record yet.</p>'}
    ${descCredit}
    ${overlapTags ? `<div class="tag-row">${overlapTags}</div>` : ""}
    <div class="detail-links">${links.join("")}</div>
    ${d.image_credit ? `<p class="detail-credit">Photo: ${escapeHtml(d.image_credit)}${d.image_license ? " (" + escapeHtml(d.image_license) + ")" : ""}</p>` : ""}
    <p class="detail-credit">Source: ${escapeHtml(d.source || "")}${d.data_license ? " \u00b7 " + escapeHtml(d.data_license) : ""}</p>
    <p class="detail-credit"><a href="./legal.html">Legal, privacy &amp; sources</a> \u00b7 Unofficial app, not affiliated with Michigan DNR or NPS.</p>
  `;
}

function descriptionAttribution(d) {
  const src = d.attributes && d.attributes.description_source;
  const lic = d.attributes && d.attributes.description_license;
  const wiki = d.attributes && d.attributes.wikipedia_url;
  if (src === "Wikipedia" && wiki) {
    return `<p class="detail-credit">Description from <a href="${escapeHtml(wiki)}" target="_blank" rel="noopener">Wikipedia</a> (${escapeHtml(lic || "CC BY-SA 4.0")})</p>`;
  }
  if (src && lic) {
    return `<p class="detail-credit">Description: ${escapeHtml(src)} (${escapeHtml(lic)})</p>`;
  }
  return "";
}

/* -------------------------------------------------------------------------- */
/* Geocoding (search a named place)                                            */
/* -------------------------------------------------------------------------- */
async function geocodePlace(query) {
  let q = query.trim();
  if (!/michigan|\bmi\b/i.test(q)) q += ", Michigan";
  const url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=us&q=" +
    encodeURIComponent(q);
  const res = await fetch(url, {
    headers: {
      "Accept-Language": "en",
      "User-Agent": APP_USER_AGENT,
    },
  });
  const data = await res.json();
  if (!data.length) return null;
  return { lat: parseFloat(data[0].lat), lon: parseFloat(data[0].lon), label: data[0].display_name };
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

  const regRoot = $("#regionFilters");
  REGIONS.forEach((r) => {
    const label = document.createElement("label");
    label.className = "checkbox";
    label.innerHTML = `<input type="checkbox" value="${r.id}" checked /> ${r.label}`;
    label.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) state.activeRegions.add(r.id);
      else state.activeRegions.delete(r.id);
      applyFilters();
    });
    regRoot.appendChild(label);
  });
}

function setView(view) {
  state.view = view;
  $("#map").classList.toggle("hidden", view !== "map");
  $("#listView").classList.toggle("hidden", view !== "list");
  if (view === "list") renderList();
  else if (state.map) state.map.resize();
}

function wireEvents() {
  $("#menuToggle").addEventListener("click", () => $("#filters").classList.toggle("hidden"));
  $("#viewToggle").addEventListener("click", () => setView(state.view === "map" ? "list" : "map"));
  $("#detailClose").addEventListener("click", () => $("#detailPanel").classList.add("hidden"));
  $("#sortSelect").addEventListener("change", (e) => { state.sort = e.target.value; applyFilters(); });
  $("#withImageOnly").addEventListener("change", (e) => { state.withImageOnly = e.target.checked; applyFilters(); });

  let debounce;
  const input = $("#searchInput");
  input.addEventListener("input", (e) => {
    state.query = e.target.value;
    clearTimeout(debounce);
    debounce = setTimeout(applyFilters, 180);
  });
  input.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    const q = input.value.trim();
    if (!q) return;
    showStatus("Finding \u201c" + q + "\u201d\u2026");
    try {
      const place = await geocodePlace(q);
      if (place) {
        state.origin = { lat: place.lat, lon: place.lon };
        state.sort = "distance";
        $("#sortSelect").value = "distance";
        if (state.map) state.map.flyTo({ center: [place.lon, place.lat], zoom: 11 });
        applyFilters();
        showStatus("Showing landmarks near " + place.label.split(",")[0], 2500);
      } else {
        showStatus("Place not found; filtering by text instead.", 2500);
      }
    } catch (err) {
      showStatus("Search unavailable offline.", 2500);
    }
  });
  $("#searchClear").addEventListener("click", () => {
    input.value = ""; state.query = ""; applyFilters(); input.focus();
  });

  $("#locateBtn").addEventListener("click", async () => {
    showStatus("Locating you\u2026");
    try {
      const pos = await getPosition();
      state.origin = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      state.sort = "distance";
      $("#sortSelect").value = "distance";
      if (state.map) {
        state.map.flyTo({ center: [state.origin.lon, state.origin.lat], zoom: 11 });
        new maplibregl.Marker({ color: "#0b3d2e" }).setLngLat([state.origin.lon, state.origin.lat]).addTo(state.map);
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
function capitalize(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

async function main() {
  buildFilterUI();
  wireEvents();
  initMap();
  try {
    await loadIndex();
  } catch (e) {
    showStatus("Could not load landmark data.", 5000);
    return;
  }
  applyFilters();

  // In the native Capacitor app the assets are already local, so skip the SW to
  // avoid serving a stale cache after an app update. sw.js is for local browser dev only.
  const inNativeApp = !!(window.Capacitor && typeof window.Capacitor.isNativePlatform === "function" && window.Capacitor.isNativePlatform());
  if (!inNativeApp && "serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }
}

main();
