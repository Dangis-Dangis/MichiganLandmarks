"""URL and address helpers for fetchers, merge, KML, and the app's matching rules.

Venue websites go in ``official_url``. Encyclopedia and archive pages do not.
Maps search is name + locality; directions use coordinates.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import quote_plus, urlparse, urlunparse

if TYPE_CHECKING:
    from .schema import Landmark

_STATE_ONLY = frozenset({"mi", "michigan", "usa", "us"})
_STREET_RE = re.compile(r"^\d+\s")
_MI_RE = re.compile(r"\bmi\b", re.IGNORECASE)


def normalize_url(url: str | None) -> str | None:
    """https + lowercased host; drop empties. Path/query case is preserved."""
    if not url:
        return None
    text = str(url).strip()
    if not text or text.lower() in {"none", "n/a", "null"}:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.IGNORECASE):
        text = "https://" + text
    parsed = urlparse(text)
    if not parsed.netloc:
        return None
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    scheme = "https"
    host = parsed.netloc.lower()
    return urlunparse((scheme, host, parsed.path or "", parsed.params, parsed.query, parsed.fragment))


def _host(url: str) -> str:
    try:
        host = urlparse(url).hostname
        return (host or "").lower()
    except ValueError:
        return ""


def is_encyclopedia_url(url: str | None) -> bool:
    if not url:
        return False
    host = _host(url)
    return host.endswith("wikipedia.org") or host.endswith("wikimedia.org")


def is_nara_url(url: str | None) -> bool:
    if not url:
        return False
    host = _host(url)
    return host.endswith("archives.gov") or host.endswith("nara.gov")


def is_source_dump_url(url: str | None) -> bool:
    """Machine dumps that should not be presented as a venue website."""
    if not url:
        return False
    lower = url.lower()
    host = _host(url)
    if "imls.gov" in host and lower.endswith(".zip"):
        return True
    if "arcgis.com" in host and ("/query" in lower or "/featureserver" in lower):
        return True
    return False


def is_venue_official_url(url: str | None) -> bool:
    """True when ``url`` is a usable venue/agency site, not wiki/NARA/a data dump."""
    normalized = normalize_url(url)
    if not normalized:
        return False
    if is_encyclopedia_url(normalized) or is_nara_url(normalized):
        return False
    if is_source_dump_url(normalized):
        return False
    return True


def as_official(url: str | None) -> str | None:
    normalized = normalize_url(url)
    return normalized if is_venue_official_url(normalized) else None


def as_wikipedia(url: str | None) -> str | None:
    normalized = normalize_url(url)
    if normalized and is_encyclopedia_url(normalized) and "redlink" not in normalized.lower():
        if "action=edit" in normalized.lower():
            return None
        return normalized
    return None


def prefer_official(current: str | None, candidate: str | None) -> str | None:
    """Keep a venue site; never keep encyclopedia/NARA as official."""
    return as_official(current) or as_official(candidate)


def is_street_address(address: str | None) -> bool:
    """True for lines that start with a house number (not 'MI' or city+ZIP)."""
    if not address:
        return False
    text = str(address).strip()
    if not text or text.lower() in _STATE_ONLY:
        return False
    return bool(_STREET_RE.match(text))


def display_address(address: str | None, city: str | None) -> str | None:
    """Human location line: street (+ city, MI) or city, MI. Never 'MI' alone."""
    if is_street_address(address):
        line = address.strip()
        if city and city.lower() not in line.lower():
            line = f"{line}, {city}"
        if not _MI_RE.search(line):
            line = f"{line}, MI"
        return line
    if city and city.strip() and city.strip().lower() not in _STATE_ONLY:
        return f"{city.strip()}, MI"
    return None


def maps_search_query(
    name: str | None,
    address: str | None,
    city: str | None,
    county: str | None,
    lat: float | None,
    lon: float | None,
) -> str:
    """Name + locality for Google Maps search; coordinates as last resort."""
    title = (name or "").strip()
    street = address.strip() if is_street_address(address) else ""
    town = (city or "").strip()
    parts: list[str] = []
    if title:
        parts.append(title)
    if street:
        parts.append(street)
    if town and (not street or town.lower() not in street.lower()):
        parts.append(town)
    if len(parts) >= 2:
        q = ", ".join(parts)
        return q if _MI_RE.search(q) else f"{q}, MI"
    if title and county:
        return f"{title}, {county} County, MI"
    if lat is not None and lon is not None:
        return f"{lat},{lon}"
    return title or ""


def maps_search_url(lm: Landmark) -> str:
    q = maps_search_query(lm.name, lm.address, lm.city, lm.county, lm.latitude, lm.longitude)
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(q)


def maps_directions_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"


def feature_page_url(layer: str, object_id) -> str | None:
    """Browser-openable ArcGIS feature page (HTML), not a JSON query."""
    if object_id is None or object_id == "":
        return None
    return f"{layer.rstrip('/')}/{object_id}"


def sanitize_landmark(lm: Landmark) -> None:
    """Move encyclopedia/NARA off ``official_url``; drop non-street addresses."""
    official = lm.official_url
    if official:
        if is_encyclopedia_url(official):
            wiki = as_wikipedia(official) or normalize_url(official)
            if wiki:
                lm.attributes.setdefault("wikipedia_url", wiki)
            lm.official_url = None
        elif is_nara_url(official):
            nara = normalize_url(official)
            if nara:
                lm.attributes.setdefault("nara_url", nara)
            lm.official_url = None
        elif is_source_dump_url(official):
            lm.official_url = None
        else:
            lm.official_url = as_official(official)
    if lm.address and not is_street_address(lm.address):
        lm.address = None
