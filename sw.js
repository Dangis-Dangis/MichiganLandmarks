/* Service worker for local browser UI preview only (not bundled in the Android app). */
const VERSION = "mi-landmarks-v2";
const CORE_CACHE = VERSION + "-core";
const DATA_CACHE = VERSION + "-data";
const RUNTIME_CACHE = VERSION + "-runtime";

const CORE_ASSETS = [
  "./",
  "./index.html",
  "./legal.html",
  "./app.js",
  "./styles.css",
  "./manifest.webmanifest",
  "./icons/icon.svg",
  "./icons/icon-192.png",
  "./data/landmarks.index.json",
  "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js",
  "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CORE_CACHE).then((cache) =>
      // Don't let one failed cross-origin asset abort the whole install.
      Promise.allSettled(CORE_ASSETS.map((url) => cache.add(url)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function cacheFirst(request, cacheName) {
  return caches.open(cacheName).then((cache) =>
    cache.match(request).then((hit) => {
      if (hit) return hit;
      return fetch(request).then((res) => {
        if (res && res.status === 200) cache.put(request, res.clone());
        return res;
      });
    })
  );
}

function staleWhileRevalidate(request, cacheName) {
  return caches.open(cacheName).then((cache) =>
    cache.match(request).then((hit) => {
      const network = fetch(request)
        .then((res) => { if (res && res.status === 200) cache.put(request, res.clone()); return res; })
        .catch(() => hit);
      return hit || network;
    })
  );
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // App navigations -> serve the cached shell when offline.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("./index.html")));
    return;
  }

  // Per-record detail JSON -> cache as it's viewed (lazy offline build-up).
  if (url.pathname.includes("/data/details/")) {
    event.respondWith(cacheFirst(req, DATA_CACHE));
    return;
  }

  // The index + other same-origin assets.
  if (url.origin === self.location.origin) {
    event.respondWith(staleWhileRevalidate(req, CORE_CACHE));
    return;
  }

  // Map tiles and fonts only — do not cache third-party landmark photos.
  const host = url.hostname;
  const isPhotoHost = /wikimedia\.org|wikipedia\.org|arcgis\.com/i.test(host);
  if (isPhotoHost) {
    event.respondWith(fetch(req));
    return;
  }

  // Map tiles, fonts, sprites, and MapLibre CDN -> best-effort runtime cache.
  event.respondWith(staleWhileRevalidate(req, RUNTIME_CACHE));
});
