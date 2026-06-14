# Michigan Landmarks — Android app (Capacitor)

Self-contained Android wrapper around the Michigan Landmarks web UI. The APK
bundles the app shell **and landmark data** (~18 MB of index + details), so
browsing works offline. Map basemap tiles still load from the network when
online.

## How it works

- `copy-web.mjs` assembles `www/` from the repo-root UI (`index.html`, `app.js`,
  `styles.css`, `manifest.webmanifest`, `legal.html`, `icons/`) plus
  `data/landmarks.index.json` and `data/details/`.
- Capacitor packages `www/` into a native Android WebView app.
- The web UI detects Capacitor and skips the service worker (assets are already
  local), so app updates never serve a stale cache.

`www/` and `android/` are gitignored — regenerate them with the commands below.

## Prerequisites (install once)

- **Node.js 20+**
- **JDK 21** (Capacitor 8 / modern Android Gradle Plugin)
- **Android SDK** — Android Studio is easiest; needs platform `android-35+` and
  build-tools. Set `ANDROID_HOME` or `ANDROID_SDK_ROOT`.

## Build the APK

```bash
cd mobile
npm install                 # one time

# 1) Dataset must exist (from repo root):
#    python -m pipeline.run

# 2) Generate the Android project (first time only):
npm run add:android         # copy-web.mjs + cap add android

# 3a) Android Studio (recommended):
npm run open:android        # Run or Build → Build APK

# 3b) Debug APK from CLI:
npm run apk:debug
# → android/app/build/outputs/apk/debug/app-debug.apk
```

After changing the web UI or rebuilding data:

```bash
npm run sync                # copy-web.mjs + cap sync
```

## Sideloading

Send `app-debug.apk` to testers. On their phone: allow installs from the app
used to open the file (Files, Chrome, etc.), then tap to install.

## Signed release / Play Store

See [`../docs/PLAYSTORE.md`](../docs/PLAYSTORE.md) for keystore setup, AAB
build, store listing, and data-safety form.

## App identity

Edit `capacitor.config.json` to change `appId` (currently `com.michiganlandmarks.app`)
and `appName` **before** the first `npm run add:android`.

Regenerate launcher icons from `mobile/assets/`:

```bash
npx @capacitor/assets generate --android
npm run sync
```

## Local UI preview (optional)

From the repo root, with `data/` present:

```bash
python -m http.server 8000
```

Open `http://localhost:8000/` in a desktop browser to iterate on layout and
filters without rebuilding Android. Not a deployment path.
