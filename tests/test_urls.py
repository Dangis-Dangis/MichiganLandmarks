from __future__ import annotations

import unittest

import helpers  # noqa: F401
from pipeline import urls


class UrlSanitizeTests(unittest.TestCase):
    def test_javascript_rejected(self):
        self.assertIsNone(urls.as_official("javascript:alert(1)"))
        self.assertIsNone(urls.normalize_url("javascript:alert(1)"))
        self.assertIsNone(urls.normalize_url("data:text/html,hi"))
        self.assertIsNone(urls.as_official("https://javascript:alert(1)"))

    def test_wikipedia_not_official(self):
        wiki = "https://en.wikipedia.org/wiki/Mackinac_Island"
        self.assertIsNone(urls.as_official(wiki))
        self.assertEqual(urls.as_wikipedia(wiki), wiki)

    def test_nara_not_official(self):
        nara = "https://catalog.archives.gov/id/123"
        self.assertIsNone(urls.as_official(nara))
        self.assertTrue(urls.is_nara_url(nara))

    def test_arcgis_query_not_official(self):
        q = "https://services3.arcgis.com/x/arcgis/rest/services/Y/FeatureServer/0/query"
        self.assertIsNone(urls.as_official(q))

    def test_venue_https_kept(self):
        site = "https://www.nps.gov/slbe/index.htm"
        self.assertEqual(urls.as_official(site), site)

    def test_sanitize_moves_wiki_off_official(self):
        lm = helpers.landmark(official_url="https://en.wikipedia.org/wiki/Foo")
        urls.sanitize_landmark(lm)
        self.assertIsNone(lm.official_url)
        self.assertEqual(lm.attributes.get("wikipedia_url"), "https://en.wikipedia.org/wiki/Foo")


if __name__ == "__main__":
    unittest.main()
