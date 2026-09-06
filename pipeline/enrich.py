"""Best-effort enrichment: Commons image licensing + Wikipedia summaries for parks.

Enrichment never fabricates data. If a lookup is ambiguous or empty, the field is
left as None and the data report reflects the gap.

Commons licenses are resolved in serial batches (Action API, ≤1 concurrent) with
a pause between calls. Wikipedia REST summaries use ≤3 workers. See Wikimedia
Robot policy: https://wikitech.wikimedia.org/wiki/Robot_policy
"""
from __future__ import annotations

import re
import time
import urllib.parse

from . import config
from .concurrency import map_threaded
from .http_util import get_json, post_json
from .config import WIKIPEDIA_SUMMARY
from .schema import Landmark

_TAG_RE = re.compile(r"<[^>]+>")
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
FCC_AREA_API = "https://geo.fcc.gov/api/census/area"


def _county_for_point(lm: Landmark) -> str | None:
    """Look up the U.S. county for a point via the FCC Area API (official, free)."""
    if lm.latitude is None or lm.longitude is None:
        return None
    try:
        data = get_json(
            FCC_AREA_API,
            {"lat": lm.latitude, "lon": lm.longitude, "censusYear": 2020, "format": "json"},
            timeout=config.ENRICH_TIMEOUT,
            retries=config.ENRICH_RETRIES,
            backoff=config.ENRICH_BACKOFF,
        )
    except RuntimeError as exc:
        from . import log
        log.warn(f"county lookup failed for {lm.name!r}: {exc}")
        return None
    results = data.get("results") or []
    if not results:
        return None
    top = results[0]
    if (top.get("state_code") or "").upper() != "MI":
        return None
    name = top.get("county_name")
    return name.replace(" County", "").strip() if name else None


def fill_missing_counties(landmarks: list[Landmark]) -> int:
    """Backfill county from coordinates for records lacking one (lighthouses, parks,
    NPS units), so they can be assigned a region. Best-effort + parallel."""
    targets = [lm for lm in landmarks if not lm.county and lm.latitude is not None]
    results = map_threaded(_county_for_point, targets, config.COUNTY_WORKERS)
    filled = 0
    for lm, county in zip(targets, results):
        if county:
            lm.county = county
            filled += 1
    return filled


def wikimedia_reachable() -> bool:
    """Quick probe so the build degrades gracefully when Wikimedia is blocked/slow.

    Enrichment makes hundreds of Wikimedia calls; if the host is unreachable we skip
    it rather than letting every call burn its full timeout.
    """
    try:
        get_json(
            COMMONS_API,
            {"action": "query", "meta": "siteinfo", "format": "json"},
            timeout=8,
            retries=1,
        )
        return True
    except RuntimeError:
        return False


def commons_filename_from_url(url: str) -> str | None:
    """Extract the Commons file name from a Special:FilePath or upload.wikimedia URL."""
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(parsed.path)
    lower = path.lower()

    if "special:filepath/" in lower:
        idx = lower.index("special:filepath/")
        return urllib.parse.unquote(path[idx + len("Special:FilePath/"):]) or None

    if "/wiki/file:" in lower:
        idx = lower.index("/wiki/file:")
        return urllib.parse.unquote(path[idx + len("/wiki/File:"):]) or None

    if "upload.wikimedia.org" in parsed.netloc.lower():
        parts = [p for p in path.split("/") if p]
        if not parts:
            return None
        if "/thumb/" in lower and len(parts) >= 2:
            # .../thumb/<hash>/<hash>/<Original>.jpg/<width>px-...
            return parts[-2]
        return parts[-1]

    name = urllib.parse.unquote(path.rsplit("/", 1)[-1])
    return name or None


def commons_file_title(filename: str) -> str:
    """MediaWiki page title for a bare Commons filename."""
    name = filename.strip()
    if name.lower().startswith("file:"):
        return name
    return "File:" + name.replace(" ", "_")


def _normalize_filename_key(filename: str) -> str:
    return filename.replace("_", " ").strip().lower()


def _meta_value(meta: dict, key: str) -> str | None:
    raw = meta.get(key)
    if not isinstance(raw, dict):
        return None
    value = raw.get("value")
    if value is None:
        return None
    text = _TAG_RE.sub("", str(value)).strip()
    return text or None


def _parse_extmetadata(meta: dict) -> tuple[str | None, str | None]:
    lic = (
        _meta_value(meta, "LicenseShortName")
        or _meta_value(meta, "UsageTerms")
        or _meta_value(meta, "License")
    )
    artist = _meta_value(meta, "Artist") or _meta_value(meta, "Credit")
    return lic, artist


