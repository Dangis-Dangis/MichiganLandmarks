# Agent notes — Michigan Landmarks

Offline-first Android app (Capacitor) plus a stdlib Python pipeline that
aggregates Michigan landmarks into `data/`. No hosted site, no backend.

Canonical developer steps: [`docs/DEVELOP.md`](docs/DEVELOP.md).

## Stack

- Pipeline: Python 3.10+, stdlib only (`python -m pipeline.run`)
- UI: vanilla `index.html` / `app.js` / `styles.css`
- Android: Capacitor 8 in `mobile/` (Node 20+, JDK 21)

## Generated vs tracked

- **Tracked:** web UI, `pipeline/`, `mobile/` sources
- **Gitignored:** `data/`, `.cursor/`, `mobile/android/`, `mobile/www/`,
  `mobile/dist/`, `.env`, `.cache/`, keystores, `internal/`

Do not commit `.env`, `*.keystore`, or `key.properties`.

## Commands

```bash
python -m pipeline.run
python -m pipeline.run --no-enrich
python -m pipeline.run --geocode-museums
python -m pipeline.run --verbose
cd mobile && npm run sync
cd mobile && npm run open:android
cd mobile && npm run apk:debug
cd mobile && npm run apk:export
```

`--geocode-museums` is the canonical leftover-Nominatim switch. `--verbose` also
prints `[debug]` lines to stdout (they are always written to the log file).
`NPS_API_KEY` stays in `.env` (secret). After data or
UI changes, `npm run sync` before any APK.

The debug APK is the developer/sideload artifact. Play Store uses an AAB — see
[`docs/PLAYSTORE.md`](docs/PLAYSTORE.md). Do not invent extra pipeline flags.
