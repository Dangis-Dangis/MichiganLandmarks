"""The unified landmark schema shared by every source and every output.

Mirrors the schema agreed in the plan: Core, Media, Provenance, Location detail,
and Category-specific attributes. A single dataclass keeps every record honest
about which fields are present (None means "unknown", never a placeholder value).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    value = (value or "").lower().strip()
    value = _SLUG_RE.sub("-", value).strip("-")
    return value or "x"


@dataclass
class Landmark:
    # --- Core (every record) ---
    id: str
    name: str
    category: str
    latitude: float
    longitude: float
    subtype: str | None = None
    description: str | None = None
    official_url: str | None = None
    significant_date: str | None = None  # ISO-ish string ("1858", "1979-06-04")
    date_type: str | None = None  # built | erected | listed | established | designated
    year: int | None = None

    # --- Media ---
    image_url: str | None = None
    image_credit: str | None = None
    image_license: str | None = None

    # --- Provenance ---
    source: str = ""
    source_id: str = ""
    source_url: str | None = None
    data_license: str | None = None
    last_fetched: str | None = None

    # --- Location detail ---
    county: str | None = None
    city: str | None = None
    address: str | None = None
    region: str | None = None  # tourism-style region (e.g. Western UP, Southeast)
    water_body: str | None = None
    tags: list[str] = field(default_factory=list)

    # --- Category-specific (and any enrichment provenance) ---
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def index_record(self) -> dict[str, Any]:
        """Lightweight record for landmarks.index.json (map + list view)."""
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "subtype": self.subtype,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "year": self.year,
            "county": self.county,
            "region": self.region,
            "image_url": self.image_url,
            "summary": _truncate(self.description, 160),
            "tags": self.tags,
            "has_details": True,
        }


def _truncate(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


def make_id(category: str, source: str, source_id: str) -> str:
    return f"{category}:{slugify(source)}:{slugify(str(source_id))}"


def year_from_date(value: Any) -> int | None:
    """Extract a 4-digit year from an int, ISO date, or free-form string."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 2100 else None
    m = re.search(r"(1[6-9]\d{2}|20\d{2})", str(value))
    return int(m.group(1)) if m else None
