# Third-party notices

This app bundles or loads the following third-party software and data. See
[`docs/LEGAL.md`](docs/LEGAL.md) for data-source licensing and
[`legal.html`](legal.html) for the in-app legal page.

## JavaScript libraries

| Component | Version | License | Source |
|-----------|---------|---------|--------|
| MapLibre GL JS | 4.7.1 | BSD 3-Clause | https://github.com/maplibre/maplibre-gl-js |
| Capacitor (Android wrapper) | 8.x | MIT | https://capacitorjs.com |
| @capacitor/geolocation | 8.x | MIT | https://capacitorjs.com/docs/apis/geolocation |

MapLibre is loaded from unpkg in `index.html` at runtime. Capacitor packages are
build-time dependencies under `mobile/`.

## Map and geocoding services (network)

| Service | Data license / terms | Use in app |
|---------|----------------------|------------|
| OpenFreeMap vector tiles | OpenStreetMap data © OpenStreetMap contributors (ODbL) | Basemap |
| OpenStreetMap Nominatim | OSM data (ODbL); [usage policy](https://operations.osmfoundation.org/policies/nominatim/) | Named-place search |

## Data sources (aggregated landmark records)

See [`docs/LEGAL.md`](docs/LEGAL.md) for the full attribution table (Michigan
DNR, NPS/NRHP, Wikidata, Wikipedia, Wikimedia Commons).

## Python pipeline

The data pipeline uses only the Python standard library (no third-party packages).
