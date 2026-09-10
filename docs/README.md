# Docs

User-facing Help (the Help button in the app) and maintainer handbooks.

| Path | Audience | In the Android app? |
|---|---|---|
| `docs/*.md`, `docs/roadmap/`, `docs/assets/`, `docs/index.json` | App users | Yes (`copy-web.mjs` copies them into `www/docs/`) |
| [`LEGAL.md`](LEGAL.md) | Users (Help → Legal & Privacy) | Yes |
| [`dev/DEVELOP.md`](dev/DEVELOP.md), [`dev/PLAYSTORE.md`](dev/PLAYSTORE.md) | Developers | No |
| [`../legal.html`](../legal.html) | Play Store privacy URL (repo root) | Copied to www root; Help uses `LEGAL.md` |
| [`../CHANGELOG.md`](../CHANGELOG.md) | Users and developers | Yes (Help → Changelog) |

This `README.md` is not a Help article and is not copied into the APK.

Hash links in the running app stay `#wiki/…` (`wiki.js` is the overlay engine).
