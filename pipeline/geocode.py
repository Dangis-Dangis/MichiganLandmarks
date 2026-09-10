"""Rate-limited forward geocoding for build-time gaps (museum Wikipedia leftovers).

Uses OpenStreetMap Nominatim with an identifying user-agent. On by default;
skip with ``--skip-nominatim-geocode``. On HTTP 429 the circuit opens immediately so a build
does not sit in a retry storm — Wikidata + IMLS coverage is enough to finish.

Nominatim usage policy (https://operations.osmfoundation.org/policies/nominatim/):
≤1 req/s, single thread, cache results, identifying User-Agent. Skip leftover
Nominatim (``--skip-nominatim-geocode``) when you do not need those pins.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, log

_logger = log.get_logger(__name__)

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
# Nominatim viewbox: left(lon), top(lat), right(lon), bottom(lat)
_MI_VIEWBOX = "-90.5,48.3,-82.0,41.5"
_MIN_INTERVAL = 2.0  # stay under 1 req/s
_last_request = 0.0
_circuit_open = False
_CACHE_DIR = config.CACHE_DIR / "nominatim"

_NAME_PREFERRED_CLASS = frozenset({
    "tourism", "amenity", "building", "historic", "man_made", "leisure", "shop",
    "craft", "office",
})
_ADMIN_CLASS = frozenset({"place", "boundary"})
_ADMIN_TYPE = frozenset({
    "city", "town", "village", "hamlet", "township", "county", "state",
    "administrative", "suburb", "neighbourhood", "municipality", "isolated_dwelling",
})
_GENERIC_NAME_TAILS = (
    r"\s+Historical Society Museum$",
    r"\s+Historical Society$",
    r"\s+Heritage Center$",
    r"\s+Heritage Centre$",
    r"\s+Historical Museum$",
    r"\s+Area Museum$",
    r"\s+Area History Museum$",
    r"\s+Museum and Library$",
    r"\s+Museum$",
)


class RateLimitExceeded(RuntimeError):
    """Nominatim is rate-limiting; callers should stop issuing more requests."""


def reset_circuit() -> None:
    global _circuit_open
    _circuit_open = False


def circuit_is_open() -> bool:
    return _circuit_open


def _cache_path(query: str):
    digest = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{digest}.json"


def _cache_get(query: str) -> dict | None | object:
    """Return a result dict, None for a cached miss, or _UNCACHED."""
    if not config.CACHE_READ:
        return _UNCACHED
    path = _cache_path(query)
    if not path.is_file():
        return _UNCACHED
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _UNCACHED
    if data.get("miss"):
        return None
    try:
        float(data["lon"])
        float(data["lat"])
    except (KeyError, TypeError, ValueError):
        return _UNCACHED
    return data


def _cache_put(query: str, result: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(query)
    payload = {
        "query": query,
        "lon": result["lon"],
        "lat": result["lat"],
        "osm_class": result.get("osm_class"),
        "osm_type": result.get("osm_type"),
        "miss": False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _cache_put_miss(query: str) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(query)
    path.write_text(
        json.dumps({"query": query, "miss": True}, ensure_ascii=False),
        encoding="utf-8",
    )


_UNCACHED = object()


def _normalize_ampersand(text: str) -> str:
    return re.sub(r"\s*&\s*", " and ", text)


def _light_variants(text: str) -> list[str]:
    """OSM usually indexes 'Lighthouse', not Wikipedia's 'Light' / 'Light Station'."""
    if "Lighthouse" in text or not re.search(r"\bLight\b", text):
        return []
    if re.search(r"\bLight Station\b", text):
        return [re.sub(r"\bLight Station\b", "Lighthouse", text)]
    return [re.sub(r"\bLight\b", "Lighthouse", text)]


def _place_typos(text: str) -> list[str]:
    """Wikipedia list typos such as Elk Rapid → Elk Rapids."""
    out: list[str] = []
    if re.search(r"\bElk Rapid\b", text) and "Elk Rapids" not in text:
        out.append(re.sub(r"\bElk Rapid\b", "Elk Rapids", text))
    return out


