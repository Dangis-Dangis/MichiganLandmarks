# Known issues

These are documented limitations of the dataset and app, not a live bug tracker. See also [What's next](roadmap.md) and the [changelog](../CHANGELOG.md).

## Data gaps

- State-park descriptions and photos come from Wikipedia enrichment at **build** time. If Wikimedia is unreachable during `pipeline.run`, those fields stay empty until a later rebuild.
- NRHP listings are **points** only (polygons are withheld by NPS). Some coordinates carry minor source error. Listing years come from the National Register certification date when the source provides one; GIS layer create-dates are not used.
- State parks and NPS Data API units often have no built or established year.
- Pins with `location_quality` of `name` or `locality` are approximate. The detail card shows a warning. [Using the app](using-the-app.md#approximate-pins) explains the filter that hides locality pins.
- Museum leftover geocoding (Wikipedia leftovers not in Wikidata/IMLS) may still land on a city/township pin.

## App behavior

- Basemap tiles and landmark photos need a network. The landmark index, detail text, MapLibre, and this Help overlay do not.
- Search does not look up addresses or place names on the internet; it only filters bundled records.
- The app is unofficial and not intended for navigation. Verify hours, fees, and access on official sites.

## Reporting a problem

Open an issue at [github.com/Dangis-Dangis/MichiganLandmarks](https://github.com/Dangis-Dangis/MichiganLandmarks/issues) or email [dangisdangis.dev@gmail.com](mailto:dangisdangis.dev@gmail.com).
