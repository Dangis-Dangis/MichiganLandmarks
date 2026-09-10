# iPhone / App Store

This page records an analysis of shipping Michigan Landmarks on the Apple App
Store. It is **not a commitment** to build iOS. Back to [What's next](../roadmap.md).

**Recommendation if it happens:** keep one product. Add Capacitor’s iOS platform
next to Android. Do not rewrite in Swift, Flutter, or React Native.

## Same app, two stores

A Play listing and an App Store listing are two store products. They do not need
two codebases.

Today the Android app is already a Capacitor WebView around the same web UI
(`index.html`, `app.js`, `styles.css`, this Help overlay) plus bundled `data/`.
Location already uses `Capacitor.isNativePlatform()`, not Android-only APIs.
`npm run sync` copies `www/` to every Capacitor platform that has been added.

If iOS is added later, `mobile/` stays one package. Do not create `mobile-ios/`.

### Options that were considered

- **Same Capacitor project + iOS platform** — the fit for this repo. Same
  `www/`, same `copy-web.mjs`, Xcode instead of Android Studio.
- **PWA / Add to Home Screen** — not the App Store. Skip if the goal is a store listing.
- **Separate native Swift app** — share only pipeline JSON. Two UIs. Only if
  WKWebView/MapLibre fails in a way that cannot be patched.
- **Flutter / React Native rewrite** — throws away the existing web UI. No benefit.

### Already shared

- Pipeline and dataset (`python -m pipeline.run`, index + details)
- Web UI (map, list, filters, search, Help, legal)
- Offline model (landmark text bundled; tiles and photos still need a network)
- `@capacitor/geolocation`
- Safe-area CSS (`viewport-fit=cover`, `env(safe-area-inset-*)`)
- App id `com.michiganlandmarks.app` (valid as an iOS bundle ID)
- Privacy story (no accounts, no backend, location on-device only)

### Not shared

- Native project: gitignored `mobile/android/` vs a new `mobile/ios/`
- IDE: Android Studio / JDK 21 vs **macOS + Xcode**
- Signing: Play keystore / AAB vs Apple certificates and an `.ipa`
- Store: Play $25 one-time vs Apple $99/year
- Maps outbound links: Google Maps URLs today; iPhone users expect Apple Maps
- Icons, splash, and version fields in each native project
- Device testing: Windows + USB works for Android; iOS Simulator and archive need a Mac

## Mac and Xcode

Apple requires macOS to compile and submit iOS apps. Capacitor cannot work around
that. This repository is developed on Windows, so an App Store build is not
possible from the current machine.

Practical paths later: a Mac mini (best for debugging the map), a cloud Mac
(GitHub Actions `macos-latest`, MacStadium, Codemagic), or borrowing a Mac for
certificates and the first archive. Without some Mac access, iOS is not shippable.

Capacitor 8’s iOS docs also pin a recent Xcode. That is a tooling constraint, not
a product redesign.

## Apple Developer Program

Apple Developer Program membership is **$99 per year**. Google Play Developer
registration is a one-time **$25**. iOS also needs App Store Connect, certificates,
privacy nutrition labels, and an export-compliance encryption answer (usually
“HTTPS only”).

## No sideload APK analog

Android testers can install a debug APK from Files or Chrome. iOS has no
equivalent casual sideload. Distribution is TestFlight or the App Store. Free
developer-certificate sideload expires in seven days and is painful.

## App Review

Apple guideline 4.2 rejects thin website wrappers. This project is in a stronger
position than a typical Capacitor site wrapper: there is **no hosted website**,
the dataset is bundled (~18 MB), browsing works offline, and location uses a native
plugin. Review notes should say that. Risk still exists if the listing looks like
bookmarks of michigan.gov.

Apple is also sensitive to apps that download and execute code. The current model
(new data = a new store binary) matches Play and is the honest App Store story. Do
not add a live-update CDN just for iOS.

## MapLibre in WKWebView

The map is MapLibre GL JS (WebGL) loading
`https://tiles.openfreemap.org/styles/positron`. That usually works on modern iOS
WKWebView, but it has **not been tested** on iPhone. If it is janky or WebGL
fails, options are raise min iOS, WebView CSS tweaks, or (last resort) a native
map — a large fork. Do not plan a native MapLibre plugin up front.

Tiles and photos are already HTTPS. Mixed content is already disabled in
`capacitor.config.json`.

Other iOS polish that is not a reason to split apps: location purpose string
(`NSLocationWhenInUseUsageDescription`), keyboard / `100vh` / rubber-band scroll,
optional iPhone-only listing vs iPhone+iPad screenshots.

## Design choices that keep updates cheap

These are already mostly true:

1. One Capacitor `mobile/` package and one web UI.
2. Generic native checks (`isNativePlatform()`). Use `getPlatform()` only for
   Maps URLs and About runtime text (today About says “Android app” for any
   native runtime).
3. One maps helper: Apple Maps on iOS, Google Maps on Android.
4. Platform-neutral Help wording (“the app”, “the install package”) instead of
   only “APK”.
5. Same gitignore policy as Android for a generated `ios/` folder, unless Xcode
   files are customized and then committed.
6. Same version number on both stores when the dataset or UI changes.

## If it is built later

Not scheduled. First slice would be: `@capacitor/ios`, `npx cap add ios`, location
usage string, Apple Maps URLs, TestFlight, then App Store listing. None of that
requires a second Michigan Landmarks app. The expensive part is Apple’s hardware
and review process.
