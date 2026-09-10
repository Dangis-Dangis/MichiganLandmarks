# Google Play release (Capacitor)

Michigan Landmarks ships as a **self-contained Capacitor app**: the web UI and
landmark dataset are bundled in the APK/AAB. No hosted website is required.

Build steps: [`../../mobile/README.md`](../../mobile/README.md).

## Prerequisites

- Completed debug build (`npm run sync`, then `gradlew bundleRelease` or Android Studio).
- Google Play Developer account (one-time **$25** registration).
- Release keystore backed up securely — losing it blocks future updates.

## Release build

1. Create a keystore (once) and store it outside the repo (e.g. `internal/mi-landmarks.keystore`):
   ```bash
   keytool -genkey -v -keystore mi-landmarks.keystore -alias milandmarks \
     -keyalg RSA -keysize 2048 -validity 10000
   ```
   `*.keystore` and `internal/` are gitignored.

2. Copy `mobile/key.properties.example` to `mobile/android/key.properties` and set
   your `storePassword` and `keyPassword`. Release signing is wired in
   `mobile/android/app/build.gradle` via `signingConfigs.release`.

3. Build an **Android App Bundle** (required for Play; APK is for sideloading only):
   ```bash
   cd mobile/android && ./gradlew bundleRelease
   ```
   Output: `mobile/android/app/build/outputs/bundle/release/app-release.aab`

4. Bump `versionCode` and `versionName` in `mobile/android/app/build.gradle`
   before each store upload.

## Play Console checklist

### App setup
- [ ] Package name matches `com.michiganlandmarks.app` in `capacitor.config.json`
      (change both together before your first release if you use a different id).
- [ ] Upload `app-release.aab` to an **internal testing** track first.
- [ ] Target API level meets [Play requirements](https://developer.android.com/google/play/requirements/target-sdk)
      (project targets SDK 36 via `variables.gradle`).

### Store listing
- [ ] **Title:** Michigan Landmarks (or your chosen name).
- [ ] **Short description:** Offline guide to Michigan lighthouses, markers, historic places, and parks.
- [ ] **Full description:** Explain bundled offline data, map/list/search, and that the app is unofficial.
      Do **not** imply endorsement by Michigan DNR, NPS, or NRHP.
- [ ] **Category:** Travel & Local (or Maps & Navigation).
- [ ] **Icon:** 512×512 PNG — use `icons/icon-512.png`.
- [ ] **Feature graphic:** 1024×500.
- [ ] **Phone screenshots:** at least 2 (map view, list or detail card).

### Privacy and data safety
- [ ] **Privacy policy URL** — Play requires a public URL. This project does not
      host a website; link to `legal.html` in your GitHub repository, e.g.
      `https://github.com/Dangis-Dangis/MichiganLandmarks/blob/main/legal.html`.
      In-app Help uses [`docs/LEGAL.md`](../LEGAL.md) (**Help** → **Legal & Privacy**).
      Keep `legal.html` in sync with that page's unofficial, privacy, sources,
      disclaimer, and software sections.
- [ ] **Data safety form:**
  - Location: **used in-app** for “Near me” sorting; **not collected**, not shared,
    not stored on a server (there is no backend).
  - No accounts, no analytics SDK, no ads.
  - Optional network: map tiles (OpenFreeMap/OSM), hotlinked photos,
    external direction links.

### Permissions
- [ ] **ACCESS_FINE_LOCATION / ACCESS_COARSE_LOCATION** — justify as on-device
      distance sort and map centering only (`@capacitor/geolocation`).
- [ ] **INTERNET** — map tiles, hotlinked images, user-tapped outbound links.

### Content and compliance
- [ ] Complete the content rating questionnaire (no user-generated content).
- [ ] Confirm all image licenses resolved at build time (`data/DATA_REPORT.md`).
- [ ] Promote from internal testing → closed testing → production when ready.

## Launcher icons

Default Capacitor mipmaps are placeholders. Generate store-quality icons from
`mobile/assets/` before release:

```bash
cd mobile
npx @capacitor/assets generate --android
npm run sync
```

## Sideloading (non-Play)

Share `mobile/dist/MichiganLandmarks-debug.apk` after `cd mobile && npm run apk:debug && npm run apk:export`.
On the device: **Settings → Security → Install unknown apps** for the file manager used to open the APK.

## Updating landmark data

1. `python -m pipeline.run` (repo root)
2. `cd mobile && npm run sync`
3. Rebuild and upload a new AAB with an incremented `versionCode`.
