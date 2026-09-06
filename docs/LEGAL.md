# Legal and licensing

This document summarizes how Michigan Landmarks handles data, images, third-party
services, and distribution. It is not legal advice.

The in-app version lives at [`legal.html`](../legal.html). For Google Play, use
the public GitHub URL to that file as the privacy-policy link (see
[`PLAYSTORE.md`](PLAYSTORE.md)).

## Unofficial status

**Michigan Landmarks is an independent hobby project.** It is not affiliated with,
endorsed by, or operated by:

- Michigan Department of Natural Resources (DNR) or Michigan History Center
- National Park Service (NPS)
- National Register of Historic Places (NRHP) program
- State of Michigan
- OpenStreetMap Foundation (beyond normal OSM attribution)
- Wikimedia Foundation (beyond normal content attribution)

Do not use government logos or wording that implies an official partnership.

## Data sources and licenses

| Source | Records | License / terms | Attribution |
|--------|---------|-----------------|-------------|
| Michigan DNR / History Center historical markers | ~1,600 | Michigan open data (public; attribution requested) | Michigan History Center / Michigan DNR |
| Michigan DNR state park points | ~110 | Michigan open data (public; attribution requested) | Michigan DNR |
| NRHP points (NPS via Esri Federal) | ~1,500 | U.S. Government work (public domain) | National Park Service |
| NPS units (API or Wikidata fallback) | 8 | U.S. Government work / CC0 | National Park Service / Wikidata |
| Lighthouses (Wikidata) | ~120 | CC0 (Wikidata); images per-file on Commons | Wikidata / Wikimedia Commons |
| Museums (Wikidata + IMLS 2018 + Wikipedia list) | varies | CC0 / U.S. Gov PD / CC BY-SA 4.0 | Wikidata; IMLS; Wikipedia |
| Wikipedia (state park enrichment; museum text) | subset | CC BY-SA 4.0 | Link + license on detail card |
| FCC Area API (build-time county lookup) | — | U.S. Government | Used only during `pipeline.run` |
| Nominatim (build-time museum geocode leftovers) | subset | OSM / Nominatim usage policy | Rate-limited; identifying User-Agent |

Wikimedia access follows the
[Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy) and
[User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy):
identifying bot UA, `Accept-Encoding: gzip`, honor `429`/`Retry-After`, REST
enrichment concurrency ≤3, Commons Action API in serial batches, and museum-list
HTML via CDN `/wiki/…` (not Action API `parse`).

Official portals: [data.michigan.gov](https://data.michigan.gov),
[NPS Developer](https://www.nps.gov/subjects/developer/get-started.htm),
[NRHP](https://www.nps.gov/subjects/nationalregister/database-research.htm).

## Images

- **Marker photos** from Michigan DNR ArcGIS attachments are labeled
  `Michigan DNR Open Data` and credited to Michigan History Center.
- **Commons / Wikidata images** have per-file licenses resolved at build time via
  the Wikimedia Commons API.
- **Policy:** images without a known, allowed license are **omitted** from the
  dataset before export (`pipeline/licensing.py`).
- **Display:** photos are hotlinked where possible; the detail card shows credit
  and license. Photos are not bundled offline in the APK.

Allowed image licenses include public domain, CC0, Michigan DNR Open Data, and
Creative Commons licenses that permit display with attribution (CC BY, CC BY-SA).

## Text content

- Historical marker plaque text comes from Michigan DNR open data.
- Some state park descriptions are enriched from Wikipedia (CC BY-SA 4.0). The
  pipeline stores `description_source` and `description_license`; the app shows
  attribution on the detail card.

## Map tiles and place search

- Basemap: OpenFreeMap (OpenStreetMap vector data, ODbL). MapLibre attribution
  control is enabled.
- Place search: queries are sent to
  [Nominatim](https://nominatim.openstreetmap.org/) with an identifying
  `User-Agent`. Results are not stored on a server.

## Privacy (summary)

- **Location:** used on-device only (distance sort, map centering). Not sent to
  our servers — there are no accounts or backend.
- **Nominatim:** place names you search are sent to OpenStreetMap's Nominatim
  service when online.
- **Third-party loads:** map tiles, hotlinked images, and external direction
  links (Google Maps) load from their respective hosts when online.

Full text: [`legal.html#privacy`](../legal.html#privacy).

## Software license

Application source code (pipeline, web UI, Capacitor wrapper) is licensed under the
[MIT License](../LICENSE). Third-party library notices:
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

## Disclaimers

- Landmark locations and descriptions may be incomplete or inaccurate.
- **Not for navigation.** Verify access, safety, and hours on official sites.
- No warranty; use at your own risk.

## Maintainer actions

1. Re-run the pipeline when sources change; review `data/DATA_REPORT.md`.
2. Do not commit images or descriptions without provenance fields.
3. Keep Nominatim usage modest:
   - In the app: single-user place search only (not bulk geocoding).
   - In the pipeline: Wikipedia leftover geocoding via Nominatim is **opt-in**
     (`MUSEUM_GEOCODE=1`). When enabled, pacing is ≈2s between requests with 429
     backoff and a circuit breaker. Default builds use Wikidata + IMLS coordinates
     only; Wikipedia still supplies Defunct filtering and Active text enrichment.

## Play Store checklist

- [ ] Privacy policy URL → public GitHub link to `legal.html`
- [ ] Data safety: location used in-app, not collected
- [ ] Store listing does not imply government endorsement
- [ ] Re-run `python -m pipeline.run` after source changes; confirm
      `DATA_REPORT.md` shows zero unspecified image licenses
