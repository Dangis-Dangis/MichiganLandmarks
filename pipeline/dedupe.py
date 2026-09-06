"""Merge-with-tags de-duplication.

A single physical place can appear across sources (e.g. a lighthouse that is also
an NRHP listing and has a roadside marker). We cluster records that are both very
close together AND name-similar, keep one primary (by category priority), tag it
with the other categories (`also_*`), and backfill any missing media/description.

Same-category pairs are merged only when they are strict duplicates: punctuation
variants, NRHP "(Boundary Increase)" rows, or a lighthouse group listing sitting
on top of one of its member lights (e.g. Inner and Outer Lights vs Outer Light).
Adjacent but distinct places (school vs church, inner vs outer pierheads) stay
separate.
"""
from __future__ import annotations

import math
import re

from . import facts, log, urls
from .schema import Landmark

# Lower index = higher priority to become the surviving primary record.
CATEGORY_PRIORITY = {
    "lighthouse": 0,
    "national_park_unit": 1,
    "state_park": 2,
    "museum": 3,
    "nrhp_site": 4,
    "historical_marker": 5,
}

DISTANCE_THRESHOLD_M = 80.0
NAME_JACCARD_MIN = 0.5

_STOPWORDS = {
    "the", "of", "and", "a", "lighthouse", "light", "station", "historic",
    "district", "state", "park", "recreation", "area", "national", "site",
    "monument", "memorial", "house", "building", "museum",
}
_NORM_RE = re.compile(r"[^a-z0-9\s]")
_BOUNDARY_RE = re.compile(r"\s*\(?\s*boundary increase\s*\)?\s*$", re.I)
_DIRECTIONAL = frozenset({
    "inner", "outer", "front", "rear", "north", "south", "east", "west",
    "upper", "lower",
})
_DIR_PAIRS = (
    ("inner", "outer"),
    ("front", "rear"),
    ("north", "south"),
    ("east", "west"),
    ("upper", "lower"),
)
_logger = log.get_logger(__name__)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _tokens(name: str) -> set[str]:
    name = _NORM_RE.sub(" ", (name or "").lower())
    return {t for t in name.split() if t and t not in _STOPWORDS}


def _name_score(a: str, b: str) -> tuple[bool, float, str]:
    """Return (similar, jaccard, reason) where reason is jaccard, subset, empty, or none."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False, 0.0, "empty"
    inter = len(ta & tb)
    union = len(ta | tb)
    jaccard = inter / union if union else 0.0
    if jaccard >= NAME_JACCARD_MIN:
        return True, jaccard, "jaccard"
    if ta <= tb or tb <= ta:
        return True, jaccard, "subset"
    return False, jaccard, "none"


def _name_similar(a: str, b: str) -> bool:
    return _name_score(a, b)[0]


def _normalized_name(name: str) -> str:
    s = (name or "").lower().replace("&", " and ").replace("/", " ")
    s = _NORM_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _base_name(name: str) -> str:
    return _BOUNDARY_RE.sub("", _normalized_name(name)).strip()


def _group_member_names(a: str, b: str) -> bool:
    """True when one name is a paired listing (inner and outer) covering the other."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    if len(ta & tb) < 3:
        return False
    if not _name_score(a, b)[0]:
        return False
    da, db = ta & _DIRECTIONAL, tb & _DIRECTIONAL
    for x, y in _DIR_PAIRS:
        pair = {x, y}
        if pair <= da and db and db <= pair:
            return True
        if pair <= db and da and da <= pair:
            return True
    return False


def _same_category_duplicate(a: Landmark, b: Landmark) -> bool:
    """Strict same-category duplicate (not merely nearby similar places)."""
    if _normalized_name(a.name) == _normalized_name(b.name):
        return True
    if _base_name(a.name) and _base_name(a.name) == _base_name(b.name):
        return True
    if a.category == "lighthouse" and _group_member_names(a.name, b.name):
        return True
    return False


def _survivor_key(lm: Landmark) -> tuple:
    attrs = lm.attributes or {}
    return (
        CATEGORY_PRIORITY.get(lm.category, 99),
        0 if attrs.get("wikipedia_url") else 1,
        0 if lm.image_url else 1,
        -len(lm.description or ""),
        -len(lm.name or ""),
    )


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _grid_key(lat: float, lon: float) -> tuple[int, int]:
    # ~0.001 deg latitude ~= 111 m; cell comfortably larger than the threshold.
    return (round(lat / 0.001), round(lon / 0.001))


