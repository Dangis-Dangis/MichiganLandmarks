from __future__ import annotations

import unittest

import helpers
from pipeline.run import _ensure_unique_ids


class UniqueIdTests(unittest.TestCase):
    def test_suffix_order_is_stable_across_input_order(self):
        def make(lat: float, sid: str):
            return helpers.landmark(
                id="nrhp_site:nrhp:ref",
                name="Multi-site listing",
                category="nrhp_site",
                latitude=lat,
                longitude=-84.0,
                source_id=sid,
            )

        specs = [(45.2, "b"), (45.0, "a"), (45.1, "c")]
        first = [make(lat, sid) for lat, sid in specs]
        second = [make(lat, sid) for lat, sid in reversed(specs)]
        _ensure_unique_ids(first)
        _ensure_unique_ids(second)
        by_sid = lambda rows: {lm.source_id: lm.id for lm in rows}
        self.assertEqual(by_sid(first), by_sid(second))
        ids = set(by_sid(first).values())
        self.assertEqual(len(ids), 3)
        self.assertIn("nrhp_site:nrhp:ref", ids)

    def test_skips_existing_suffix(self):
        a = helpers.landmark(id="same", latitude=1.0, source_id="1")
        b = helpers.landmark(id="same", latitude=2.0, source_id="2")
        c = helpers.landmark(id="same-2", latitude=9.0, source_id="3")
        n = _ensure_unique_ids([a, b, c])
        self.assertEqual(n, 1)
        ids = {a.id, b.id, c.id}
        self.assertEqual(len(ids), 3)
        self.assertIn("same-2", ids)


if __name__ == "__main__":
    unittest.main()
