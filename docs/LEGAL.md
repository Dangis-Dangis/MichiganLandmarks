# Legal & Privacy

This page is the in-app Legal & Privacy topic (Help). It is not legal advice.

The standalone Play Store privacy page is [`legal.html`](../legal.html) at the repository root.

## Unofficial

**Michigan Landmarks is an independent hobby project.** It is not affiliated with,
endorsed by, or operated by:

- Michigan Department of Natural Resources (DNR) or Michigan History Center
- National Park Service (NPS)
- National Register of Historic Places (NRHP) program
- State of Michigan
- OpenStreetMap Foundation (beyond normal OSM attribution)
- Wikimedia Foundation (beyond normal content attribution)

Do not use government logos or wording that implies an official partnership.

## Privacy

*Last updated: September 2026*

Michigan Landmarks helps you browse publicly available landmark information
(lighthouses, historical markers, NRHP sites, state and national parks, and
museums) on a map and list. There are **no user accounts** and **no backend
server** operated by this project.

If you tap **Near me**, the app reads your device location **on your device
only** to sort landmarks by distance and center the map. Location is **not sent
to our servers** (we do not operate any). The native app requests the system
location permission; you can deny it and still browse the map manually.

The search box filters the bundled landmark list by name, county, and summary
text. Pressing Enter (or the keyboard Search / Go key) applies that filter and
dismisses the keyboard. Search text is not sent to any geocoding service.

Other network requests when you are online:

- **Map tiles** — loaded from OpenFreeMap (OpenStreetMap data).
- **Photos** — hotlinked from Michigan DNR ArcGIS or Wikimedia Commons when you
  open a landmark; not bundled in the install package.
- **Directions / Maps** — tapping Open in Maps, Directions, or the address line
  opens Google Maps in the browser (Google's privacy policy applies).
  Destinations may be GPS coordinates, name + address, or a street address.
  The app does not call a Places API or store those queries.
- **Official website, Wikipedia, Search the web, source, and nomination
  links** — open the respective sites when you tap them.

The Android app bundles the landmark index and detail files in the APK. When
you preview the UI in a desktop browser during development, a service worker may
cache files you have viewed. Neither mode stores your location history.

The app does not knowingly collect personal information from anyone.

Questions: open an issue on
[github.com/Dangis-Dangis/MichiganLandmarks](https://github.com/Dangis-Dangis/MichiganLandmarks)
or email [dangisdangis.dev@gmail.com](mailto:dangisdangis.dev@gmail.com).

## Sources

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

### Images

- **Marker photos** from Michigan DNR ArcGIS attachments are labeled
  `Michigan DNR Open Data` and credited to Michigan History Center.
- **Commons / Wikidata images** have per-file licenses resolved at build time via
  the Wikimedia Commons API.
- **Policy:** images without a known, allowed license are **omitted** from the
  dataset before export (`pipeline/licensing.py`).
- **Display:** photos are hotlinked where possible; the detail card shows credit
  and license. Photos are not bundled offline in the APK.

Allowed image licenses include public domain, CC0, Michigan DNR Open Data, GFDL,
and Creative Commons licenses that permit display with attribution (CC BY, CC BY-SA).
Non-commercial (NC) licenses are omitted.

### Text

- Historical marker plaque text comes from Michigan DNR open data.
- Some state park descriptions are enriched from Wikipedia (CC BY-SA 4.0). The
  pipeline stores `description_source` and `description_license`; the app shows
  attribution on the detail card.

### Outbound links

Detail cards link out only when the user taps them:

- **Official website** — the venue or agency site (`official_url`), never Wikipedia or NARA.
- **Open in Maps / Directions** — each action offers the destinations that exist
  for that record: GPS coordinates, name + address, and street address. Tapping a
  destination opens Google Maps (search or directions). No Google Places API and
  no stored Maps queries. A street-address line (when the record has one) is
  selectable text with a copy control.
- **Search the web** — a Google web search for the landmark name and locality.
- **Source data / Nomination** — the originating open catalog (Wikidata, DNR/NPS
  feature pages, IMLS dataset page, NARA nomination).

### Map tiles and search

- Basemap: OpenFreeMap (OpenStreetMap vector data, ODbL). MapLibre attribution
  control is enabled.
- Landmark search filters the bundled index locally. It does not call a
  geocoding service.
- MapLibre GL JS is bundled in the app and is not fetched from a CDN.

## Disclaimer

- Landmark locations and descriptions may be incomplete or inaccurate.
- **Not for navigation.** Verify access, safety, and hours on official sites.
- Information is provided for general reference only. Always verify hours, fees,
  and access on official agency websites before visiting.
- No warranty; use at your own risk.

## Software

Application source code (pipeline, web UI, Capacitor wrapper) is licensed under the
[MIT License](../LICENSE). Third-party library notices:
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).
