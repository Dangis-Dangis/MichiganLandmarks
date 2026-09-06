# Michigan Landmarks

An offline-first Android app for exploring Michigan's lighthouses, historical
markers, registered historic places (NRHP), state and national parks, and museums.
Data is aggregated from official open sources into one searchable map and list
with thousands of landmarks bundled in the app.

There is no hosted website and no backend. Landmark data ships inside the APK;
map basemap tiles and optional place search load from the network when available.

## What's in this repository

```
michigan/
├── pipeline/              Python data pipeline (stdlib only)
│   ├── sources/           one fetcher per source → unified Landmark records
│   ├── enrich.py          Wikipedia/Commons enrichment (best-effort)
│   ├── dedupe.py          merge-with-tags de-duplication
│   ├── outputs.py         geojson / csv / kml / index / details
│   └── run.py             orchestrator: python -m pipeline.run
├── data/                  generated dataset (included for clone-and-build)
│   ├── landmarks.index.json     lightweight index (map + list)
│   ├── details/<id>.json        full per-record detail (lazy-loaded)
│   └── DATA_REPORT.md           counts, completeness, sizes
├── index.html, app.js, styles.css, manifest.webmanifest, icons/, legal.html
│                          web UI source (bundled into the Android app)
├── mobile/                Capacitor Android project — see mobile/README.md
└── docs/                  LEGAL.md, PLAYSTORE.md
```

## Quick start (Android)

1. **Dataset** — already in `data/`. To refresh from sources:
   ```bash
   python -m pipeline.run
   ```
2. **Build the APK** — see [`mobile/README.md`](mobile/README.md):
   ```bash
   cd mobile
   npm install
   npm run add:android    # first time only
   npm run apk:debug      # or open in Android Studio
   ```

Requires Python 3.10+, Node.js 20+, JDK 21, and the Android SDK.

## Data pipeline

Requires Python 3.10+. No third-party packages.

```bash
python -m pipeline.run
```

Outputs land in `data/`. The run prints per-source counts and writes
`data/DATA_REPORT.md`. Typical result: ~3,300 landmarks in under 20 seconds.

Options:
- `python -m pipeline.run --no-enrich` — skip Wikipedia/Commons enrichment.
- Set `NPS_API_KEY` (free, from [NPS Developer](https://www.nps.gov/subjects/developer/get-started.htm))
  to fetch National Park units from the official NPS API; without it, the pipeline
  uses Wikidata for Michigan NPS units automatically.

### Data sources (all open)

| Category | Source |
|---|---|
| Historical markers | Michigan DNR / History Center feature service |
| State parks | Michigan DNR state park recreation points |
| Historic places | National Register of Historic Places (NPS, Esri Federal) |
| Lighthouses | Wikidata (WikiProject Lighthouses) + Wikimedia Commons images |
| National parks | NPS Data API (or Wikidata fallback) |

Licensing is recorded per record (`data_license`, `image_license`). See
[`docs/LEGAL.md`](docs/LEGAL.md) and the in-app [`legal.html`](legal.html).

## Offline behavior

| Content | Offline? |
|---|---|
| Landmark index, details, app UI | Yes — bundled in the APK |
| Map basemap tiles | No — loaded from OpenFreeMap when online |
| Place search (Nominatim) | No — requires network |
| Landmark photos | Cached in memory during a session; hotlinked when online |

After building data or editing the web UI, run `npm run sync` in `mobile/` before
rebuilding the APK.

## Local UI preview (optional)

To iterate on the web UI in a desktop browser without rebuilding Android:

```bash
python -m pipeline.run          # if data/ is missing
python -m http.server 8000      # repo root; open http://localhost:8000/
```

This is for development only. The product is the Android app, not a hosted site.

## Play Store

See [`docs/PLAYSTORE.md`](docs/PLAYSTORE.md) for signing, store listing, data
safety, and privacy-policy requirements.

## Legal / licensing

- In-app: [`legal.html`](legal.html) (privacy, disclaimers, data sources).
- Maintainer docs: [`docs/LEGAL.md`](docs/LEGAL.md).
- Code license: [MIT](LICENSE). Third-party notices: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Known gaps

- State-park descriptions and photos come from Wikipedia enrichment at build time;
  if Wikimedia is unreachable during `pipeline.run`, those fields stay empty.
- NRHP listings are points only (polygons withheld by NPS); some coordinates carry
  minor source error.
