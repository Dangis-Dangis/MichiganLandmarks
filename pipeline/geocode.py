"""Rate-limited forward geocoding for build-time gaps (museum Wikipedia leftovers).

Uses OpenStreetMap Nominatim with an identifying user-agent. Opt-in only
(``MUSEUM_GEOCODE=1``). On HTTP 429 the circuit opens immediately so a build
does not sit in a retry storm — Wikidata + IMLS coverage is enough to finish.

Nominatim usage policy (https://operations.osmfoundation.org/policies/nominatim/):
≤1 req/s, single thread, cache results, identifying User-Agent. One-time small
bulk only — do not enable on every routine rebuild.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, log

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
# Nominatim viewbox: left(lon), top(lat), right(lon), bottom(lat)
_MI_VIEWBOX = "-90.5,48.3,-82.0,41.5"
_MIN_INTERVAL = 2.0  # stay under 1 req/s
_last_request = 0.0
_circuit_open = False
_CACHE_DIR = config.CACHE_DIR / "nominatim"


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


def _cache_get(query: str) -> tuple[float, float] | None | object:
    """Return coords, or a sentinel meaning 'not cached'.

    Misses are not cached permanently — Wikipedia titles often need softer
    query variants, and a hard miss would block those forever.
    """
    path = _cache_path(query)
    if not path.is_file():
        return _UNCACHED
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _UNCACHED
    if data.get("miss"):
        return _UNCACHED
    try:
        return float(data["lon"]), float(data["lat"])
    except (KeyError, TypeError, ValueError):
        return _UNCACHED


def _cache_put(query: str, coords: tuple[float, float]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    lon, lat = coords
    path = _cache_path(query)
    payload = {"query": query, "lon": lon, "lat": lat, "miss": False}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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

    add(q)
    add(_normalize_ampersand(q))
    for lit in _light_variants(q):
        add(lit)
        add(_normalize_ampersand(lit))

    # "Name, City, Michigan" → "Name, Michigan"
    parts = [p.strip() for p in q.split(",") if p.strip()]
    if len(parts) >= 3 and parts[-1].lower() == "michigan":
        short = f"{parts[0]}, Michigan"
        add(short)
        add(_normalize_ampersand(short))
        for lit in _light_variants(short):
            add(lit)
            add(_normalize_ampersand(lit))

    return variants


def geocode_michigan(query: str) -> tuple[float, float] | None:
    """Return (lon, lat) for a place query constrained to Michigan, or None.

    Tries several query variants (ampersand normalization, Light→Lighthouse,
    drop middle place token). Raises RateLimitExceeded on the first HTTP 429.
    """
    global _circuit_open
    if _circuit_open:
        raise RateLimitExceeded("Nominatim geocode circuit open")

    variants = query_variants(query)
    if not variants:
        return None

    for variant in variants:
        cached = _cache_get(variant)
        if cached is not _UNCACHED:
            if variant != variants[0]:
                log.info(f"geocode cache hit via variant {variant!r} (for {variants[0]!r})")
            return cached  # type: ignore[return-value]

        coords = _nominatim_search(variant)
        if coords is not None:
            _cache_put(variant, coords)
            # Also remember under the original query so reruns skip variants.
            if variant != variants[0]:
                _cache_put(variants[0], coords)
                log.info(f"geocode hit via variant {variant!r} (for {variants[0]!r})")
            else:
                log.info(f"geocode hit for {variant!r}")
            return coords

    log.warn(f"geocode: no results for {variants[0]!r} ({len(variants)} variants tried)")
    return None


def _nominatim_search(q: str) -> tuple[float, float] | None:
    global _last_request, _circuit_open

    wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)

    params = {
        "format": "json",
        "limit": 1,
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
            log.error(
                f"geocode HTTP 429 for {q!r}; opening circuit — "
                "skipping remaining Wikipedia leftover geocodes"
            )
            raise RateLimitExceeded("Nominatim geocode circuit open") from exc
        log.warn(f"geocode HTTP {exc.code} for {q!r}: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001 - best-effort geocode
        _last_request = time.monotonic()
        log.warn(f"geocode request failed for {q!r}: {exc}")
        return None
    finally:
        _last_request = time.monotonic()

    if not payload:
        return None
    try:
        lon = float(payload[0]["lon"])
        lat = float(payload[0]["lat"])
    except (KeyError, TypeError, ValueError) as exc:
        log.warn(f"geocode: bad payload for {q!r}: {exc}")
        return None
    if not (41.5 <= lat <= 48.3 and -90.6 <= lon <= -82.0):
        log.warn(f"geocode: result outside Michigan for {q!r} -> {lat},{lon}")
        return None
    return lon, lat
