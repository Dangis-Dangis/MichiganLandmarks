"""Michigan historical markers (Michigan History Center / DNR public view).

Full front+back plaque text is preserved in `attributes.marker_text`.
`description` is the English face so list and search text stay in English.
Photos come from the layer's feature attachments via queryAttachments.

Coordinates prefer field GNSS (``ESRIGNSS_*``) when the crew found the sign, so
the pin is the green marker rather than an address-geocoded parcel centroid.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from .. import config, facts, log, urls
from ..plaque import english_plaque_text
from ..schema import Landmark, make_id, year_from_date
from . import arcgis

SOURCE = "MI-DNR-Markers"
_logger = log.get_logger(__name__)

# GNSS statuses that mean the field crew did not pin the sign itself.
_GNSS_UNRELIABLE = frozenset({"unable to find", "bad location"})
_MI_LAT = (41.5, 48.3)
_MI_LON = (-90.6, -82.0)


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pair(lon, lat) -> tuple[float, float] | None:
    try:
        lon_f, lat_f = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if not (_MI_LAT[0] <= lat_f <= _MI_LAT[1] and _MI_LON[0] <= lon_f <= _MI_LON[1]):
        return None
    return lon_f, lat_f


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _sign_coords(feature: dict) -> tuple[float, float] | None:
    """Prefer field GNSS of the green sign; fall back to layer geometry."""
    attrs = feature.get("attributes") or {}
    status = (attrs.get("fieldlocationstatus") or "").strip().lower()
    gnss_ok = status not in _GNSS_UNRELIABLE
    gnss = _pair(attrs.get("ESRIGNSS_LONGITUDE"), attrs.get("ESRIGNSS_LATITUDE"))
    geom = arcgis.point_lonlat(feature)
    if geom and not _pair(geom[0], geom[1]):
        geom = None
    if gnss and gnss_ok:
        return gnss
    if geom:
        return geom
    return gnss


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
    n_gnss = 0
    n_geom = 0
    n_disagreed = 0
    for f in features:
        a = f.get("attributes", {})
        oid = a.get("OBJECTID")
        gnss = _pair(a.get("ESRIGNSS_LONGITUDE"), a.get("ESRIGNSS_LATITUDE"))
        geom = arcgis.point_lonlat(f)
        coords = _sign_coords(f)
        if coords is None:
            continue
        lon, lat = coords
        if gnss and coords == gnss:
            n_gnss += 1
        else:
            n_geom += 1
        if gnss and geom and _haversine_m(geom[1], geom[0], gnss[1], gnss[0]) > 25:
            n_disagreed += 1

        name = _clean(a.get("markername")) or _clean(a.get("markernameother")) or "Unnamed marker"
        marker_text = _plaque_text(a)
        description = english_plaque_text(marker_text)
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
            description=description,
            official_url=urls.as_official(_clean(a.get("websitelink"))),
            image_url=photos.get(int(oid)) if oid is not None else None,
            image_credit="Michigan History Center" if (oid is not None and int(oid) in photos) else None,
            image_license="Michigan DNR Open Data" if (oid is not None and int(oid) in photos) else None,
            source=SOURCE,
            source_id=src_id,
            source_url=urls.feature_page_url(config.MARKERS_LAYER, oid),
            data_license=config.DATA_LICENSE[SOURCE],
            last_fetched=now,
            county=county,
            city=(_clean(a.get("markerlocationcity")) or "").title() or None,
            address=_clean(a.get("markerlocationaddress")),
            tags=tags,
            attributes={
                "marker_number": _clean(a.get("markerid")),
                "marker_text": marker_text,
                "erected_year": year_from_date(a.get("erecteddate")),
                "national_registry_year": a.get("nationalregistrydate") or None,
                "registry_listing_year": a.get("registrylistingyear") or None,
            },
        ))
        lm = landmarks[-1]
        facts.record_date(lm, "erected", erected)
        registry = a.get("nationalregistrydate") or a.get("registrylistingyear")
        if registry:
            facts.record_date(lm, "listed", registry)
            facts.add_recognition(lm, "National Register of Historic Places", registry, SOURCE)
    _logger.info(
        f"[markers] coords gnss={n_gnss} geometry={n_geom} "
        f"gnss_disagreed_>25m={n_disagreed}"
    )
    return landmarks
