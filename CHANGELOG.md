# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- In-app Help overlay with markdown pages, Legal & Privacy, changelog, and About. `copy-web.mjs` bundles `wiki/`, `wiki.js`, `CHANGELOG.md`, and `vendor/` into the APK.
- In-app **What's next** roadmap with iPhone / App Store costs and blockers, plus details in [`docs/roadmap/ios.md`](docs/roadmap/ios.md).
- Pipeline HTTP cache under `.cache/http/` (plus existing Nominatim cache); `--fresh` skips cache reads. A bare run writes the Android dataset under `data/` (index, details, report). `--export-gis` also writes GeoJSON/CSV/KML for QGIS / Google Earth / My Maps. `--output-dir DIR` writes somewhere other than `data/`. `--until` / `--skip` / `--from` / `--sources` for staged and partial rebuilds. Unchanged detail JSON files are not rewritten.
- Pipeline skip flags `--skip-nominatim-geocode`, `--skip-wikipedia`, `--skip-commons`; `--quiet` / `--silent` for stdout (`python -m pipeline.run --help`). A bare run is verbose and includes leftover Nominatim.
- Rotating per-run logs under `.cache/logs/`, stage/ETA banners, and a stdout summary of fallbacks and index changes.
- `data/DATA_HISTORY.md` plus `data_history.json` (local run snapshots; directory is gitignored).
- Wikidata heritage designations (P1435) after merge; dated events and multi-source attribution helpers.
- `location_quality` (`site` / `name` / `locality`) with an in-app warning on approximate pins.
- Split two-sided historical marker plaques: English body on the card, other-language text in a labeled section.
- Museum leftover geocoding order: Wikipedia article coordinates, then Nominatim on the name, then a city/township/county pin.
- Filter drawer close control, show/hide all categories, and “Hide city/township pins”.
- Detail sheet drag handle; Open in Maps / Directions for GPS, name+address, and street address; copyable address; Search the web.
- `npm run apk:export` (stable `mobile/dist/MichiganLandmarks-debug.apk`) and cross-platform Gradle via `gradle-run.mjs` (loads repo-root `.env` for `JAVA_HOME`).
- Developer handbook [`docs/DEVELOP.md`](docs/DEVELOP.md), [`AGENTS.md`](AGENTS.md), [`scripts/pipeline.sh`](scripts/pipeline.sh), and VS Code/Cursor tasks in `.vscode/tasks.json` (labels name the steps, e.g. **Pipeline (Nominatim, Wikipedia, Commons) + Build Debug APK**).
- Python unittest suite (`python -m unittest discover -s tests -v`).
- MapLibre GL JS 4.7.1 and marked 15.0.12 vendored under `vendor/` (map tiles still need a network).
- Agent session closeout: update matching user and developer docs, then refresh this `[Unreleased]` section and review older bullets against the tree. Tracked Cursor rules live in `.cursor/rules/`.

### Changed

- `data/` is generated output and is gitignored. A clone must run `python -m pipeline.run` before `npm run sync` or a Web UI preview.
- `.cursor/` is gitignored except tracked `.cursor/rules/`. `*.log`, `*.apk`, and `*.aab` remain gitignored.
- In-app search filters the bundled index only (name, county, summary). Nominatim is not called from the app.
- Leftover-museum Nominatim is on by default. Skip with `--skip-nominatim-geocode`.
- Default pipeline output is the Android dataset under `data/` (index, details, report). `--export-gis` writes GeoJSON/CSV/KML for QGIS / Google Earth / My Maps. `--output-dir DIR` writes somewhere other than `data/`.
- NRHP listing years come from National Register certification dates, not GIS layer create-dates.
- Official website links stay on venue/agency URLs; Wikipedia, NARA, and catalog pages are labeled as source/nomination.
- Privacy, legal, and Play Store docs match the local-search and outbound-link behavior. MapLibre is bundled, not loaded from a CDN.
- Header Help control is an SVG (circled i), not the Unicode character that some fonts draw as “?”.
- Help articles live under [`docs/`](docs/) (bundled into the APK). Maintainer handbooks are [`docs/dev/DEVELOP.md`](docs/dev/DEVELOP.md) and [`docs/dev/PLAYSTORE.md`](docs/dev/PLAYSTORE.md) and are not copied into the app. The former `wiki/` directory is gone.
- Help → Legal & Privacy renders [`docs/LEGAL.md`](docs/LEGAL.md). [`legal.html`](legal.html) remains the Play Store privacy URL at the repo root.
- IMLS 2018 museum coordinates default to `location_quality=name` (often city-level geocodes, not building pins).
- Duplicate post-merge landmark ids get a stable `-2`, `-3`, … suffix so rebuilds do not swap which record keeps the unsuffixed id.
- Invalid `--skip` / `--until` / `--from` / `--sources` values print `python -m pipeline.run: …` and exit 2, without an argparse usage dump. `--help` prog is `python -m pipeline.run`.
- Cursor/VS Code tasks: **Tests**, **Host Web UI**, **Pipeline**, **Pipeline (fast)**, **Pipeline + GIS exports**, **Pipeline (Nominatim, Wikipedia, Commons) + Build Debug APK**, **Copy Web UI into Android**, **Open Android Studio**, **Build Debug APK**, **Build Debug APK + Copy to dist**.
- Cursor/VS Code tasks also include **Pipeline (--fresh)**, **Pipeline (fast) + --fresh**, and **Pipeline (--fresh) + Build Debug APK** (bypass HTTP/Nominatim cache reads).
- Changelog corrections are additive: leave earlier bullets as written; add a new Added / Changed / Removed line that states what is now true. Do not rewrite or delete prior entries.
- `.cursor/rules/session-docs.mdc` is a Michigan Landmarks project rule (always applied in this repo).

### Removed

- In-app Help source directory `wiki/` (articles now live under `docs/`; maintainer pages under `docs/dev/`).
- Nominatim named-place search from the running app.
- Region filter facet (county remains on records and in search).
- Tracked copy of the generated dataset (about 4,460 files previously in git).
- Pipeline flags `--no-enrich`, `--geocode-museums`, `--verbose`, `--outputs`, and the `MUSEUM_GEOCODE` env switch (replaced by skip flags, `--export-gis`, `--output-dir`, and default-on leftover Nominatim).
