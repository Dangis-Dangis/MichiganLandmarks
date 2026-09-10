from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import helpers  # noqa: F401
from pipeline import geocode


class QueryVariantTests(unittest.TestCase):
    def test_adds_michigan_and_ampersand_form(self):
        variants = geocode.query_variants("Foo & Bar Museum, Detroit")
        self.assertTrue(any("Michigan" in v for v in variants))
        self.assertTrue(any("and" in v.lower() for v in variants))

    def test_empty_query(self):
        self.assertEqual(geocode.query_variants(""), [])
        self.assertEqual(geocode.query_variants("   "), [])


class PickResultTests(unittest.TestCase):
    def test_name_purpose_rejects_admin(self):
        payload = [
            {"lon": "-83.7", "lat": "42.3", "class": "place", "type": "city"},
            {"lon": "-83.71", "lat": "42.31", "class": "tourism", "type": "museum"},
        ]
        picked = geocode._pick_result(payload, "name")
        self.assertIsNotNone(picked)
        self.assertEqual(picked["osm_class"], "tourism")

    def test_locality_prefers_admin(self):
        payload = [
            {"lon": "-83.71", "lat": "42.31", "class": "tourism", "type": "museum"},
            {"lon": "-83.7", "lat": "42.3", "class": "place", "type": "city"},
        ]
        picked = geocode._pick_result(payload, "locality")
        self.assertEqual(picked["osm_class"], "place")


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        geocode._CACHE_DIR = Path(self.tmp.name)
        geocode.reset_circuit()

    def test_cached_miss_skips_network(self):
        geocode._cache_put_miss("no such place, Michigan")
        self.assertIsNone(geocode._cache_get("no such place, Michigan"))

        calls = {"n": 0}

        def boom(q, *, purpose="name", logger=None):
            calls["n"] += 1
            return None

        with patch.object(geocode, "_nominatim_search", side_effect=boom):
            self.assertIsNone(geocode.geocode_michigan("no such place"))
        self.assertEqual(calls["n"], 0)

    def test_cache_hit_returns_coords(self):
        geocode._cache_put("hit museum, Michigan", {
            "lon": -83.7, "lat": 42.3, "osm_class": "tourism", "osm_type": "museum",
        })
        with patch.object(geocode, "_nominatim_search") as search:
            got = geocode.geocode_michigan("hit museum")
            search.assert_not_called()
        self.assertEqual(got, (-83.7, 42.3))

    def test_empty_nominatim_payload_is_cached_miss(self):
        class Resp:
            headers = {"Content-Encoding": ""}

            def read(self):
                return b"[]"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        calls = {"n": 0}

        def fake_open(req, timeout=None):
            calls["n"] += 1
            return Resp()

        with patch("pipeline.geocode.time.sleep"), patch("urllib.request.urlopen", fake_open):
            geocode.geocode_michigan("Definitely Missing Museum 999")
            n = calls["n"]
            self.assertGreater(n, 0)
            geocode.geocode_michigan("Definitely Missing Museum 999")
            self.assertEqual(calls["n"], n)


if __name__ == "__main__":
    unittest.main()