def _stripped_name_head(name: str) -> list[str]:
    """Shorter OSM-friendly names (drop Museum / Historical Society, …)."""
    heads = []
    current = name.strip()
    for pat in _GENERIC_NAME_TAILS:
        shorter = re.sub(pat, "", current, flags=re.IGNORECASE).strip(" ,")
        if shorter and shorter.lower() != current.lower() and shorter not in heads:
            heads.append(shorter)
            current = shorter
    return heads


def _stripped_is_place_only(head: str, loc: str) -> bool:
    """True when stripping 'Museum' etc. left only the city/township/county name."""
    h = {t for t in re.split(r"\W+", head.lower()) if t and t not in {"michigan", "the", "of"}}
    p = {t for t in re.split(r"\W+", loc.lower()) if t and t not in {"michigan", "the", "of"}}
    if not h:
        return True
    if p and h <= p:
        return True
    place_words = {"city", "township", "village", "county", "charter"}
    if p and (h - place_words) <= p:
        return True
    return False


def query_variants(query: str) -> list[str]:
    """Build softer Nominatim queries from a Wikipedia-style title + place string.

    Exact museum names often miss in OSM; shorter / normalized forms often hit.
    """
    q = (query or "").strip()
    if not q:
        return []
    if "michigan" not in q.lower():
        q = f"{q}, Michigan"

    variants: list[str] = []

    def add(s: str) -> None:
        s = re.sub(r"\s+", " ", s).strip(" ,")
        if s and s not in variants:
            variants.append(s)

    def add_family(s: str) -> None:
        add(s)
        add(_normalize_ampersand(s))
        for lit in _light_variants(s):
            add(lit)
            add(_normalize_ampersand(lit))
        for typo in _place_typos(s):
            add(typo)
            add(_normalize_ampersand(typo))

    add_family(q)

    parts = [p.strip() for p in q.split(",") if p.strip()]
    if len(parts) >= 3 and parts[-1].lower() == "michigan":
        add_family(f"{parts[0]}, Michigan")
        loc = parts[1]
        for head in _stripped_name_head(parts[0]):
            if _stripped_is_place_only(head, loc):
                continue
            add_family(f"{head}, {loc}, Michigan")
            add_family(f"{head}, Michigan")
    elif len(parts) == 2 and parts[-1].lower() == "michigan":
        for head in _stripped_name_head(parts[0]):
            add_family(f"{head}, Michigan")

    return variants


def _is_admin_result(result: dict) -> bool:
    osm_class = (result.get("osm_class") or "").lower()
    osm_type = (result.get("osm_type") or "").lower()
    if osm_class in _ADMIN_CLASS:
        return True
    if osm_type in _ADMIN_TYPE:
        return True
    return False


def _usable_for_purpose(result: dict | None, purpose: str) -> bool:
    if not result:
        return False
    if purpose == "name" and _is_admin_result(result):
        return False
    return True