def _commons_query_titles(titles: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """Query imageinfo for a list of File: page titles. Keys are normalized filenames."""
    if not titles:
        return {}
    try:
        payload = post_json(
            COMMONS_API,
            {
                "action": "query",
                "titles": "|".join(titles),
                "prop": "imageinfo",
                "iiprop": "extmetadata",
                "redirects": "1",
                "format": "json",
            },
            timeout=config.ENRICH_TIMEOUT,
            retries=config.ENRICH_RETRIES,
            backoff=config.ENRICH_BACKOFF,
        )
    except RuntimeError:
        return {}
    out: dict[str, tuple[str | None, str | None]] = {}
    pages = payload.get("query", {}).get("pages", {})
    for page in pages.values():
        title = page.get("title") or ""
        if not title.startswith("File:"):
            continue
        filename = title[5:]
        infos = page.get("imageinfo") or []
        if not infos:
            out[_normalize_filename_key(filename)] = (None, None)
            continue
        out[_normalize_filename_key(filename)] = _parse_extmetadata(infos[0].get("extmetadata", {}))
    return out


def _commons_search_filename(hint: str) -> str | None:
    """Last-resort: find a File: page title via Commons search."""
    base = hint.rsplit(".", 1)[0] if "." in hint else hint
    try:
        payload = get_json(
            COMMONS_API,
            {
                "action": "query",
                "list": "search",
                "srsearch": f'file:"{base}"',
                "srnamespace": "6",
                "srlimit": "3",
                "format": "json",
            },
            timeout=config.ENRICH_TIMEOUT,
            retries=config.ENRICH_RETRIES,
            backoff=config.ENRICH_BACKOFF,
        )
    except RuntimeError:
        return None
    for hit in payload.get("query", {}).get("search", []):
        title = hit.get("title") or ""
        if title.startswith("File:"):
            return title[5:]
    return None


def commons_resolve_filenames(filenames: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """Resolve license + credit for many Commons files (batched, rate-limit friendly)."""
    unique = list(dict.fromkeys(f for f in filenames if f))
    if not unique:
        return {}

    resolved: dict[str, tuple[str | None, str | None]] = {}
    batch_size = config.COMMONS_BATCH_SIZE

    for start in range(0, len(unique), batch_size):
        chunk = unique[start : start + batch_size]
        titles = [commons_file_title(name) for name in chunk]
        batch_result = _commons_query_titles(titles)
        for name in chunk:
            key = _normalize_filename_key(name)
            info = batch_result.get(key)
            if info and info[0]:
                resolved[key] = info
        if start + batch_size < len(unique):
            time.sleep(config.COMMONS_BATCH_PAUSE)

    missing = [
        name for name in unique
        if not (resolved.get(_normalize_filename_key(name)) or (None, None))[0]
    ]
    for name in missing:
        alt = _commons_search_filename(name)
        if not alt:
            continue
        hit = _commons_query_titles([commons_file_title(alt)])
        info = hit.get(_normalize_filename_key(alt))
        if info and info[0]:
            resolved[_normalize_filename_key(name)] = info
        time.sleep(0.3)

    return resolved


def commons_image_info(image_url: str | None) -> tuple[str | None, str | None]:
    """Return (license_short_name, attribution_text) for a single Commons file URL."""
    filename = commons_filename_from_url(image_url)
    if not filename:
        return None, None
    lookup = commons_resolve_filenames([filename])
    return lookup.get(_normalize_filename_key(filename), (None, None))


def wikipedia_summary(title: str) -> dict | None:
    try:
        data = get_json(
            WIKIPEDIA_SUMMARY + urllib.parse.quote(title.replace(" ", "_")),
            timeout=config.ENRICH_TIMEOUT,
            retries=config.ENRICH_RETRIES,
            backoff=config.ENRICH_BACKOFF,
        )
    except RuntimeError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("type") == "disambiguation" or "extract" not in data:
        return None
    return data


def _enrich_one_park(lm: Landmark) -> dict | None:
    """Worker: look up a single park's Wikipedia summary (+ image license). Pure I/O."""
    base = lm.name.strip()
    candidates = [base]
    if "state park" not in base.lower() and "recreation" not in base.lower():
        candidates.append(f"{base} State Park")
    summary = None
    for title in candidates:
        summary = wikipedia_summary(title)
        if summary:
            break
    if not summary:
        return None
    result: dict = {
        "description": summary.get("extract"),
        "description_source": "Wikipedia",
        "description_license": config.WIKIPEDIA_TEXT_LICENSE,
    }
    page = summary.get("content_urls", {}).get("desktop", {}).get("page")
    if page:
        result["wikipedia_url"] = page
    thumb = (summary.get("thumbnail") or {}).get("source")
    if thumb:
        result["image_url"] = thumb
        result["image_credit"] = "Wikimedia Commons"
    return result


def enrich_state_parks(landmarks: list[Landmark]) -> int:
    """Fill missing description/image for state parks from Wikipedia (parallel)."""
    targets = [lm for lm in landmarks if lm.category == "state_park" and not lm.description]
    results = map_threaded(_enrich_one_park, targets, config.ENRICH_WORKERS)
    enriched = 0
    for lm, res in zip(targets, results):
        if not res:
            continue
        lm.description = res.get("description")
        if res.get("description_source"):
            lm.attributes["description_source"] = res["description_source"]
            lm.attributes["description_license"] = res.get("description_license")
        if res.get("wikipedia_url"):
            lm.attributes["wikipedia_url"] = res["wikipedia_url"]
            if not lm.official_url:
                lm.official_url = res["wikipedia_url"]
        if res.get("image_url") and not lm.image_url:
            lm.image_url = res["image_url"]
            lm.image_credit = res.get("image_credit")
        enriched += 1
    return enriched


def resolve_commons_licenses(landmarks: list[Landmark]) -> int:
    """Resolve Commons licenses for all Wikimedia images lacking one (batched)."""
    pending = [
        lm for lm in landmarks
        if lm.image_url and not lm.image_license
        and ("wikimedia.org" in lm.image_url or "wikipedia.org" in lm.image_url)
    ]
    if not pending:
        return 0

    url_to_filename = {
        lm.image_url: commons_filename_from_url(lm.image_url)
        for lm in pending
        if commons_filename_from_url(lm.image_url)
    }
    filenames = list(dict.fromkeys(url_to_filename.values()))
    lookup = commons_resolve_filenames(filenames)

    resolved = 0
    for lm in pending:
        filename = url_to_filename.get(lm.image_url)
        if not filename:
            continue
        info = lookup.get(_normalize_filename_key(filename))
        if not info:
            continue
        lic, artist = info
        if lic:
            lm.image_license = lic
            resolved += 1
        if artist:
            lm.image_credit = artist
        elif not lm.image_credit:
            lm.image_credit = "Wikimedia Commons"
    return resolved
