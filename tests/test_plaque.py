from __future__ import annotations

import unittest

import helpers  # noqa: F401
from pipeline.plaque import english_plaque_text, partition_plaque


class PlaqueTests(unittest.TestCase):
    def test_english_front_other_back(self):
        text = (
            "This marker commemorates the founding of the village in 1836 and tells "
            "the story of the mill that stood on the river for many years afterward.\n\n"
            "Ten znacznik upamietnia zalozenie wsi roku tysiac osiemset trzydziesci "
            "szesc oraz opisuje dalsze dzieje mlyna nad rzeka przez wiele kolejnych "
            "lat istnienia osady mlyna rzeki mostu i rynku miejscowosci nad woda."
        )
        en, other = partition_plaque(text)
        self.assertIn("commemorates", en or "")
        self.assertIn("znacznik", other or "")

    def test_same_as_front_stub_dropped(self):
        text = "The mill was built on the river.\n\nSame as front."
        en, other = partition_plaque(text)
        self.assertIn("mill", en or "")
        self.assertIsNone(other)

    def test_short_side_treated_as_english(self):
        self.assertEqual(english_plaque_text("Fort Mackinac"), "Fort Mackinac")

    def test_empty(self):
        self.assertIsNone(english_plaque_text(None))
        self.assertIsNone(english_plaque_text(""))


if __name__ == "__main__":
    unittest.main()
