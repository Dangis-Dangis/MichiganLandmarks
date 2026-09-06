# Michigan Landmarks

An offline-first Android app for exploring Michigan's lighthouses, historical
markers, registered historic places (NRHP), state and national parks, and museums.
Data is aggregated from official open sources into one searchable map and list
with thousands of landmarks bundled in the app.

There is no hosted website and no backend. Landmark data ships inside the APK;
map basemap tiles load from the network when available.

## What's in this repository

```
├── pipeline/              Python data pipeline (stdlib only)
│   └── run.py             python -m pipeline.run [--no-enrich] [--geocode-museums] [--verbose]
├── data/                  generated dataset (gitignored; run the pipeline)
│   ├── landmarks.index.json
│   ├── details/<id>.json
│   ├── DATA_REPORT.md     counts, fallbacks, changes since last run
│   └── DATA_HISTORY.md    recent run snapshots
├── index.html, app.js, styles.css, manifest.webmanifest, icons/, legal.html
│                          web UI source (bundled into the Android app)
├── mobile/                Capacitor Android project — see mobile/README.md
└── docs/                  DEVELOP.md, LEGAL.md, PLAYSTORE.md
```

## Quick start (Android)

Requires Python 3.10+, Node.js 20+, JDK 21, and the Android SDK. Copy
`.env.example` to `.env`. Full steps: [`docs/DEVELOP.md`](docs/DEVELOP.md).

```bash
python -m pipeline.run          # required; writes gitignored data/
cd mobile
npm install
npm run add:android             # first time only
npm run open:android            # or: npm run apk:debug
```

After UI or data changes: `cd mobile && npm run sync`, then rebuild.

## Data pipeline

```bash
python -m pipeline.run
```

Writes `data/` and prints a summary (fallbacks, changes, log path). Variants,
stage ETAs, and the option-gated diagram: [`docs/DEVELOP.md`](docs/DEVELOP.md).

### Data sources (all open)

| Category | Source |
|---|---|
| Historical markers | Michigan DNR / History Center feature service |
| State parks | Michigan DNR state park recreation points |
| Historic places | National Register of Historic Places (NPS, Esri Federal) |
| Lighthouses | Wikidata (WikiProject Lighthouses) + Wikimedia Commons images |
| National parks | NPS Data API (or Wikidata fallback) |
| Museums | Wikidata + IMLS 2018 + Wikipedia list |

Licensing is recorded per record (`data_license`, `image_license`). See
[`docs/LEGAL.md`](docs/LEGAL.md) and the in-app [`legal.html`](legal.html).

## Contact

- GitHub: [Dangis-Dangis/MichiganLandmarks](https://github.com/Dangis-Dangis/MichiganLandmarks)
- Email: [dangisdangis.dev@gmail.com](mailto:dangisdangis.dev@gmail.com)

## Offline behavior

| Content | Offline? |
|---|---|
| Landmark index, details, app UI | Yes — bundled in the APK |
| Map basemap tiles | No — loaded from OpenFreeMap when online |
| Landmark search | Yes — filters the bundled index |
| Landmark photos | Cached in memory during a session; hotlinked when online |

## Local UI preview (optional)

```bash
python -m http.server 8000      # repo root; open http://localhost:8000/
```

Development only. The product is the Android app, not a hosted site.

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
  minor source error. Listing years come from the National Register certification
  date when the source provides one; GIS layer create-dates are not used.
- State parks and NPS Data API units often have no built or established year.
- Pins with `location_quality` of `name` or `locality` are approximate; the detail
  card shows a warning.
