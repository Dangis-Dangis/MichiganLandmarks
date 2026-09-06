"""National Register of Historic Places points, filtered to Michigan.

The public points layer omits restricted-geography listings and represents
districts as a single point. Nomination PDFs live on ``attributes.nara_url``;
they are not the venue website.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import config, facts, urls
from ..schema import Landmark, make_id
from . import arcgis

SOURCE = "NRHP"


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def fetch() -> list[Landmark]:
    now = datetime.now(timezone.utc).isoformat()
    features = arcgis.query_features(config.NRHP_LAYER, where="State='MICHIGAN'")
    landmarks: list[Landmark] = []
    for f in features:
        a = f.get("attributes", {})
        coords = arcgis.point_lonlat(f)
        if coords is None:
            continue
        lon, lat = coords

        name = _clean(a.get("RESNAME")) or "Unnamed listing"
        refnum = _clean(a.get("NRIS_Refnum"))
        county = _clean(a.get("County"))
        is_nhl = (_clean(a.get("Is_NHL")) or "").upper() in {"Y", "YES", "TRUE", "1"}
        cert_date = facts.iso_date(a.get("CertDate"))
        nara = urls.normalize_url(_clean(a.get("NARA_URL")))
        oid = a.get("OBJECTID")
        attrs = {
            "ref_number": refnum,
            "property_type": _clean(a.get("ResType")),
            "is_nhl": is_nhl,
        }
        if nara:
            attrs["nara_url"] = nara

        lm = Landmark(
            id=make_id("nrhp_site", SOURCE, refnum or oid),
            name=name,
            category="nrhp_site",
            subtype=("National Historic Landmark" if is_nhl else _clean(a.get("ResType"))),
            latitude=lat,
            longitude=lon,
            description=None,
            official_url=None,
            source=SOURCE,
            source_id=refnum or str(oid),
            source_url=urls.feature_page_url(config.NRHP_LAYER, oid),
            data_license=config.DATA_LICENSE[SOURCE],
            last_fetched=now,
            county=county.title() if county else None,
            city=(_clean(a.get("City")) or _clean(a.get("Vicinity")) or "").title() or None,
            address=_clean(a.get("Address")),
            tags=["national_historic_landmark"] if is_nhl else [],
            attributes=attrs,
        )
        if cert_date:
            facts.record_date(lm, "listed", cert_date)
            facts.add_recognition(lm, "National Register of Historic Places", cert_date, SOURCE)
        if is_nhl:
            facts.add_recognition(lm, "National Historic Landmark", None, SOURCE)
        landmarks.append(lm)
    return landmarks
