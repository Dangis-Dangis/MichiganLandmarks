from __future__ import annotations

import unittest

import helpers
from pipeline.schema import stamp_location_quality


class LocationQualityTests(unittest.TestCase):
    def test_imls_without_via_is_not_site(self):
        lm = helpers.landmark(source="IMLS", attributes={"museum_sources": ["IMLS"]})
        self.assertEqual(stamp_location_quality(lm), "name")
        self.assertEqual(lm.location_quality, "name")

    def test_wikidata_source_coords_are_site(self):
        lm = helpers.landmark(source="Wikidata", attributes={"museum_sources": ["Wikidata"]})
        self.assertEqual(stamp_location_quality(lm), "site")

    def test_existing_locality_kept(self):
        lm = helpers.landmark(location_quality="locality")
        self.assertEqual(stamp_location_quality(lm), "locality")

    def test_wikipedia_article_upgrade_is_site(self):
        lm = helpers.landmark(
            source="IMLS",
            attributes={"geocode_via": "wikipedia_summary", "geocode_precision": "article"},
        )
        self.assertEqual(stamp_location_quality(lm), "site")

    def test_nominatim_city_is_locality(self):
        lm = helpers.landmark(attributes={"geocode_via": "nominatim_city"})
        self.assertEqual(stamp_location_quality(lm), "locality")


if __name__ == "__main__":
    unittest.main()
