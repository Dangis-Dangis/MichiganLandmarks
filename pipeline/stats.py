"""Run-scoped counters for fallbacks, merges, and quality — not parsed from logs."""
from __future__ import annotations

import threading
from collections import Counter

_lock = threading.Lock()

source_fetch_failed: dict[str, str] = {}
source_returned_zero: list[str] = []
nps_via: str | None = None
enrich_skipped: str | None = None  # "flag" | "unreachable" | None
images_stripped: int = 0
museum_leftovers_uncovered: int = 0
museum_geocode_article: int = 0
museum_geocode_name: int = 0
museum_geocode_locality: int = 0
museum_geocode_unplaced: int = 0
museum_geocode_429_abort: int = 0
museum_coord_upgrades: int = 0
museum_coord_skips_name_mismatch: int = 0
merged_clusters: int = 0
museum_intra_merges: int = 0
counties_filled: int = 0
id_collisions: int = 0
location_quality: Counter[str] = Counter()
http_cache_hits: int = 0
http_cache_misses: int = 0
details_skipped_unchanged: int = 0


def reset() -> None:
    global nps_via, enrich_skipped, images_stripped
    global museum_leftovers_uncovered, museum_geocode_article, museum_geocode_name
    global museum_geocode_locality, museum_geocode_unplaced, museum_geocode_429_abort
    global museum_coord_upgrades, museum_coord_skips_name_mismatch
    global merged_clusters, museum_intra_merges, counties_filled
    global id_collisions
    global http_cache_hits, http_cache_misses, details_skipped_unchanged
    with _lock:
        source_fetch_failed.clear()
        source_returned_zero.clear()
        nps_via = None
        enrich_skipped = None
        images_stripped = 0
        museum_leftovers_uncovered = 0
        museum_geocode_article = 0
        museum_geocode_name = 0
        museum_geocode_locality = 0
        museum_geocode_unplaced = 0
        museum_geocode_429_abort = 0
        museum_coord_upgrades = 0
        museum_coord_skips_name_mismatch = 0
        merged_clusters = 0
        museum_intra_merges = 0
        counties_filled = 0
        id_collisions = 0
        location_quality.clear()
        http_cache_hits = 0
        http_cache_misses = 0
        details_skipped_unchanged = 0


def note_source_failed(name: str, exc: BaseException) -> None:
    with _lock:
        source_fetch_failed[name] = str(exc)


def note_source_zero(name: str) -> None:
    with _lock:
        if name not in source_returned_zero:
            source_returned_zero.append(name)


def set_nps_via(value: str) -> None:
    global nps_via
    with _lock:
        nps_via = value


def add_museum_intra_merges(n: int) -> None:
    global museum_intra_merges
    if n <= 0:
        return
    with _lock:
        museum_intra_merges += n


def inc_coord_skip() -> None:
    global museum_coord_skips_name_mismatch
    with _lock:
        museum_coord_skips_name_mismatch += 1


def inc_cache_hit() -> None:
    global http_cache_hits
    with _lock:
        http_cache_hits += 1


def inc_cache_miss() -> None:
    global http_cache_misses
    with _lock:
        http_cache_misses += 1


def add_details_skipped(n: int) -> None:
    global details_skipped_unchanged
    if n <= 0:
        return
    with _lock:
        details_skipped_unchanged += n


def snapshot() -> dict:
    with _lock:
        return {
            "source_fetch_failed": dict(source_fetch_failed),
            "source_returned_zero": list(source_returned_zero),
            "nps_via": nps_via,
            "enrich_skipped": enrich_skipped,
            "images_stripped": images_stripped,
            "museum_leftovers_uncovered": museum_leftovers_uncovered,
            "museum_geocode_article": museum_geocode_article,
            "museum_geocode_name": museum_geocode_name,
            "museum_geocode_locality": museum_geocode_locality,
            "museum_geocode_unplaced": museum_geocode_unplaced,
            "museum_geocode_429_abort": museum_geocode_429_abort,
            "museum_coord_upgrades": museum_coord_upgrades,
            "museum_coord_skips_name_mismatch": museum_coord_skips_name_mismatch,
            "merged_clusters": merged_clusters,
            "museum_intra_merges": museum_intra_merges,
            "counties_filled": counties_filled,
            "id_collisions": id_collisions,
            "location_quality": dict(location_quality),
            "http_cache_hits": http_cache_hits,
            "http_cache_misses": http_cache_misses,
            "details_skipped_unchanged": details_skipped_unchanged,
        }
