"""Michigan state parks and recreation areas (DNR recreation-search points).

One point per park unit. Descriptions/photos are sparse in the source, so these
records are good candidates for optional Wikipedia enrichment downstream.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import config, urls
from ..schema import Landmark, make_id
from . import arcgis

SOURCE = "MI-DNR-StateParks"


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def fetch() -> list[Landmark]:
    now = datetime.now(timezone.utc).isoformat()
    features = arcgis.query_features(config.STATE_PARKS_LAYER)
    landmarks: list[Landmark] = []
    for f in features:
        a = f.get("attributes", {})
        coords = arcgis.point_lonlat(f)
        if coords is None:
            lon, lat = a.get("Longitude"), a.get("Latitude")
            if lon is None or lat is None:
                continue
            coords = (float(lon), float(lat))
        lon, lat = coords

        name = _clean(a.get("Label")) or _clean(a.get("Name")) or "Unnamed park"
        if name and "state park" not in name.lower() and "recreation" not in name.lower():
            display = name  # keep the source label; many already include the suffix
        else:
            display = name
        src_id = _clean(a.get("Unique_Id")) or _clean(a.get("UnitID")) or str(a.get("OBJECTID"))

        landmarks.append(Landmark(
            id=make_id("state_park", SOURCE, src_id),
            name=display,
            category="state_park",
            subtype="State Park or Recreation Area",
            latitude=lat,
            longitude=lon,
            description=None,
            official_url=urls.as_official(_clean(a.get("url"))),
            source=SOURCE,
            source_id=src_id,
            source_url=urls.feature_page_url(config.STATE_PARKS_LAYER, a.get("OBJECTID")),
            data_license=config.DATA_LICENSE[SOURCE],
            last_fetched=now,
            city=(_clean(a.get("City")) or "").title() or None,
            address=_clean(a.get("Addr1")),
            attributes={
                "phone": _clean(a.get("MainPhone")),
                "park_type": "state_park",
            },
        ))
    return landmarks
