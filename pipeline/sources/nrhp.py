"""National Register of Historic Places points, filtered to Michigan.

The public points layer omits restricted-geography listings and represents
districts as a single point. Official link goes to the National Archives catalog.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import config
from ..schema import Landmark, make_id, year_from_date
from . import arcgis

SOURCE = "NRHP"


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _epoch_to_year(value):
    """NRHP date fields are sometimes epoch milliseconds (esriFieldTypeDate)."""
    if value is None:
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return year_from_date(value)
    # plausible epoch-ms range for NRHP listings (1960s-now)
    if ms > 10**11:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year
    return year_from_date(value)


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
        cert = a.get("CertDate")
        year = _epoch_to_year(cert) or _epoch_to_year(a.get("CREATEDATE"))
        nara = _clean(a.get("NARA_URL"))

        landmarks.append(Landmark(
            id=make_id("nrhp_site", SOURCE, refnum or a.get("OBJECTID")),
            name=name,
            category="nrhp_site",
            subtype=("National Historic Landmark" if is_nhl else _clean(a.get("ResType"))),
            latitude=lat,
            longitude=lon,
            description=None,
            official_url=nara,
            significant_date=str(year) if year else None,
            date_type="listed" if year else None,
            year=year,
            source=SOURCE,
            source_id=refnum or str(a.get("OBJECTID")),
            source_url=config.NRHP_LAYER + f"/query?where=NRIS_Refnum='{refnum}'" if refnum else None,
            data_license=config.DATA_LICENSE[SOURCE],
            last_fetched=now,
            county=county.title() if county else None,
            city=(_clean(a.get("City")) or _clean(a.get("Vicinity")) or "").title() or None,
            address=_clean(a.get("Address")),
            region=config.region_for_county(county),
            tags=["national_historic_landmark"] if is_nhl else [],
            attributes={
                "ref_number": refnum,
                "property_type": _clean(a.get("ResType")),
                "is_nhl": is_nhl,
            },
        ))
    return landmarks
