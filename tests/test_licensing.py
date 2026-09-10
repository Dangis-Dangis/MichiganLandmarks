from __future__ import annotations

import unittest

import helpers  # noqa: F401
from pipeline.licensing import is_allowed_image_license, strip_unlicensed_images


class LicenseAllowListTests(unittest.TestCase):
    def test_allows_cc_by_and_sa(self):
        self.assertTrue(is_allowed_image_license("CC BY-SA 4.0"))
        self.assertTrue(is_allowed_image_license("CC BY 2.0"))
        self.assertTrue(is_allowed_image_license("Cc-by-sa-3.0"))

    def test_rejects_noncommercial(self):
        self.assertFalse(is_allowed_image_license("CC BY-NC-SA 3.0"))
        self.assertFalse(is_allowed_image_license("CC-BY-NC-2.0"))

    def test_allows_public_domain_tokens(self):
        self.assertTrue(is_allowed_image_license("Public domain"))
        self.assertTrue(is_allowed_image_license("PD-US"))
        self.assertTrue(is_allowed_image_license("CC0"))
        self.assertTrue(is_allowed_image_license("Michigan DNR Open Data"))
        self.assertTrue(is_allowed_image_license("GFDL"))

    def test_pd_is_not_a_bare_substring(self):
        self.assertFalse(is_allowed_image_license("adapted"))
        self.assertFalse(is_allowed_image_license("All rights reserved"))
        self.assertFalse(is_allowed_image_license(""))
        self.assertFalse(is_allowed_image_license(None))

    def test_strip_removes_nc_image(self):
        lm = helpers.landmark(
            image_url="https://upload.wikimedia.org/wikipedia/commons/x.jpg",
            image_license="CC BY-NC 2.0",
            image_credit="Someone",
        )
        n = strip_unlicensed_images([lm])
        self.assertEqual(n, 1)
        self.assertIsNone(lm.image_url)


if __name__ == "__main__":
    unittest.main()
