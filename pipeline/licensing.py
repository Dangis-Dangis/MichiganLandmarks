"""Licensing policy for images and text before data is exported or bundled.

Images without a known allowed license are stripped so APK / committed JSON
never redistributes unattributed media. Wikipedia-sourced text provenance is
set during enrichment (see enrich.py).
"""
from __future__ import annotations

import re

from . import log
from .schema import Landmark

# Commons LicenseShortName values vary (CC BY-SA 4.0, Cc-by-sa-3.0, PD-US, …).
_NC_RE = re.compile(r"(?:^|[\s_\-/])nc(?:[\s_\-/]|$)|non[\s\-]?commercial", re.I)
_CC_BY_RE = re.compile(
    r"\bcc[\s\-]?by(?:[\s\-]?sa)?(?:[\s\-]?nd)?(?:[\s\-]?\d+(?:\.\d+)?)?\b",
    re.I,
)
_PD_TOKEN_RE = re.compile(r"(?:^|[\s,;/(])pd(?:[-_\s]|$)", re.I)


def is_allowed_image_license(license: str | None) -> bool:
    if not license or not str(license).strip():
        return False
    raw = str(license).strip()
    key = raw.lower()
    compact = re.sub(r"[\s_\-]+", "", key)

    if _NC_RE.search(key) or "noncommercial" in compact:
        return False
    if "michigan dnr open data" in key:
        return True
    if "public domain" in key or "publicdomain" in compact or "public domain mark" in key:
        return True
    if key in {"pd", "pdm"} or key.startswith("pd-") or _PD_TOKEN_RE.search(key):
        return True
    if "cc0" in compact or key.startswith("cc-0") or "cc zero" in key:
        return True
    if "gfdl" in key:
        return True
    if "no restrictions" in key:
        return True
    if _CC_BY_RE.search(key):
        return True
    return False


def strip_unlicensed_images(landmarks: list[Landmark]) -> int:
    """Remove image fields when license is missing or not on the allow-list."""
    stripped = 0
    for lm in landmarks:
        if not lm.image_url:
            continue
        if is_allowed_image_license(lm.image_license):
            continue
        license_was = lm.image_license
        lm.image_url = None
        lm.image_credit = None
        lm.image_license = None
        stripped += 1
        log.debug(log.fmt(
            "license",
            f"stripped image for {lm.name!r} (license={license_was!r})",
        ))
    return stripped
