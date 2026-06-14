"""Licensing policy for images and text before data is exported or bundled.

Images without a known allowed license are stripped so APK / committed JSON
never redistributes unattributed media. Wikipedia-sourced text provenance is
set during enrichment (see enrich.py).
"""
from __future__ import annotations

from .schema import Landmark

# Licenses we accept for hotlinking and metadata in exported data.
# Matching is case-insensitive; Commons returns varied short names.
_ALLOWED_IMAGE_LICENSE_SUBSTRINGS = (
    "michigan dnr open data",
    "public domain",
    "cc0",
    "cc by",
    "cc-by",
    "pd",
    "public domain mark",
    "no restrictions",
    "free use",
    "gfdl",
)


def is_allowed_image_license(license: str | None) -> bool:
    if not license or not str(license).strip():
        return False
    key = str(license).strip().lower()
    return any(sub in key for sub in _ALLOWED_IMAGE_LICENSE_SUBSTRINGS)


def strip_unlicensed_images(landmarks: list[Landmark]) -> int:
    """Remove image fields when license is missing or not on the allow-list."""
    stripped = 0
    for lm in landmarks:
        if not lm.image_url:
            continue
        if is_allowed_image_license(lm.image_license):
            continue
        lm.image_url = None
        lm.image_credit = None
        lm.image_license = None
        stripped += 1
    return stripped
