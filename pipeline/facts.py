"""Dated events, heritage recognitions, and multi-source attribution.

None means unknown. Helpers never invent a date, award, or source URL.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from . import config
from .schema import Landmark, year_from_date

DATE_TYPE_LABELS = {
    "built": "Built",
    "erected": "Erected",
    "listed": "Listed",
    "established": "Established",
    "designated": "Designated",
}

# Prefer built as the index/sort year when a place has several dated events.
DATE_TYPE_PRIORITY = {
    "built": 0,
    "established": 1,
    "erected": 2,
    "listed": 3,
    "designated": 4,
}

_RECOGNITION_CANON = {
    "national register of historic places": "National Register of Historic Places",
    "listed in the national register of historic places": "National Register of Historic Places",
    "part of the national register of historic places": "National Register of Historic Places",
    "nrhp": "National Register of Historic Places",
    "national historic landmark": "National Historic Landmark",
    "michigan state historic site": "Michigan State Historic Site",
    "michigan historic site": "Michigan State Historic Site",
}

QID_RE = re.compile(r"^Q\d+$", re.IGNORECASE)


def iso_date(value: Any) -> str | None:
    """Normalize a date-ish value to YYYY-MM-DD or YYYY. None if unknown."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        if value > 10**11:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if 1000 <= value <= 2100:
            return str(value)
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        ms = int(text)
        if ms > 10**11:
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if 1000 <= ms <= 2100:
            return str(ms)
    except ValueError:
        pass
    if "T" in text:
        text = text.split("T", 1)[0]
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    m = re.search(r"(1[6-9]\d{2}|20\d{2})", text)
    return m.group(1) if m else None


def date_label(date_type: str, custom: str | None = None) -> str:
    if custom:
        return custom
    return DATE_TYPE_LABELS.get(date_type, date_type.replace("_", " ").title())


def record_date(lm: Landmark, date_type: str, value: Any, *, label: str | None = None) -> bool:
    """Append a dated event if the value parses. Returns True when added or merged."""
    parsed = iso_date(value)
    if not parsed or date_type not in DATE_TYPE_LABELS:
        return False
    entry = {
        "type": date_type,
        "date": parsed,
        "label": date_label(date_type, label),
    }
    dates = list(lm.attributes.get("dates") or [])
    year = year_from_date(parsed)
    for i, existing in enumerate(dates):
        if existing.get("type") != date_type:
            continue
        if year_from_date(existing.get("date")) != year:
            continue
        # Same type+year: keep the more specific calendar date.
        if len(parsed) > len(str(existing.get("date") or "")):
            dates[i] = entry
            lm.attributes["dates"] = dates
            return True
        return False
    dates.append(entry)
    lm.attributes["dates"] = dates
    return True


def canonical_recognition(name: str | None) -> str | None:
    if not name:
        return None
    raw = " ".join(name.split())
    if not raw:
        return None
    key = raw.lower()
    if key in _RECOGNITION_CANON:
        return _RECOGNITION_CANON[key]
    if "national historic landmark" in key:
        return "National Historic Landmark"
    if "national register of historic places" in key:
        return "National Register of Historic Places"
    if "michigan state historic site" in key or "michigan historic site" in key:
        return "Michigan State Historic Site"
    return raw


def add_recognition(lm: Landmark, name: str | None, date_value: Any, source: str) -> bool:
    """Append a named recognition. Same canonical name keeps the dated copy."""
    canon = canonical_recognition(name)
    if not canon:
        return False
    parsed = iso_date(date_value)
    recs = list(lm.attributes.get("recognitions") or [])
    key = canon.lower()
    for i, existing in enumerate(recs):
        if str(existing.get("name") or "").lower() != key:
            continue
        if parsed and not existing.get("date"):
            recs[i] = {"name": canon, "date": parsed, "source": source or existing.get("source")}
            lm.attributes["recognitions"] = recs
            return True
        if parsed and existing.get("date") and len(parsed) > len(str(existing.get("date"))):
            recs[i] = {"name": canon, "date": parsed, "source": source or existing.get("source")}
            lm.attributes["recognitions"] = recs
            return True
        return False
    recs.append({"name": canon, "date": parsed, "source": source or None})
    lm.attributes["recognitions"] = recs
    return True


