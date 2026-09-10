from __future__ import annotations

import unittest

import helpers  # noqa: F401
from pipeline.sources import museums


WIKI_HTML = """
<html><body>
<h2 id="Active">Active</h2>
<table class="wikitable">
<tr><th>Name</th><th>Location</th><th>County</th><th>Region</th><th>Type</th><th>Summary</th></tr>
<tr>
  <td><a href="/wiki/Foo_Museum">Foo Museum</a></td>
  <td>Detroit</td><td>Wayne</td><td>SE</td>
  <td>History</td><td>A local history museum.</td>
</tr>
<tr>
  <td><a href="/wiki/Bar?redlink=1">Redlink Museum</a></td>
  <td>Lansing</td><td>Ingham</td><td>C</td>
  <td>Art</td><td>Has no article yet.</td>
</tr>
</table>
<h2 id="Defunct">Defunct</h2>
<ul>
<li>Old Closed Museum, Flint</li>
<li>Another Gone Place [1]</li>
</ul>
</body></html>
"""


class WikiListParserTests(unittest.TestCase):
    def test_parses_active_and_defunct(self):
        parser = museums._WikiMuseumListParser()
        parser.feed(WIKI_HTML)
        names = [r["name"] for r in parser.active]
        self.assertIn("Foo Museum", names)
        self.assertIn("Redlink Museum", names)
        foo = next(r for r in parser.active if r["name"] == "Foo Museum")
        self.assertEqual(foo["url"], "https://en.wikipedia.org/wiki/Foo_Museum")
        self.assertEqual(foo["location"], "Detroit")
        self.assertEqual(foo["type"], "History")
        red = next(r for r in parser.active if r["name"] == "Redlink Museum")
        self.assertIsNone(red["url"])
        self.assertIn("Old Closed Museum", parser.defunct)
        self.assertIn("Another Gone Place", parser.defunct)


class LeftoverArticleMatchTests(unittest.TestCase):
    def test_two_shared_tokens_is_not_enough(self):
        self.assertFalse(museums._leftover_article_matches(
            "Grand Rapids Public Museum",
            "Grand Rapids Art Museum",
            "Grand_Rapids_Art_Museum",
        ))

    def test_same_building_alias_accepted(self):
        self.assertTrue(museums._leftover_article_matches(
            "Foo House Museum", "Foo House", "Foo_House",
        ))

    def test_parent_park_rejected(self):
        self.assertFalse(museums._leftover_article_matches(
            "Ludington Heritage Museum",
            "Ludington State Park",
            "Ludington_State_Park",
        ))


if __name__ == "__main__":
    unittest.main()
