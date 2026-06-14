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
from pathlib import Path

from . import config
from .schema import Landmark

_OVERLAY_DESC_LIMIT = 600  # chars, keeps per-category My Maps CSV small


def safe_filename(landmark_id: str) -> str:
    return landmark_id.replace(":", "__")


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
        "county", "city", "address", "region", "water_body", "tags",
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
        (config.DETAILS_DIR / fname).write_text(
            json.dumps(lm.to_dict(), ensure_ascii=False), encoding="utf-8"
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
    if lm.date_type and lm.year:
        meta.append(f"{lm.date_type.title()}: {lm.year}")
    if lm.county:
        meta.append(f"County: {_xml_escape(lm.county)}")
    if meta:
        html_parts.append("<p>" + " &middot; ".join(meta) + "</p>")
    if lm.official_url:
        html_parts.append(f'<p><a href="{_xml_escape(lm.official_url)}">More information</a></p>')
    html = "".join(html_parts)
    return (
        "    <Placemark>\n"
        f"      <name>{_xml_escape(lm.name)}</name>\n"
        f"      <description><![CDATA[{html}]]></description>\n"
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
        folders.append(
            f"    <Folder>\n      <name>{cat} ({len(items)})</name>\n{marks}    </Folder>\n"
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
        kml_path.write_text(
            _kml_document(f"Michigan {cat}", f"    <Folder>\n{marks}    </Folder>\n"),
            encoding="utf-8",
        )
        paths.append(kml_path)

        csv_path = config.OVERLAY_DIR / f"{cat}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "name", "latitude", "longitude", "subtype", "year",
                "description", "image_url", "official_url", "county", "city",
            ])
            for lm in items:
                desc = lm.description or ""
                if len(desc) > _OVERLAY_DESC_LIMIT:
                    desc = desc[: _OVERLAY_DESC_LIMIT - 1].rstrip() + "\u2026"
                writer.writerow([
                    lm.name, lm.latitude, lm.longitude, lm.subtype or "", lm.year or "",
                    desc, lm.image_url or "", lm.official_url or "",
                    lm.county or "", lm.city or "",
                ])
        paths.append(csv_path)
    return paths