def apply_primary_date(lm: Landmark) -> None:
    """Set year / date_type / significant_date from the preferred dated event."""
    dates = lm.attributes.get("dates") or []
    if not dates:
        return
    best = min(
        dates,
        key=lambda d: DATE_TYPE_PRIORITY.get(d.get("type") or "", 99),
    )
    lm.date_type = best.get("type")
    lm.significant_date = best.get("date")
    lm.year = year_from_date(best.get("date"))


def seed_date_from_core(lm: Landmark) -> None:
    """If a source set core date fields but no dates list, copy them once."""
    if lm.attributes.get("dates"):
        return
    if lm.date_type and (lm.significant_date or lm.year):
        record_date(lm, lm.date_type, lm.significant_date or lm.year)


def source_snapshot(lm: Landmark) -> dict[str, Any]:
    return {
        "id": lm.id,
        "source": lm.source,
        "category": lm.category,
        "source_url": lm.source_url,
        "data_license": lm.data_license,
    }


def _add_source_row(rows: list[dict], seen: set[str], name: str | None, url: str | None, license_: str | None) -> None:
    if not name:
        return
    key = name.strip().lower()
    if not key or key in seen:
        return
    seen.add(key)
    rows.append({
        "name": name.strip(),
        "url": url or None,
        "license": license_ or None,
    })


def collect_sources(lm: Landmark) -> list[dict[str, Any]]:
    """Deduped contributing datasets, primary first."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    _add_source_row(rows, seen, lm.source, lm.source_url, lm.data_license)
    for extra in lm.attributes.get("merged_from") or []:
        if not isinstance(extra, dict):
            continue
        _add_source_row(
            rows, seen,
            extra.get("source"),
            extra.get("source_url"),
            extra.get("data_license"),
        )
    qid = lm.attributes.get("wikidata_qid")
    wiki = lm.attributes.get("wikipedia_url")
    for name in lm.attributes.get("museum_sources") or []:
        if name == "Wikidata" and qid and QID_RE.match(str(qid)):
            _add_source_row(
                rows, seen, "Wikidata",
                f"https://www.wikidata.org/wiki/{qid}",
                config.DATA_LICENSE.get("Wikidata"),
            )
        elif name == "IMLS":
            _add_source_row(
                rows, seen, "IMLS",
                config.IMLS_DATASET_PAGE,
                config.DATA_LICENSE.get("IMLS"),
            )
        elif name == "Wikipedia":
            _add_source_row(
                rows, seen, "Wikipedia",
                wiki,
                config.DATA_LICENSE.get("Wikipedia"),
            )
        else:
            _add_source_row(rows, seen, name, None, config.DATA_LICENSE.get(name))
    return rows


def merge_facts(primary: Landmark, other: Landmark) -> None:
    """Union dates and recognitions from an absorbed record."""
    for entry in other.attributes.get("dates") or []:
        record_date(primary, entry.get("type") or "", entry.get("date"), label=entry.get("label"))
    for rec in other.attributes.get("recognitions") or []:
        add_recognition(primary, rec.get("name"), rec.get("date"), rec.get("source") or other.source)
    if not primary.attributes.get("wikidata_qid") and other.attributes.get("wikidata_qid"):
        primary.attributes["wikidata_qid"] = other.attributes["wikidata_qid"]


def finalize(lm: Landmark) -> None:
    seed_date_from_core(lm)
    apply_primary_date(lm)
    sources = collect_sources(lm)
    if sources:
        lm.attributes["sources"] = sources
    elif "sources" in lm.attributes:
        del lm.attributes["sources"]
