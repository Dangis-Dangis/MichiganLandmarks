"""Serializers for every output artifact.

Produces, under data/:
  - landmarks.geojson          full dataset, one Feature per record
  - landmarks.csv              full dataset, flattened
  - landmarks.kml              full dataset, foldered by category (export)
  - landmarks.index.json       lightweight index for map + list (loaded up front)
  - details/<id>.json          full per-record detail (fetched on tap)
  - overlay/<category>.kml     per-category KML export
  - overlay/<category>.csv     per-category CSV export
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from . import config, urls
from .schema import Landmark

_OVERLAY_DESC_LIMIT = 600  # chars, keeps per-category My Maps CSV small


def safe_filename(landmark_id: str) -> str:
    return landmark_id.replace(":", "__")


def _write_text(path: Path, text: str) -> None:
    """Write UTF-8 text, retrying on transient Windows file-lock errors."""
    last: OSError | None = None
    data = text.encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    for attempt in range(8):
        try:
            with tmp.open("wb") as fh:
                fh.write(data)
            tmp.replace(path)
            return
        except OSError as exc:
            last = exc
            time.sleep(0.1 * (2 ** attempt))
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
    assert last is not None
    raise last


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def ensure_dirs() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    config.OVERLAY_DIR.mkdir(parents=True, exist_ok=True)


def write_geojson(landmarks: list[Landmark]) -> Path:
    features = []
    for lm in landmarks:
        d = lm.to_dict()
        lat, lon = d.pop("latitude"), d.pop("longitude")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": d,
        })
    fc = {"type": "FeatureCollection", "features": features}
    path = config.DATA_DIR / "landmarks.geojson"
    path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return path


def write_csv(landmarks: list[Landmark]) -> Path:
    cols = [
        "id", "name", "category", "subtype", "latitude", "longitude",
        "description", "official_url", "significant_date", "date_type", "year",
        "image_url", "image_credit", "image_license",
        "source", "source_id", "source_url", "data_license", "last_fetched",
        "county", "city", "address", "water_body", "location_quality", "tags",
    ]
    path = config.DATA_DIR / "landmarks.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for lm in landmarks:
            row = lm.to_dict()
            row["tags"] = ";".join(lm.tags)
            writer.writerow(row)
    return path


def write_app_data(landmarks: list[Landmark]) -> tuple[Path, int]:
    """Write landmarks.index.json + details/<id>.json. Returns (index_path, details_count)."""
    index = []
    written = 0
    current_files: set[str] = set()
    for lm in landmarks:
        rec = lm.index_record()
        rec["detail_file"] = f"details/{safe_filename(lm.id)}.json"
        index.append(rec)
        fname = f"{safe_filename(lm.id)}.json"
        current_files.add(fname)
        _write_text(
            config.DETAILS_DIR / fname,
            json.dumps(lm.to_dict(), ensure_ascii=False),
        )
        written += 1
    # Drop stale detail files left over from a previous (larger) build so the
    # details dir always mirrors the current dataset exactly.
    for existing in config.DETAILS_DIR.glob("*.json"):
        if existing.name not in current_files:
            existing.unlink()
    index_path = config.DATA_DIR / "landmarks.index.json"
    index_path.write_text(
        json.dumps({"count": len(index), "landmarks": index}, ensure_ascii=False),
        encoding="utf-8",
    )
    return index_path, written


def _date_reported(lm: Landmark) -> str | None:
    """Best date to show as 'Date reported' on a KML balloon.

    Prefer the source's significant_date (ISO-ish), then the extracted year.
    """
    raw = (lm.significant_date or "").strip()
    if raw:
        if "T" in raw:
            raw = raw.split("T", 1)[0]
        return raw
    if lm.year:
        return str(lm.year)
    return None


def _placemark(lm: Landmark, trim_desc: int | None = None) -> str:
    desc = lm.description or ""
    if trim_desc and len(desc) > trim_desc:
        desc = desc[: trim_desc - 1].rstrip() + "\u2026"
    html_parts = []
    if lm.image_url:
        html_parts.append(f'<img src="{_xml_escape(lm.image_url)}" width="320"/><br/>')
    if desc:
        html_parts.append(f"<p>{_xml_escape(desc)}</p>")
    meta = []
    if lm.county:
        meta.append(f"County: {_xml_escape(lm.county)}")
    if lm.city:
        meta.append(f"City: {_xml_escape(lm.city)}")
    addr = urls.display_address(lm.address, lm.city)
    if addr:
        meta.append(f"Address: {_xml_escape(addr)}")
    if meta:
        html_parts.append("<p>" + " &middot; ".join(meta) + "</p>")
    official = urls.as_official(lm.official_url)
    if official:
        html_parts.append(f'<p><a href="{_xml_escape(official)}">Website</a></p>')
    wiki = (lm.attributes or {}).get("wikipedia_url")
    if wiki:
        html_parts.append(f'<p><a href="{_xml_escape(str(wiki))}">Wikipedia</a></p>')
    nara = (lm.attributes or {}).get("nara_url")
    if nara:
        html_parts.append(f'<p><a href="{_xml_escape(str(nara))}">Nomination (NARA)</a></p>')
    if lm.source_url:
        html_parts.append(f'<p><a href="{_xml_escape(lm.source_url)}">Source data</a></p>')
    html_parts.append(
        f'<p><a href="{_xml_escape(urls.maps_search_url(lm))}">Google Maps</a></p>'
    )
    html_parts.append(
        f'<p><a href="{_xml_escape(urls.maps_directions_url(lm.latitude, lm.longitude))}">Directions</a></p>'
    )
    reported = _date_reported(lm)
    if reported:
        html_parts.append(f"<p>Date reported: {_xml_escape(reported)}</p>")
    html = "".join(html_parts)
    ext = []
    cat_label = config.CATEGORY_LABELS.get(lm.category, lm.category)
    ext.append(f'        <Data name="category"><value>{_xml_escape(cat_label)}</value></Data>\n')
    if reported:
        ext.append(
            f'        <Data name="date_reported"><value>{_xml_escape(reported)}</value></Data>\n'
        )
    if lm.county:
        ext.append(
            f'        <Data name="county"><value>{_xml_escape(lm.county)}</value></Data>\n'
        )
    return (
        "    <Placemark>\n"
        f"      <name>{_xml_escape(lm.name)}</name>\n"
        f"      <description><![CDATA[{html}]]></description>\n"
        f"      <ExtendedData>\n{''.join(ext)}      </ExtendedData>\n"
        f'      <styleUrl>#{lm.category}</styleUrl>\n'
        f"      <Point><coordinates>{lm.longitude},{lm.latitude},0</coordinates></Point>\n"
        "    </Placemark>\n"
    )


def _kml_document(title: str, body: str) -> str:
    styles = "".join(
        f'  <Style id="{cat}"><IconStyle><Icon>'
        f"<href>https://maps.google.com/mapfiles/kml/shapes/{_kml_icon(cat)}.png</href>"
        "</Icon></IconStyle></Style>\n"
        for cat in config.CATEGORIES
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "  <Document>\n"
        f"    <name>{_xml_escape(title)}</name>\n"
        f"{styles}"
        f"{body}"
        "  </Document>\n"
        "</kml>\n"
    )


def _kml_icon(category: str) -> str:
    return {
        "lighthouse": "marina",
        "historical_marker": "info-i",
        "nrhp_site": "library_maps",
        "state_park": "parks",
        "national_park_unit": "mountains",
        "museum": "museum_historical",
    }.get(category, "placemark_circle")


def write_kml(landmarks: list[Landmark]) -> Path:
    by_cat: dict[str, list[Landmark]] = {c: [] for c in config.CATEGORIES}
    for lm in landmarks:
        by_cat.setdefault(lm.category, []).append(lm)
    folders = []
    for cat in config.CATEGORIES:
        items = by_cat.get(cat, [])
        if not items:
            continue
        marks = "".join(_placemark(lm) for lm in items)
        label = config.CATEGORY_LABELS.get(cat, cat)
        folders.append(
            f"    <Folder>\n      <name>{_xml_escape(label)} ({len(items)})</name>\n{marks}    </Folder>\n"
        )
    path = config.DATA_DIR / "landmarks.kml"
    path.write_text(_kml_document("Michigan Landmarks", "".join(folders)), encoding="utf-8")
    return path


def write_overlays(landmarks: list[Landmark]) -> list[Path]:
    by_cat: dict[str, list[Landmark]] = {}
    for lm in landmarks:
        by_cat.setdefault(lm.category, []).append(lm)
    paths = []
    for cat, items in by_cat.items():
        marks = "".join(_placemark(lm, trim_desc=_OVERLAY_DESC_LIMIT) for lm in items)
        kml_path = config.OVERLAY_DIR / f"{cat}.kml"
        label = config.CATEGORY_LABELS.get(cat, cat)
        kml_path.write_text(
            _kml_document(
                f"Michigan {label}",
                f"    <Folder>\n      <name>{_xml_escape(label)} ({len(items)})</name>\n{marks}    </Folder>\n",
            ),
            encoding="utf-8",
        )
        paths.append(kml_path)

        csv_path = config.OVERLAY_DIR / f"{cat}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "name", "latitude", "longitude", "subtype", "year", "date_reported",
                "description", "image_url", "official_url", "county", "city",
            ])
            for lm in items:
                desc = lm.description or ""
                if len(desc) > _OVERLAY_DESC_LIMIT:
                    desc = desc[: _OVERLAY_DESC_LIMIT - 1].rstrip() + "\u2026"
                writer.writerow([
                    lm.name, lm.latitude, lm.longitude, lm.subtype or "", lm.year or "",
                    _date_reported(lm) or "",
                    desc, lm.image_url or "", lm.official_url or "",
                    lm.county or "", lm.city or "",
                ])
        paths.append(csv_path)
    return paths
