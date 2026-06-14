"""Michigan lighthouses from Wikidata (WikiProject Lighthouses).

Selects items that are a lighthouse (P31/P279* Q39715) located in Michigan
(P131* Q1166) with coordinates, plus optional image, inception, USCG id, and the
English Wikipedia article as the official/descriptive link.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import config
from ..schema import Landmark, make_id, year_from_date
from . import wikidata

SOURCE = "Wikidata"

QUERY = f"""
SELECT ?item ?itemLabel ?desc ?coord ?image ?inception ?uscg ?height ?article WHERE {{
  ?item wdt:P31/wdt:P279* wd:{config.WD_LIGHTHOUSE} .
  ?item wdt:P131* wd:{config.WD_MICHIGAN} .
  ?item wdt:P625 ?coord .
  ?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en")
  OPTIONAL {{ ?item schema:description ?desc . FILTER(LANG(?desc) = "en") }}
  OPTIONAL {{ ?item wdt:P18 ?image . }}
  OPTIONAL {{ ?item wdt:P571 ?inception . }}
  OPTIONAL {{ ?item wdt:P3723 ?uscg . }}
  OPTIONAL {{ ?item wdt:P2048 ?height . }}
  OPTIONAL {{ ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }}
}}
"""


def fetch() -> list[Landmark]:
    now = datetime.now(timezone.utc).isoformat()
    rows = wikidata.run_sparql(QUERY)
    landmarks: dict[str, Landmark] = {}
    for r in rows:
        qid = wikidata.qid_from_uri(r.get("item"))
        coords = wikidata.parse_point(r.get("coord"))
        if not qid or not coords:
            continue
        if qid in landmarks:  # de-dupe SPARQL row multiplication
            continue
        lon, lat = coords
        inception = r.get("inception")
        landmarks[qid] = Landmark(
            id=make_id("lighthouse", SOURCE, qid),
            name=r.get("itemLabel") or qid,
            category="lighthouse",
            subtype="Lighthouse",
            latitude=lat,
            longitude=lon,
            description=r.get("desc"),
            official_url=r.get("article"),
            significant_date=inception.split("T")[0] if inception else None,
            date_type="built" if inception else None,
            year=year_from_date(inception),
            image_url=r.get("image"),
            image_credit="Wikimedia Commons" if r.get("image") else None,
            image_license=None,  # resolved later via Commons imageinfo
            source=SOURCE,
            source_id=qid,
            source_url=f"https://www.wikidata.org/wiki/{qid}",
            data_license=config.DATA_LICENSE[SOURCE],
            last_fetched=now,
            attributes={
                "uscg_id": r.get("uscg"),
                "focal_height_ft": _meters_to_feet(r.get("height")),
                "still_active": None,
                "wikidata_qid": qid,
            },
        )
    return list(landmarks.values())


def _meters_to_feet(value):
    if not value:
        return None
    try:
        return round(float(value) * 3.28084, 1)
    except (TypeError, ValueError):
        return None