def geocode_michigan(
    query: str,
    *,
    purpose: str = "name",
    logger: logging.Logger | None = None,
) -> tuple[float, float] | None:
    """Return (lon, lat) for a place query constrained to Michigan, or None.

    ``purpose="name"`` rejects city/township/county hits so they are not labeled
    as a named building. ``purpose="locality"`` allows those settlement results.
    Pass ``logger`` to record hits on a caller-specific named logger.
    """
    global _circuit_open
    log_ = logger or _logger
    if _circuit_open:
        raise RateLimitExceeded("Nominatim geocode circuit open")

    variants = query_variants(query)
    if not variants:
        return None

    for variant in variants:
        cached = _cache_get(variant)
        stale_name_cache = (
            purpose == "name"
            and isinstance(cached, dict)
            and "osm_class" not in cached
        )
        if cached is None:
            continue
        if (
            isinstance(cached, dict)
            and not stale_name_cache
            and _usable_for_purpose(cached, purpose)
        ):
            if variant != variants[0]:
                log_.info(f"geocode cache hit via variant {variant!r} (for {variants[0]!r})")
            return float(cached["lon"]), float(cached["lat"])
        if isinstance(cached, dict) and not stale_name_cache:
            continue

        result = _nominatim_search(variant, purpose=purpose, logger=log_)
        if result is not None:
            _cache_put(variant, result)
            if variant != variants[0]:
                orig_head = variants[0].split(",")[0].strip().lower()
                hit_head = variant.split(",")[0].strip().lower()
                if orig_head == hit_head or orig_head in variant.lower():
                    _cache_put(variants[0], result)
                log_.info(f"geocode hit via variant {variant!r} (for {variants[0]!r})")
            else:
                log_.info(f"geocode hit for {variant!r}")
            return float(result["lon"]), float(result["lat"])

    log_.warning(f"geocode: no results for {variants[0]!r} ({len(variants)} variants tried)")
    return None


def _pick_result(payload: list, purpose: str) -> dict | None:
    scored: list[tuple[int, dict]] = []
    for row in payload:
        try:
            lon = float(row["lon"])
            lat = float(row["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (41.5 <= lat <= 48.3 and -90.6 <= lon <= -82.0):
            continue
        result = {
            "lon": lon,
            "lat": lat,
            "osm_class": row.get("class") or "",
            "osm_type": row.get("type") or "",
        }
        if purpose == "name" and _is_admin_result(result):
            continue
        preferred = 0 if (result["osm_class"] or "").lower() in _NAME_PREFERRED_CLASS else 1
        if purpose == "locality":
            preferred = 0 if _is_admin_result(result) else 1
        scored.append((preferred, result))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def _nominatim_search(
    q: str, *, purpose: str = "name", logger: logging.Logger | None = None,
) -> dict | None:
    global _last_request, _circuit_open
    log_ = logger or _logger

    wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)

    params = {
        "format": "json",
        "limit": 5,
        "countrycodes": "us",
        "q": q,
        "viewbox": _MI_VIEWBOX,
        "bounded": 0,
    }
    url = NOMINATIM_SEARCH + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": config.APP_USER_AGENT,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=config.ENRICH_TIMEOUT) as resp:
            raw = resp.read()
            encoding = (resp.headers.get("Content-Encoding") or "").lower()
            if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
                import gzip
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
            payload = json.loads(raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        _last_request = time.monotonic()
        if exc.code == 429:
            _circuit_open = True
            log_.error(
                f"geocode HTTP 429 for {q!r}; opening circuit — "
                "skipping remaining Wikipedia leftover geocodes"
            )
            raise RateLimitExceeded("Nominatim geocode circuit open") from exc
        log_.warning(f"geocode HTTP {exc.code} for {q!r}: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001 - best-effort geocode
        _last_request = time.monotonic()
        log_.warning(f"geocode request failed for {q!r}: {exc}")
        return None
    finally:
        _last_request = time.monotonic()

    if not payload:
        log_.debug(f"geocode: empty Nominatim payload for {q!r}")
        _cache_put_miss(q)
        return None
    picked = _pick_result(payload, purpose)
    if picked is None and payload:
        try:
            lon = float(payload[0]["lon"])
            lat = float(payload[0]["lat"])
        except (KeyError, TypeError, ValueError) as exc:
            log_.warning(f"geocode: bad payload for {q!r}: {exc}")
            return None
        if not (41.5 <= lat <= 48.3 and -90.6 <= lon <= -82.0):
            log_.warning(f"geocode: result outside Michigan for {q!r} -> {lat},{lon}")
            return None
        if purpose == "name":
            log_.debug(f"geocode: admin/locality results rejected for {q!r} (purpose=name)")
            return None
        return {
            "lon": lon,
            "lat": lat,
            "osm_class": payload[0].get("class") or "",
            "osm_type": payload[0].get("type") or "",
        }
    return picked