def merge(landmarks: list[Landmark]) -> tuple[list[Landmark], int]:
    """Return (merged_landmarks, clusters_merged_count)."""
    n = len(landmarks)
    uf = _UnionFind(n)

    # Bucket records into a coarse grid, compare only within neighboring cells.
    grid: dict[tuple[int, int], list[int]] = {}
    for i, lm in enumerate(landmarks):
        grid.setdefault(_grid_key(lm.latitude, lm.longitude), []).append(i)

    for (gx, gy), idxs in grid.items():
        neighbors: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbors.extend(grid.get((gx + dx, gy + dy), []))
        for i in idxs:
            a = landmarks[i]
            for j in neighbors:
                if j <= i:
                    continue
                b = landmarks[j]
                if _haversine_m(a.latitude, a.longitude, b.latitude, b.longitude) > DISTANCE_THRESHOLD_M:
                    continue
                if a.category == b.category:
                    if not _same_category_duplicate(a, b):
                        continue
                elif not _name_score(a.name, b.name)[0]:
                    continue
                uf.union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    merged: list[Landmark] = []
    merged_count = 0
    for members in clusters.values():
        if len(members) == 1:
            merged.append(landmarks[members[0]])
            continue
        merged_count += 1
        members.sort(key=lambda i: _survivor_key(landmarks[i]))
        primary = landmarks[members[0]]
        others = [landmarks[i] for i in members[1:]]
        _absorb(primary, others)
        merged.append(primary)
    return merged, merged_count


def _absorb(primary: Landmark, others: list[Landmark]) -> None:
    merged_from = []
    for o in others:
        if o.category != primary.category:
            absorbed = [f"also_{o.category}"]
            primary.tags.append(f"also_{o.category}")
        else:
            absorbed = ["same_category"]
        merged_from.append(facts.source_snapshot(o))
        if not primary.description and o.description:
            primary.description = o.description
            absorbed.append("description")
        if not primary.image_url and o.image_url:
            primary.image_url = o.image_url
            primary.image_credit = o.image_credit
            primary.image_license = o.image_license
            absorbed.append("image")
        prev_url = primary.official_url
        primary.official_url = urls.prefer_official(primary.official_url, o.official_url)
        if primary.official_url and primary.official_url != prev_url:
            absorbed.append("official_url")
        if not primary.address and o.address:
            primary.address = o.address
            absorbed.append("address")
        if not primary.city and o.city:
            primary.city = o.city
            absorbed.append("city")
        if not primary.attributes.get("nara_url") and o.attributes.get("nara_url"):
            primary.attributes["nara_url"] = o.attributes["nara_url"]
            absorbed.append("nara_url")
        if not primary.attributes.get("wikipedia_url") and o.attributes.get("wikipedia_url"):
            primary.attributes["wikipedia_url"] = o.attributes["wikipedia_url"]
            absorbed.append("wikipedia_url")
        if not primary.attributes.get("uscg_id") and o.attributes.get("uscg_id"):
            primary.attributes["uscg_id"] = o.attributes["uscg_id"]
            absorbed.append("uscg_id")
        if not primary.attributes.get("focal_height_ft") and o.attributes.get("focal_height_ft"):
            primary.attributes["focal_height_ft"] = o.attributes["focal_height_ft"]
            absorbed.append("focal_height_ft")
        facts.merge_facts(primary, o)
        # Carry the marker plaque text onto the surviving record.
        if o.category == "historical_marker" and o.attributes.get("marker_text"):
            if "marker_text" not in primary.attributes:
                primary.attributes["marker_text"] = o.attributes["marker_text"]
                absorbed.append("marker_text")
        dist = _haversine_m(primary.latitude, primary.longitude, o.latitude, o.longitude)
        _ok, jaccard, reason = _name_score(primary.name, o.name)
        _logger.debug(log.fmt(
            "dedupe",
            f"merge {primary.name!r} ({primary.category}) <- {o.name!r} ({o.category}) "
            f"d={dist:.0f}m j={jaccard:.2f} ({reason}) absorbed={','.join(absorbed)}",
        ))
    # De-duplicate tags while preserving order.
    seen = set()
    primary.tags = [t for t in primary.tags if not (t in seen or seen.add(t))]
    primary.attributes["merged_from"] = merged_from
