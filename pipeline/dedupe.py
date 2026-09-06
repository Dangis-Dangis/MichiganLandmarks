"""Merge-with-tags de-duplication.

A single physical place can appear across sources (e.g. a lighthouse that is also
an NRHP listing and has a roadside marker). We cluster records that are both very
close together AND name-similar, keep one primary (by category priority), tag it
with the other categories (`also_*`), and backfill any missing media/description.
"""
from __future__ import annotations

import math
import re

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


def _name_similar(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    if union and inter / union >= NAME_JACCARD_MIN:
        return True
    return ta <= tb or tb <= ta  # one is a subset of the other


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
                if a.category == b.category:
                    continue  # only merge cross-category physical duplicates
                if _haversine_m(a.latitude, a.longitude, b.latitude, b.longitude) > DISTANCE_THRESHOLD_M:
                    continue
                if _name_similar(a.name, b.name):
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
        members.sort(key=lambda i: CATEGORY_PRIORITY.get(landmarks[i].category, 99))
        primary = landmarks[members[0]]
        others = [landmarks[i] for i in members[1:]]
        _absorb(primary, others)
        merged.append(primary)
    return merged, merged_count


def _absorb(primary: Landmark, others: list[Landmark]) -> None:
    merged_from = []
    for o in others:
        primary.tags.append(f"also_{o.category}")
        merged_from.append({"id": o.id, "source": o.source, "category": o.category})
        if not primary.description and o.description:
            primary.description = o.description
        if not primary.image_url and o.image_url:
            primary.image_url = o.image_url
            primary.image_credit = o.image_credit
            primary.image_license = o.image_license
        if not primary.official_url and o.official_url:
            primary.official_url = o.official_url
        if not primary.year and o.year:
            primary.year = o.year
            primary.significant_date = o.significant_date
            primary.date_type = o.date_type
        # Carry the marker plaque text onto the surviving record.
        if o.category == "historical_marker" and o.attributes.get("marker_text"):
            primary.attributes.setdefault("marker_text", o.attributes["marker_text"])
    # De-duplicate tags while preserving order.
    seen = set()
    primary.tags = [t for t in primary.tags if not (t in seen or seen.add(t))]
    primary.attributes["merged_from"] = merged_from
