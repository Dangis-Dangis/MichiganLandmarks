# Third-party notices

This app bundles or loads the following third-party software and data. See
[`docs/LEGAL.md`](docs/LEGAL.md) for data-source licensing (also in-app Help →
Legal & Privacy) and [`legal.html`](legal.html) for the standalone Play Store
privacy page.

## JavaScript libraries

| Component | Version | License | Source |
|-----------|---------|---------|--------|
| MapLibre GL JS | 4.7.1 | BSD 3-Clause | https://github.com/maplibre/maplibre-gl-js |
| marked | 15.0.12 | MIT | https://github.com/markedjs/marked |
| Capacitor (Android wrapper) | 8.x | MIT | https://capacitorjs.com |
| @capacitor/geolocation | 8.x | MIT | https://capacitorjs.com/docs/apis/geolocation |

MapLibre is bundled from `vendor/` into the APK (and local browser preview).
marked is bundled from `vendor/marked.min.js` to render in-app Help markdown.
Capacitor packages are build-time dependencies under `mobile/`.

## Map services (network)

| Service | Data license / terms | Use in app |
|---------|----------------------|------------|
| OpenFreeMap vector tiles | OpenStreetMap data © OpenStreetMap contributors (ODbL) | Basemap |

OpenStreetMap Nominatim is used only at **build time** (leftover museum
geocoding in the pipeline; skip with `--skip-nominatim-geocode`), not by the app.

## Data sources (aggregated landmark records)

See [`docs/LEGAL.md`](docs/LEGAL.md) for the full attribution table (Michigan
DNR, NPS/NRHP, Wikidata, Wikipedia, Wikimedia Commons).

## Python pipeline

The data pipeline uses only the Python standard library (no third-party packages).
