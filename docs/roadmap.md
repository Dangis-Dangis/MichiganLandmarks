# What's next

These are **explored options**, not a schedule. Nothing here promises a ship date.
Shipped work is in the [changelog](../CHANGELOG.md). Documented limits are on
[Known issues](known-issues.md).

## iPhone / App Store

An iPhone listing is possible later by adding Capacitor’s iOS platform to the
**same** `mobile/` project — not by writing a second app. Details:
[iPhone / App Store](roadmap/ios.md).

**Costs and blockers**

- [Mac / Xcode](roadmap/ios.md#mac-and-xcode) — this project is developed on Windows. Apple will not compile or submit an iOS app from Windows.
- [Apple Developer Program](roadmap/ios.md#apple-developer-program) — **$99 per year**. Google Play is a one-time $25.
- [No sideload APK analog](roadmap/ios.md#no-sideload-apk-analog) — testers need TestFlight or the App Store, not an emailed install file.
- [App Review](roadmap/ios.md#app-review) — Apple is strict about WebView wrappers. This app is stronger than a website wrapper (bundled data, no hosted site), but review is still a risk.
- [MapLibre in WKWebView](roadmap/ios.md#maplibre-in-wkwebview) — the map has not been tested on iPhone.
- [Same app, two stores](roadmap/ios.md#same-app-two-stores) — Android and iPhone would share the pipeline, web UI, and dataset. The store listing is separate; the product is not.

## Where else to look

- [Known issues](known-issues.md) — documented data and app limits
- [Changelog](../CHANGELOG.md) — shipped and unreleased changes
- [GitHub issues](https://github.com/Dangis-Dangis/MichiganLandmarks/issues) — file or follow a specific problem

Build and Play Store steps are maintainer docs (`docs/dev/`) on
[GitHub](https://github.com/Dangis-Dangis/MichiganLandmarks). They are not in this Help overlay.
