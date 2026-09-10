# Agent notes — Michigan Landmarks

Offline-first Android app (Capacitor) plus a stdlib Python pipeline that
aggregates Michigan landmarks into `data/`. No hosted site, no backend.

Canonical developer steps: [`docs/dev/DEVELOP.md`](docs/dev/DEVELOP.md).

## Stack

- Pipeline: Python 3.10+, stdlib only (`python -m pipeline.run`)
- UI: vanilla `index.html` / `app.js` / `wiki.js` / `styles.css` plus `docs/` (Help)
- Android: Capacitor 8 in `mobile/` (Node 20+, JDK 21)

## Generated vs tracked

- **Tracked:** web UI, `docs/`, `pipeline/`, `vendor/`, `mobile/` sources,
  `.cursor/rules/`
- **Gitignored:** `data/`, the rest of `.cursor/`, `mobile/android/`,
  `mobile/www/`, `mobile/dist/`, `.env`, `.cache/`, keystores, `internal/`

Do not commit `.env`, `*.keystore`, or `key.properties`.

## Commands

```bash
python -m pipeline.run
python -m pipeline.run --skip-nominatim-geocode
python -m pipeline.run --skip-wikipedia --skip-commons
python -m pipeline.run --export-gis
python -m pipeline.run --fresh
python -m pipeline.run --help
python -m unittest discover -s tests -v
cd mobile && npm run sync
cd mobile && npm run open:android
cd mobile && npm run apk:debug
cd mobile && npm run apk:export
```

A bare `python -m pipeline.run` does every stage (leftover Nominatim, Wikipedia
summaries, Commons licenses) and writes the app files (index, details, report)
with `[debug]` on stdout. Skip expensive steps with `--skip-nominatim-geocode`,
`--skip-wikipedia`, `--skip-commons`. `--quiet` / `--silent` reduce or suppress
stdout (log file still written). `--export-gis` also writes GeoJSON/CSV/KML
for QGIS, Google Earth, and My Maps. `--output-dir DIR` writes the dataset
somewhere other than `data/` (Sync / the APK still read `data/`). `--fresh`
ignores HTTP/Nominatim caches. `--until` / `--skip` / `--from` / `--sources`
are documented in [`docs/dev/DEVELOP.md`](docs/dev/DEVELOP.md)
(`python -m pipeline.run --help`). `NPS_API_KEY` stays in `.env` (secret).
`JAVA_HOME` also lives in `.env`; `gradle-run.mjs` loads it for
`npm run apk:debug` / Cursor **Build Debug APK**. Maximal app rebuild + APK:
Cursor **Pipeline (Nominatim, Wikipedia, Commons) + Build Debug APK**. Cache
bypass: **Pipeline (--fresh)** or `python -m pipeline.run --fresh`. After
data or Web UI changes, `npm run sync` (or **Copy Web UI into Android**) before
any APK if you are not using **Build Debug APK**.

The debug APK is the developer/sideload artifact. Play Store uses an AAB — see
[`docs/dev/PLAYSTORE.md`](docs/dev/PLAYSTORE.md). Pipeline flags: `python -m pipeline.run --help`.

## Session closeout

Before finishing work that changes behavior, data, UI, pipeline, or workflow:

1. Update the docs that would otherwise be wrong:
   - Users / in-app: `docs/` (except `docs/dev/`), `README.md`, `legal.html`,
     `CHANGELOG.md`
   - Privacy / store: `docs/LEGAL.md`, `legal.html`, `docs/dev/PLAYSTORE.md`,
     `THIRD_PARTY_NOTICES.md`
   - Developers: `docs/dev/DEVELOP.md`, `docs/dev/PLAYSTORE.md`, this file,
     `mobile/README.md`
2. Add this session's notable changes to [`CHANGELOG.md`](CHANGELOG.md)
   `[Unreleased]` (Added / Changed / Removed).
3. Re-read existing changelog bullets. If one is no longer true, do not rewrite
   or delete it. Add a new Added / Changed / Removed line that states what is
   now true.

Typo-only or comment-only edits skip the changelog. Keep using `[Unreleased]`
until a release is cut. Do not invent version numbers.
