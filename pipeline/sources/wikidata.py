"""Wikidata SPARQL helpers (lighthouses + the no-key NPS fallback).

Resilient to the Wikidata Query Service (WDQS) being rate-limited/offline: tries
WDQS first, then falls back to the QLever Wikidata endpoint. Queries use explicit
PREFIX declarations and rdfs:label (not the WDQS-only `wikibase:label` service) so
they run identically on both endpoints.

Wikidata content is CC0. Images referenced via P18 live on Wikimedia Commons and
carry per-file licenses, resolved separately in enrich.commons_image_info().
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import config

_POINT_RE = re.compile(r"Point\(([-\d.]+)\s+([-\d.]+)\)", re.IGNORECASE)

PREFIXES = (
    "PREFIX wd: <http://www.wikidata.org/entity/>\n"
    "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX schema: <http://schema.org/>\n"
)

WDQS_ENDPOINT = config.WIKIDATA_SPARQL
QLEVER_ENDPOINT = "https://qlever.dev/api/wikidata"


# Short timeout on the primary so a rate-limited/stalled WDQS fails over quickly.
WDQS_TIMEOUT = 12


def _fetch(endpoint: str, query: str, timeout: float) -> dict:
    params = {"query": query}
    if endpoint == WDQS_ENDPOINT:
        params["format"] = "json"
    url = endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": "application/sparql-results+json",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
            import gzip
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
        return json.loads(raw.decode("utf-8", "replace"))


def run_sparql(query: str) -> list[dict]:
    full = PREFIXES + query
    errors: list[str] = []
    # 1) Wikidata Query Service (authoritative, freshest) - fail fast to the fallback.
    try:
        return _bindings(_fetch(WDQS_ENDPOINT, full, WDQS_TIMEOUT))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        errors.append(f"wdqs: {repr(exc)[:90]}")
    # 2) QLever fallback (used during WDQS outages / 429 rate-limiting).
    for attempt in range(2):
        try:
            return _bindings(_fetch(QLEVER_ENDPOINT, full, config.REQUEST_TIMEOUT))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            errors.append(f"qlever#{attempt}: {repr(exc)[:90]}")
            time.sleep(2)
    raise RuntimeError("SPARQL failed on all endpoints -> " + " | ".join(errors))


def _bindings(payload: dict) -> list[dict]:
    rows = []
    for binding in payload.get("results", {}).get("bindings", []):
        rows.append({k: v.get("value") for k, v in binding.items()})
    return rows


def parse_point(wkt: str | None) -> tuple[float, float] | None:
    """Return (lon, lat) from a 'Point(lon lat)' literal."""
    if not wkt:
        return None
    m = _POINT_RE.search(wkt)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def qid_from_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    return uri.rstrip("/").rsplit("/", 1)[-1]
