"""National Park Service units in Michigan.

Primary path: the official NPS Data API (requires a free NPS_API_KEY). When no key
is configured, falls back to Wikidata for NPS-administered places in Michigan, so
the dataset is complete either way. The chosen path is recorded on each record.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import config
from ..http_util import get_json
from ..schema import Landmark, make_id, year_from_date
from . import wikidata

SOURCE_API = "NPS"
SOURCE_WD = "Wikidata"

_WD_QUERY = f"""
SELECT ?item ?itemLabel ?desc ?coord ?image ?inception ?article ?typeLabel WHERE {{
  ?item wdt:P137 wd:{config.WD_NPS} .
  ?item wdt:P131* wd:{config.WD_MICHIGAN} .
  ?item wdt:P625 ?coord .
  ?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en")
  OPTIONAL {{ ?item schema:description ?desc . FILTER(LANG(?desc) = "en") }}
  OPTIONAL {{ ?item wdt:P18 ?image . }}
  OPTIONAL {{ ?item wdt:P571 ?inception . }}
  OPTIONAL {{ ?item wdt:P31 ?type . ?type rdfs:label ?typeLabel . FILTER(LANG(?typeLabel) = "en") }}
  OPTIONAL {{ ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }}
}}
"""


def fetch() -> list[Landmark]:
    if config.NPS_API_KEY:
        try:
            return _fetch_api()
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail the run
            from .. import log
            log.warn(f"[nps] API path failed ({exc}); falling back to Wikidata")

    return _fetch_wikidata()


def _fetch_api() -> list[Landmark]:
    now = datetime.now(timezone.utc).isoformat()
    payload = get_json(
        config.NPS_API_BASE + "/parks",
        {"stateCode": "mi", "limit": 100, "api_key": config.NPS_API_KEY},
    )
    landmarks: list[Landmark] = []
    for p in payload.get("data", []):
        try:
            lat, lon = float(p["latitude"]), float(p["longitude"])
        except (KeyError, ValueError, TypeError):
            continue
        images = p.get("images") or []
        img = images[0] if images else {}
        park_code = p.get("parkCode")
        landmarks.append(Landmark(
            id=make_id("national_park_unit", SOURCE_API, park_code or p.get("id")),
            name=p.get("fullName") or p.get("name") or "NPS unit",
            category="national_park_unit",
            subtype=p.get("designation") or None,
            latitude=lat,
            longitude=lon,
            description=p.get("description") or None,
            official_url=p.get("url") or None,
            image_url=img.get("url") or None,
            image_credit=img.get("credit") or "National Park Service",
            image_license="Public domain (NPS)" if img.get("url") else None,
            source=SOURCE_API,
            source_id=park_code or str(p.get("id")),
            source_url=p.get("url"),
            data_license=config.DATA_LICENSE[SOURCE_API],
            last_fetched=now,
            attributes={
                "designation": p.get("designation"),
                "park_code": park_code,
                "entrance_fee": _has_fee(p),
                "fetched_via": "nps_api",
            },
        ))
    return landmarks


def _fetch_wikidata() -> list[Landmark]:
    now = datetime.now(timezone.utc).isoformat()
    rows = wikidata.run_sparql(_WD_QUERY)
    landmarks: dict[str, Landmark] = {}
    for r in rows:
        qid = wikidata.qid_from_uri(r.get("item"))
        coords = wikidata.parse_point(r.get("coord"))
        if not qid or not coords:
            continue
        if qid in landmarks:
            continue
        lon, lat = coords
        inception = r.get("inception")
        landmarks[qid] = Landmark(
            id=make_id("national_park_unit", SOURCE_WD, qid),
            name=r.get("itemLabel") or qid,
            category="national_park_unit",
            subtype=r.get("typeLabel") or None,
            latitude=lat,
            longitude=lon,
            description=r.get("desc") or None,
            official_url=r.get("article"),
            significant_date=inception.split("T")[0] if inception else None,
            date_type="established" if inception else None,
            year=year_from_date(inception),
            image_url=r.get("image"),
            image_credit="Wikimedia Commons" if r.get("image") else None,
            image_license=None,
            source=SOURCE_WD,
            source_id=qid,
            source_url=f"https://www.wikidata.org/wiki/{qid}",
            data_license=config.DATA_LICENSE[SOURCE_WD],
            last_fetched=now,
            attributes={"fetched_via": "wikidata_fallback", "wikidata_qid": qid},
        )
    return list(landmarks.values())


def _has_fee(park: dict) -> bool | None:
    fees = park.get("entranceFees")
    if fees is None:
        return None
    for fee in fees:
        try:
            if float(fee.get("cost", 0)) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False
