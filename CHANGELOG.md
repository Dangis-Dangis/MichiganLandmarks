# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- Pipeline flags `--geocode-museums` and `--verbose` (`python -m pipeline.run --help`).
- Rotating per-run logs under `.cache/logs/`, stage/ETA banners, and a stdout summary of fallbacks and index changes.
- `data/DATA_HISTORY.md` plus `data_history.json` (local run snapshots; directory is gitignored).
- Wikidata heritage designations (P1435) after merge; dated events and multi-source attribution helpers.
- `location_quality` (`site` / `name` / `locality`) with an in-app warning on approximate pins.
- Split two-sided historical marker plaques: English body on the card, other-language text in a labeled section.
- Museum leftover geocoding order: Wikipedia article coordinates, then Nominatim on the name, then a city/township/county pin.
- Filter drawer close control, show/hide all categories, and “Hide city/township pins”.
- Detail sheet drag handle; Open in Maps / Directions for GPS, name+address, and street address; copyable address; Search the web.
- `npm run apk:export` (stable `mobile/dist/MichiganLandmarks-debug.apk`) and cross-platform Gradle via `gradle-run.mjs`.
- Developer handbook [`docs/DEVELOP.md`](docs/DEVELOP.md), [`AGENTS.md`](AGENTS.md), [`scripts/pipeline.sh`](scripts/pipeline.sh), and VS Code/Cursor tasks in `.vscode/tasks.json`.

### Changed

- `data/` is generated output and is gitignored. A clone must run `python -m pipeline.run` before `npm run sync` or a UI preview.
- `.cursor/`, `*.log`, `*.apk`, and `*.aab` are gitignored.
- In-app search filters the bundled index only (name, county, summary). Nominatim is not called from the app.
- Nominatim leftover museum geocoding is a per-run CLI flag. `MUSEUM_GEOCODE=1` in an existing `.env` is still honored.
- NRHP listing years come from National Register certification dates, not GIS layer create-dates.
- Official website links stay on venue/agency URLs; Wikipedia, NARA, and catalog pages are labeled as source/nomination.
- Privacy, legal, and Play Store docs match the local-search and outbound-link behavior.

### Removed

- Nominatim named-place search from the running app.
- Region filter facet (county remains on records and in search).
- Tracked copy of the generated dataset (about 4,460 files previously in git).
