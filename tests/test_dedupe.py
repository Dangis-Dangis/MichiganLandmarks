from __future__ import annotations

import unittest

import helpers
from pipeline.dedupe import merge
from pipeline.schema import Landmark


def lm(i: str, name: str, lat: float, lon: float, category: str = "lighthouse") -> Landmark:
    return helpers.landmark(
        id=i, name=name, latitude=lat, longitude=lon, category=category, source_id=i,
    )


class DedupeTests(unittest.TestCase):
    def test_inner_and_outer_lights_stay_separate(self):
        a = lm("a", "Grand Haven Inner Light", 43.0568, -86.2535)
        b = lm("b", "Grand Haven Outer Light", 43.0570, -86.2533)
        merged, clusters = merge([a, b])
        self.assertEqual(len(merged), 2)
        self.assertEqual(clusters, 0)

    def test_same_name_nearby_merges(self):
        a = lm("a", "Old Mackinac Point Light", 45.787, -84.728)
        b = lm("b", "Old Mackinac Point Light", 45.7871, -84.7281)
        merged, clusters = merge([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(clusters, 1)

    def test_cross_category_similar_name_merges(self):
        a = lm("a", "Fort Mackinac", 45.786, -84.735, category="state_park")
        b = helpers.landmark(
            id="b", name="Fort Mackinac", latitude=45.7861, longitude=-84.7351,
            category="nrhp_site", source_id="b",
        )
        merged, clusters = merge([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(clusters, 1)
        self.assertIn("also_nrhp_site", merged[0].tags)


if __name__ == "__main__":
    unittest.main()
