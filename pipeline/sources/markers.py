"""Michigan historical markers (Michigan History Center / DNR public view).

Full front+back plaque text is preserved in `attributes.marker_text`; photos come
from the layer's feature attachments via the bulk queryAttachments operation.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import config
from ..schema import Landmark, make_id, year_from_date
from . import arcgis

SOURCE = "MI-DNR-Markers"


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _plaque_text(attrs: dict) -> str | None:
    parts = []
    for title, body in (
        (attrs.get("markertitlefront"), attrs.get("markerdescfront")),
        (attrs.get("markertitleback"), attrs.get("markerdescback")),
    ):
        title, body = _clean(title), _clean(body)
        if title and body:
            parts.append(f"{title}\n{body}")
        elif body:
            parts.append(body)
    return "\n\n".join(parts) or None


def fetch() -> list[Landmark]:
    now = datetime.now(timezone.utc).isoformat()
    features = arcgis.query_features(
        config.MARKERS_LAYER, where="markerlocationstate='MI'"
    )

    # Bulk-resolve one photo per marker.
    oid_by_feature = {}
    object_ids = []
    for f in features:
        oid = f.get("attributes", {}).get("OBJECTID")
        if oid is not None:
            object_ids.append(int(oid))
            oid_by_feature[int(oid)] = f
    photos = arcgis.first_attachment_urls(config.MARKERS_LAYER, object_ids)

    landmarks: list[Landmark] = []
    for f in features:
        a = f.get("attributes", {})
        oid = a.get("OBJECTID")
        coords = arcgis.point_lonlat(f)
        if coords is None:
            lon, lat = a.get("ESRIGNSS_LONGITUDE"), a.get("ESRIGNSS_LATITUDE")
            if lon is None or lat is None:
                continue
            coords = (float(lon), float(lat))
        lon, lat = coords

        name = _clean(a.get("markername")) or _clean(a.get("markernameother")) or "Unnamed marker"
        marker_text = _plaque_text(a)
        erected = a.get("erecteddate") or a.get("significantdate")
        raw_county = _clean(a.get("markercounty"))
        # markercounty holds a Michigan county code (1-83), not a name.
        county = config.county_from_code(raw_county) or (raw_county.title() if raw_county else None)
        src_id = _clean(a.get("historicalmarkerid")) or _clean(a.get("markerid")) or str(oid)

        tags = [t for t in (
            _clean(a.get("tag1")), _clean(a.get("tag2")),
            _clean(a.get("tag3")), _clean(a.get("tag4")),
        ) if t]

        landmarks.append(Landmark(
            id=make_id("historical_marker", SOURCE, src_id),
            name=name,
            category="historical_marker",
            subtype=_clean(a.get("markertype")),
            latitude=lat,
            longitude=lon,
            description=marker_text,
            official_url=_clean(a.get("websitelink")),
            significant_date=str(erected) if erected else None,
            date_type="erected" if erected else None,
            year=year_from_date(erected),
            image_url=photos.get(int(oid)) if oid is not None else None,
            image_credit="Michigan History Center" if (oid is not None and int(oid) in photos) else None,
            image_license="Michigan DNR Open Data" if (oid is not None and int(oid) in photos) else None,
            source=SOURCE,
            source_id=src_id,
            source_url=config.MARKERS_LAYER + f"/query?where=OBJECTID={oid}",
            data_license=config.DATA_LICENSE[SOURCE],
            last_fetched=now,
            county=county,
            city=(_clean(a.get("markerlocationcity")) or "").title() or None,
            address=_clean(a.get("markerlocationaddress")),
            region=config.region_for_county(county),
            tags=tags,
            attributes={
                "marker_number": _clean(a.get("markerid")),
                "marker_text": marker_text,
                "erected_year": year_from_date(a.get("erecteddate")),
                "national_registry_year": a.get("nationalregistrydate") or None,
                "registry_listing_year": a.get("registrylistingyear") or None,
            },
        ))
    return landmarks
