"""Michigan museums from Wikidata, IMLS Museum Data Files, and Wikipedia.

Strategy:
1. Wikidata SPARQL — live museum (or subclass) items in Michigan with coordinates.
2. IMLS 2018 Museum Data Files ZIP — broader coverage; frozen snapshot; lat/lon when present.
3. Wikipedia "List of museums in Michigan" — Active section rows missing from (1)/(2)
   are geocoded unless ``--skip-nominatim-geocode`` is passed (article coords, then Nominatim
   name variants, then city/township locality as last resort). Defunct names are
   excluded from all sources.
4. Wikipedia Active enrichment upgrades weak IMLS coordinates when the article has
   a better point, and fills description / subtype / Wikipedia URL.

Within-category duplicates are merged here (pipeline dedupe only merges across categories).
"""
from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser

from .. import config, facts, geocode, log, stats, urls
from ..http_util import get_bytes, get_json, get_text
from ..schema import Landmark, make_id
from . import wikidata

SOURCE_WD = "Wikidata"
SOURCE_IMLS = "IMLS"
SOURCE_WP = "Wikipedia"

IMLS_ZIP_URL = config.IMLS_MUSEUM_ZIP
WIKI_PAGE = "List_of_museums_in_Michigan"
WIKI_ARTICLE_URL = f"https://en.wikipedia.org/wiki/{WIKI_PAGE}"

# Prefer structured sources when merging same-place museums.
_SOURCE_RANK = {SOURCE_WD: 0, SOURCE_IMLS: 1, SOURCE_WP: 2}

_NORM_RE = re.compile(r"[^a-z0-9\s]")
_STOPWORDS = {
    "the", "of", "and", "a", "museum", "museums", "historical", "history",
    "society", "center", "centre", "county", "area", "michigan",
}


QUERY = f"""
SELECT ?item ?itemLabel ?desc ?coord ?image ?article ?website ?inception WHERE {{
  ?item wdt:P31/wdt:P279* wd:{config.WD_MUSEUM} .
  ?item wdt:P131* wd:{config.WD_MICHIGAN} .
  ?item wdt:P625 ?coord .
  ?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en")
  OPTIONAL {{ ?item schema:description ?desc . FILTER(LANG(?desc) = "en") }}
  OPTIONAL {{ ?item wdt:P18 ?image . }}
  OPTIONAL {{ ?item wdt:P571 ?inception . }}
  OPTIONAL {{ ?item wdt:P856 ?website . }}
  OPTIONAL {{
    ?article schema:about ?item ;
             schema:isPartOf <https://en.wikipedia.org/> .
  }}
}}
"""


_leftover_rows: list[dict] = []
_leftover_now: str = ""


def pending_leftover_count() -> int:
    return len(_leftover_rows)


def fetch() -> list[Landmark]:
    global _leftover_rows, _leftover_now
    now = datetime.now(timezone.utc).isoformat()
    wd = _fetch_wikidata(now)
    log.info(f"[museums] Wikidata: {len(wd)} with coordinates")
    imls = _fetch_imls(now)
    log.info(f"[museums] IMLS: {len(imls)} Michigan rows with coordinates")

    active, defunct = _fetch_wikipedia_lists()
    log.info(f"[museums] Wikipedia Active={len(active)} Defunct={len(defunct)}")

    defunct_keys = {_name_key(n) for n in defunct if _name_key(n)}
    combined = _drop_defunct(wd + imls, defunct_keys)
    before_merge = len(combined)
    merged = _merge_same_category(combined)
    stats.add_museum_intra_merges(before_merge - len(merged))

    known = {_name_key(lm.name) for lm in merged}
    leftovers = []
    for row in active:
        key = _name_key(row["name"])
        if not key or key in defunct_keys:
            log.debug(log.fmt(
                "museums",
                f"skip leftover {row['name']!r}: defunct or empty name key",
            ))
            continue
        if key in known:
            log.debug(log.fmt(
                "museums",
                f"skip leftover {row['name']!r}: exact name already covered",
            ))
            continue
        match = next((lm.name for lm in merged if _name_similar(row["name"], lm.name)), None)
        if match:
            log.debug(log.fmt(
                "museums",
                f"skip leftover {row['name']!r}: similar to {match!r}",
            ))
            continue
        leftovers.append(row)
    log.info(f"[museums] Wikipedia Active not already covered: {len(leftovers)}")

    _leftover_rows = leftovers
    _leftover_now = now
    if leftovers and not config.MUSEUM_GEOCODE:
        stats.museum_leftovers_uncovered = len(leftovers)
        log.warn(
            f"[museums] skipping geocode of {len(leftovers)} Wikipedia Active leftovers "
            "(leftover Nominatim is off this run; omit --skip-nominatim-geocode to enable; "
            "Wikidata + IMLS coverage retained)"
        )
        for row in leftovers[:20]:
            log.warn(f"[museums] uncovered Wikipedia Active: {row['name']!r} ({row.get('location')})")
        if len(leftovers) > 20:
            log.warn(f"[museums] …and {len(leftovers) - 20} more uncovered Active entries")

    # Attach Wikipedia Active summaries onto existing museums when names match.
    _enrich_from_wikipedia_active(merged, active)

    dropped = sum(1 for lm in (wd + imls) if _name_key(lm.name) in defunct_keys)
    if dropped:
        log.warn(f"[museums] excluded {dropped} records matching Wikipedia Defunct names")
    log.info(f"[museums] total after merge: {len(merged)}")
    return merged


def geocode_leftovers() -> list[Landmark]:
    """Nominatim leftover geocoding (article → name → locality). Empty if none stashed."""
    if not _leftover_rows:
        return []
    return _geocode_wikipedia_leftovers(_leftover_rows, _leftover_now)


def absorb_geocoded(existing_museums: list[Landmark], geocoded: list[Landmark]) -> list[Landmark]:
    """Merge newly geocoded leftovers into the museum list; count intra-category merges."""
    if not geocoded:
        return list(existing_museums)
    before = len(existing_museums) + len(geocoded)
    merged = _merge_same_category(existing_museums + geocoded)
    stats.add_museum_intra_merges(before - len(merged))
    return merged


def _fetch_wikidata(now: str) -> list[Landmark]:
    try:
        rows = wikidata.run_sparql(QUERY)
    except RuntimeError as exc:
        log.error(f"[museums] Wikidata SPARQL failed: {exc}")
        return []
    landmarks: dict[str, Landmark] = {}
    skipped = 0
    for r in rows:
        qid = wikidata.qid_from_uri(r.get("item"))
        coords = wikidata.parse_point(r.get("coord"))
        if not qid or not coords:
            skipped += 1
            log.debug(log.fmt("museums", f"Wikidata skip row without qid/coords: {qid!r}"))
            continue
        if qid in landmarks:
            continue
        lon, lat = coords
        wiki = urls.as_wikipedia(r.get("article"))
        inception = r.get("inception")
        attrs = {"wikidata_qid": qid, "museum_sources": [SOURCE_WD]}
        if wiki:
            attrs["wikipedia_url"] = wiki
        lm = Landmark(
            id=make_id("museum", SOURCE_WD, qid),
            name=r.get("itemLabel") or qid,
            category="museum",
            subtype="Museum",
            latitude=lat,
            longitude=lon,
            description=r.get("desc"),
            official_url=urls.as_official(r.get("website")),
            image_url=r.get("image"),
            image_credit="Wikimedia Commons" if r.get("image") else None,
            source=SOURCE_WD,
            source_id=qid,
            source_url=f"https://www.wikidata.org/wiki/{qid}",
            data_license=config.DATA_LICENSE[SOURCE_WD],
            last_fetched=now,
            attributes=attrs,
        )
        facts.record_date(lm, "built", inception)
        landmarks[qid] = lm
    if skipped:
        log.warn(f"[museums] Wikidata skipped {skipped} rows without qid/coords")
    return list(landmarks.values())


def _fetch_imls(now: str) -> list[Landmark]:
    try:
        raw = _download_bytes(IMLS_ZIP_URL)
    except Exception as exc:  # noqa: BLE001
        log.error(f"[museums] IMLS ZIP download failed: {exc}")
        return []
    landmarks: list[Landmark] = []
    skipped_no_coord = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                with zf.open(name) as fh:
                    text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
                    reader = csv.DictReader(text)
                    for row in reader:
                        lm = _imls_row_to_landmark(row, now)
                        if lm is None:
                            lat = _float_or_none(row.get("LATITUDE"))
                            lon = _float_or_none(row.get("LONGITUDE"))
                            if _imls_is_michigan(row, lat, lon) and (lat is None or lon is None):
                                skipped_no_coord += 1
                            continue
                        landmarks.append(lm)
    except Exception as exc:  # noqa: BLE001
        log.error(f"[museums] IMLS ZIP parse failed: {exc}")
        return []
    if skipped_no_coord:
        log.warn(f"[museums] IMLS Michigan rows missing coordinates: {skipped_no_coord}")
    return landmarks


def _imls_is_michigan(row: dict, lat: float | None, lon: float | None) -> bool:
    """Prefer physical state; accept geocoded/admin MI only with in-state coordinates."""
    ph = (row.get("PHSTATE") or "").strip().upper()
    if ph == "MI":
        return True
    if ph:
        return False
    g = (row.get("GSTATE") or "").strip().upper()
    ad = (row.get("ADSTATE") or "").strip().upper()
    if g != "MI" and ad != "MI":
        return False
    if lat is None or lon is None:
        return False
    return 41.5 <= lat <= 48.3 and -90.6 <= lon <= -82.0


def _imls_row_to_landmark(row: dict, now: str) -> Landmark | None:
    lat = _float_or_none(row.get("LATITUDE"))
    lon = _float_or_none(row.get("LONGITUDE"))
    if not _imls_is_michigan(row, lat, lon):
        return None
    if lat is None or lon is None:
        return None
    if not (41.5 <= lat <= 48.3 and -90.6 <= lon <= -82.0):
        log.warn(
            f"[museums] IMLS coords outside Michigan for "
            f"{(row.get('COMMONNAME') or '').strip()!r}: {lat},{lon}"
        )
        return None
    mid = (row.get("MID") or "").strip()
    name = (
        (row.get("COMMONNAME") or "").strip()
        or (row.get("LEGALNAME") or "").strip()
        or mid
    )
    if not name or not mid:
        log.debug(log.fmt("museums", f"IMLS skip: missing name/mid (mid={mid!r})"))
        return None
    discipline = (row.get("DISCIPL") or row.get("DISCIPLINE") or "").strip() or None
    city = (row.get("PHCITY") or row.get("GCITY") or row.get("ADCITY") or "").strip() or None
    street = (row.get("PHSTREET") or row.get("GSTREET") or "").strip() or None
    zipc = (row.get("PHZIP") or row.get("GZIP") or "").strip() or None
    url = urls.as_official(row.get("WEBURL"))
    county_fips = (row.get("FIPSCO") or "").strip()
    county = None  # filled later from coords when missing
    street_line = ", ".join(
        p for p in (
            _title_case_name(street) if street else None,
            _title_case_name(city) if city else None,
            "MI",
            zipc,
        ) if p
    )
    address = street_line if urls.is_street_address(street_line) else None
    return Landmark(
        id=make_id("museum", SOURCE_IMLS, mid),
        name=_title_case_name(name),
        category="museum",
        subtype=discipline or "Museum",
        latitude=lat,
        longitude=lon,
        description=None,
        official_url=url,
        source=SOURCE_IMLS,
        source_id=mid,
        source_url=config.IMLS_DATASET_PAGE,
        data_license=config.DATA_LICENSE[SOURCE_IMLS],
        last_fetched=now,
        city=_title_case_name(city) if city else None,
        address=address,
        county=county,
        attributes={
            "imls_mid": mid,
            "imls_discipline": discipline,
            "imls_snapshot": "2018",
            "imls_zip_url": IMLS_ZIP_URL,
            "fips_county": county_fips or None,
            "museum_sources": [SOURCE_IMLS],
        },
    )


def _fetch_wikipedia_lists() -> tuple[list[dict], list[str]]:
    """Return (active_rows, defunct_names) from the CDN-cached wiki article HTML.

    Robot policy prefers /wiki/Title (or REST HTML) over Action API parse for page
    HTML: https://wikitech.wikimedia.org/wiki/Robot_policy
    """
    try:
        html = get_text(
            WIKI_ARTICLE_URL,
            headers={"Accept": "text/html"},
            timeout=config.REQUEST_TIMEOUT,
        )
    except RuntimeError as exc:
        log.error(f"[museums] Wikipedia article fetch failed: {exc}")
        return [], []
    if not html.strip():
        log.error("[museums] Wikipedia article returned empty HTML")
        return [], []
    parser = _WikiMuseumListParser()
    parser.feed(html)
    return parser.active, parser.defunct


def _geocode_wikipedia_leftovers(rows: list[dict], now: str) -> list[Landmark]:
    """Place Wikipedia Active leftovers that lack Wikidata/IMLS coordinates.

    Resolution order (stops at first hit):
    1. Wikipedia article coordinates from the row's wiki URL (when present)
    2. Nominatim on the museum name (with soft query variants)
    3. Nominatim on the Wikipedia list location (city/township/county) — last resort
    """
    from .. import progress

    out: list[Landmark] = []
    total = len(rows)
    geocode.reset_circuit()
    n_wiki = n_name = n_locality = 0
    for idx, row in enumerate(rows, start=1):
        name = row["name"]
        loc = (row.get("location") or "").strip()
        query = f"{name}, {loc}, Michigan" if loc else f"{name}, Michigan"
        progress.tick(idx, total, label="geocode")

        coords: tuple[float, float] | None = None
        precision = "name"
        geocode_via = None
        quality = "name"

        wiki_coords = _wikipedia_article_coords(
            row.get("url"), expect_name=name, leftover=True,
        )
        if wiki_coords:
            coords = wiki_coords
            precision = "article"
            geocode_via = "wikipedia_summary"
            quality = "site"
            n_wiki += 1
            log.info(log.fmt(
                "museums", f"wiki coords for {name!r}",
                step="geocode", idx=idx, total=total,
            ))

        if coords is None:
            try:
                coords = geocode.geocode_michigan(query, purpose="name")
            except geocode.RateLimitExceeded:
                left = total - idx + 1
                stats.museum_geocode_429_abort = left
                stats.museum_geocode_unplaced += left
                log.warn(log.fmt(
                    "museums",
                    f"stopped Wikipedia geocoding early; "
                    f"{left} leftovers left without coordinates "
                    "(Wikidata + IMLS coverage retained)",
                    step="geocode", idx=idx, total=total,
                ))
                break
            if coords:
                precision = "name"
                geocode_via = "nominatim_name"
                quality = "name"
                n_name += 1
                log.info(log.fmt(
                    "museums", f"name geocode for {name!r}",
                    step="geocode", idx=idx, total=total,
                ))

        if coords is None and loc:
            loc_query = f"{loc}, Michigan"
            try:
                coords = geocode.geocode_michigan(loc_query, purpose="locality")
            except geocode.RateLimitExceeded:
                left = total - idx + 1
                stats.museum_geocode_429_abort = left
                stats.museum_geocode_unplaced += left
                log.warn(log.fmt(
                    "museums",
                    f"stopped Wikipedia geocoding early; "
                    f"{left} leftovers left without coordinates "
                    "(Wikidata + IMLS coverage retained)",
                    step="geocode", idx=idx, total=total,
                ))
                break
            if coords:
                precision = "locality"
                geocode_via = "nominatim_city"
                quality = "locality"
                n_locality += 1
                log.warn(log.fmt(
                    "museums",
                    f"locality pin for {name!r} via {loc_query!r} "
                    "(city/township/county, not the building)",
                    step="geocode", idx=idx, total=total,
                ))

        if not coords:
            stats.museum_geocode_unplaced += 1
            log.warn(log.fmt(
                "museums",
                f"could not geocode Wikipedia Active entry: {name!r} ({loc})",
                step="geocode", idx=idx, total=total,
            ))
            continue

        lon, lat = coords
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "museum"
        attrs = {
            "museum_sources": [SOURCE_WP],
            "geocode_query": query,
            "geocode_precision": precision,
            "geocode_via": geocode_via,
            "description_source": "Wikipedia",
            "description_license": config.WIKIPEDIA_TEXT_LICENSE,
        }
        wiki = urls.as_wikipedia(row.get("url"))
        if wiki:
            attrs["wikipedia_url"] = wiki
        out.append(Landmark(
            id=make_id("museum", SOURCE_WP, slug),
            name=name,
            category="museum",
            subtype=row.get("type") or "Museum",
            latitude=lat,
            longitude=lon,
            description=row.get("summary") or None,
            official_url=None,
            city=loc or None,
            source=SOURCE_WP,
            source_id=slug,
            source_url=f"https://en.wikipedia.org/wiki/{WIKI_PAGE}",
            data_license=config.DATA_LICENSE[SOURCE_WP],
            last_fetched=now,
            location_quality=quality,
            attributes=attrs,
        ))
    stats.museum_geocode_article = n_wiki
    stats.museum_geocode_name = n_name
    stats.museum_geocode_locality = n_locality
    log.info(
        f"[museums] geocoded {len(out)}/{len(rows)} Wikipedia leftovers "
        f"(article={n_wiki}, name={n_name}, locality={n_locality})"
    )
    return out


def _wikipedia_article_coords(
    article_url: str | None,
    *,
    expect_name: str | None = None,
    leftover: bool = False,
) -> tuple[float, float] | None:
    """Return (lon, lat) from a Wikipedia REST page summary, if the article has coords.

    Section links (``…/Some_Park#Museum_Section``) are rejected: the REST summary
    returns the *parent* article's coordinates, which are usually wrong for the
    section subject. When ``expect_name`` is set, the summary title must also
    refer to the same place (avoids mismatched list URLs). Leftover geocode may
    accept alias-related building titles; parent parks/townships stay rejected.
    """
    if not article_url:
        log.debug(log.fmt("museums", "skip wiki coords: missing article URL"))
        return None
    if "#" in article_url:
        log.debug(log.fmt("museums", f"skip wiki coords: section URL {article_url!r}"))
        return None
    title = None
    if "/wiki/" in article_url:
        title = article_url.split("/wiki/", 1)[1].split("#", 1)[0].split("?", 1)[0]
    if not title or title.startswith("Special:") or "redlink" in article_url:
        log.debug(log.fmt("museums", f"skip wiki coords: Special/redlink/unparseable {article_url!r}"))
        return None
    url = config.WIKIPEDIA_SUMMARY + title
    try:
        data = get_json(
            url,
            timeout=config.ENRICH_TIMEOUT,
            retries=2,
            backoff=config.ENRICH_BACKOFF,
        )
    except RuntimeError as exc:
        # Missing articles (404) are common for list redlinks / soft titles.
        msg = str(exc)
        if "404" not in msg:
            log.warn(f"[museums] Wikipedia summary failed for {title!r}: {exc}")
        else:
            log.debug(log.fmt("museums", f"Wikipedia summary 404 for {title!r}"))
        return None
    if not isinstance(data, dict):
        log.debug(log.fmt("museums", f"Wikipedia summary not a dict for {title!r}"))
        return None
    page_title = data.get("title") or ""
    matcher = _leftover_article_matches if leftover else _article_subject_matches
    if expect_name and not matcher(expect_name, page_title, title):
        log.warn(
            f"[museums] skipping Wikipedia coords for {expect_name!r}: "
            f"article title {page_title!r} does not match"
        )
        stats.inc_coord_skip()
        return None
    coords = data.get("coordinates")
    if not isinstance(coords, dict):
        log.debug(log.fmt("museums", f"no coordinates dict on Wikipedia summary for {title!r}"))
        return None
    try:
        lat = float(coords["lat"])
        lon = float(coords["lon"])
    except (KeyError, TypeError, ValueError):
        log.debug(log.fmt("museums", f"bad Wikipedia coordinates for {title!r}"))
        return None
    if not (41.5 <= lat <= 48.3 and -90.6 <= lon <= -82.0):
        log.warn(f"[museums] Wikipedia coords outside Michigan for {title!r}: {lat},{lon}")
        return None
    if leftover and expect_name and not _article_subject_matches(expect_name, page_title, title):
        log.info(
            f"[museums] wiki coords for {expect_name!r} via related article {page_title!r}"
        )
    return lon, lat


def _article_subject_matches(museum_name: str, page_title: str, url_slug: str) -> bool:
    """True when the Wikipedia page is about this museum (not a loosely related park)."""
    slug_name = url_slug.replace("_", " ")
    for candidate in (page_title, slug_name):
        if not candidate:
            continue
        if _strong_name_match(museum_name, candidate):
            return True
        # Article title tokens contained in the museum name (or vice versa),
        # e.g. "National Ski Hall of Fame" ⊂ "U.S. National Ski and Snowboard …".
        ta, tb = _alias_tokens(candidate), _alias_tokens(museum_name)
        if ta and tb and (ta <= tb or tb <= ta) and len(ta & tb) >= 2:
            return True
    return False


_TOKEN_ALIASES = {
    "light": "lighthouse",
    "lighthouse": "lighthouse",
    "house": "house",
    "home": "house",
    "mansion": "house",
    "birthplace": "house",
    "houses": "house",
    "ste": "saint",
    "st": "saint",
    "saint": "saint",
    "sainte": "saint",
    "savior": "saviour",
    "saviour": "saviour",
}

_PARENT_GEOGRAPHY_RE = re.compile(
    r"\b(state park|metropark|national park|national marine sanctuary)\b",
    re.IGNORECASE,
)
_PARENT_PLACE_RE = re.compile(
    r"(?i)^.+\s+(charter\s+)?township(\s*,?\s*michigan)?$"
    r"|^.+\s+county(\s*,?\s*michigan)?$"
)


def _alias_tokens(name: str) -> set[str]:
    return {_TOKEN_ALIASES.get(t, t) for t in _tokens(name)}


def _is_parent_geography(title: str) -> bool:
    """True for park/sanctuary/township/county articles, not a building in one."""
    t = (title or "").replace("_", " ").strip()
    if not t:
        return False
    if _PARENT_GEOGRAPHY_RE.search(t):
        return True
    return bool(_PARENT_PLACE_RE.match(t))


def _leftover_article_matches(museum_name: str, page_title: str, url_slug: str) -> bool:
    """Leftover list links: accept same-building aliases; reject parent geography."""
    slug_name = url_slug.replace("_", " ")
    if _is_parent_geography(page_title) or _is_parent_geography(slug_name):
        return False
    return _article_subject_matches(museum_name, page_title, url_slug)


def _enrich_from_wikipedia_active(landmarks: list[Landmark], active: list[dict]) -> int:
    """Fill missing description / subtype / URL from Wikipedia Active rows by name.

    Also upgrades coordinates from the Wikipedia article when present and the
    current point looks unreliable (IMLS-only, Wikipedia geocode, or >250 m away).
    IMLS 2018 centroids are often city-ish and can be hundreds of meters to
    kilometers off the real building.

    Coordinate upgrades require a *strong* name match so a loosely related
    Active-list row (e.g. another "Keweenaw …" society) cannot move the pin.
    """
    by_key: dict[str, dict] = {}
    for row in active:
        key = _name_key(row.get("name"))
        if key:
            by_key[key] = row
    enriched = 0
    coords_upgraded = 0
    for lm in landmarks:
        exact = by_key.get(_name_key(lm.name))
        fuzzy = None
        if not exact:
            # Fall back to fuzzy name match against Active list (small).
            fuzzy = next((r for r in active if _name_similar(lm.name, r["name"])), None)
        row = exact or fuzzy
        if not row:
            continue
        changed = False
        if not lm.description and row.get("summary"):
            lm.description = row["summary"]
            lm.attributes["description_source"] = "Wikipedia"
            lm.attributes["description_license"] = config.WIKIPEDIA_TEXT_LICENSE
            changed = True
        if row.get("type") and (not lm.subtype or lm.subtype == "Museum" or len(lm.subtype) <= 3):
            # Prefer Wikipedia's human subtype over short IMLS discipline codes.
            lm.subtype = row["type"]
            changed = True
        wiki_url = urls.as_wikipedia(row.get("url")) if _strong_name_match(lm.name, row["name"]) else None
        if wiki_url and not lm.attributes.get("wikipedia_url"):
            lm.attributes["wikipedia_url"] = wiki_url
            changed = True
        if not lm.city and row.get("location"):
            lm.city = row["location"]
            changed = True
        # Prefer the Active-list display name when it is clearly more specific.
        if row.get("name") and _should_prefer_wikipedia_name(lm.name, row["name"]):
            lm.name = row["name"]
            changed = True

        # Coord upgrades: strong name match only (never weak fuzzy / subset matches).
        wiki_coords = None
        if (
            lm.source != SOURCE_WD
            and wiki_url
            and _location_compatible(lm.city, row.get("location"))
        ):
            wiki_coords = _wikipedia_article_coords(wiki_url, expect_name=lm.name)
        if wiki_coords and _should_upgrade_coords(lm, wiki_coords):
            old_lat, old_lon = lm.latitude, lm.longitude
            lon, lat = wiki_coords
            lm.latitude = lat
            lm.longitude = lon
            lm.attributes["geocode_via"] = "wikipedia_summary"
            lm.attributes["geocode_precision"] = "article"
            lm.location_quality = "site"
            lm.attributes["coords_replaced_from"] = {
                "latitude": old_lat,
                "longitude": old_lon,
                "source": lm.source,
            }
            coords_upgraded += 1
            changed = True
            log.info(
                f"[museums] upgraded coords for {lm.name!r} "
                f"from ({old_lat},{old_lon}) -> ({lat},{lon}) via Wikipedia article"
            )

        srcs = list(lm.attributes.get("museum_sources") or [lm.source])
        if SOURCE_WP not in srcs and changed:
            srcs.append(SOURCE_WP)
            lm.attributes["museum_sources"] = srcs
        if changed:
            enriched += 1
    if coords_upgraded:
        stats.museum_coord_upgrades = coords_upgraded
        log.info(f"[museums] upgraded {coords_upgraded} coordinates from Wikipedia articles")
    if enriched:
        log.info(f"[museums] enriched {enriched} records from Wikipedia Active text")
    return enriched


def _wikipedia_article_url(href: str | None) -> str | None:
    """Normalize a wiki list href to a real article URL; drop redlinks."""
    if not href:
        return None
    href = href.strip()
    # CDN HTML often uses absolute https://en.wikipedia.org/wiki/…?redlink=1
    if "redlink" in href.lower() or "action=edit" in href.lower():
        return None
    if href.startswith("/wiki/"):
        path = href.split("?", 1)[0]
        if path == "/wiki/" or path.startswith("/wiki/Special:"):
            return None
        return "https://en.wikipedia.org" + path
    if href.startswith("https://en.wikipedia.org/wiki/") or href.startswith(
        "http://en.wikipedia.org/wiki/"
    ):
        path = href.split("?", 1)[0]
        return path.replace("http://", "https://", 1)
    return None


def _should_prefer_wikipedia_name(current: str, wiki_name: str) -> bool:
    if not wiki_name or wiki_name == current:
        return False
    # Prefer Wikipedia when it adds distinctive tokens (e.g. Snowboard) or is longer.
    if not _strong_name_match(current, wiki_name):
        return False
    return len(_tokens(wiki_name)) > len(_tokens(current)) or len(wiki_name) > len(current) + 4


def _strong_name_match(a: str, b: str) -> bool:
    """Stricter than ``_name_similar`` — no subset matches; used for coord moves."""
    ka = " ".join(sorted(_alias_tokens(a)))
    kb = " ".join(sorted(_alias_tokens(b)))
    if ka and ka == kb:
        return True
    ta, tb = _alias_tokens(a), _alias_tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    return bool(union) and inter / union >= 0.7


def _location_compatible(city: str | None, wiki_location: str | None) -> bool:
    """When both sides name a place, require a token overlap (Ishpeming/Ishpeming)."""
    if not city or not wiki_location:
        return True
    ca = {t for t in _NORM_RE.sub(" ", city.lower()).split() if t and t not in _STOPWORDS}
    cb = {
        t for t in _NORM_RE.sub(" ", wiki_location.lower()).split()
        if t and t not in _STOPWORDS
    }
    if not ca or not cb:
        return True
    return bool(ca & cb)


# Upgrade IMLS (etc.) points when the Wikipedia article is meaningfully elsewhere.
_COORD_UPGRADE_MIN_M = 250.0


def _should_upgrade_coords(lm: Landmark, wiki_coords: tuple[float, float]) -> bool:
    lon, lat = wiki_coords
    dist = _haversine_m(lm.latitude, lm.longitude, lat, lon)
    via = (lm.attributes or {}).get("geocode_via")
    if via in ("nominatim_city", "nominatim_name"):
        return dist > 25.0
    srcs = lm.attributes.get("museum_sources") or [lm.source]
    # Wikidata coordinates are usually curated; only replace if far off.
    if SOURCE_WD in srcs and lm.source == SOURCE_WD:
        return dist > 1000.0
    # IMLS 2018 geocodes are the common failure mode.
    if SOURCE_IMLS in srcs or lm.source == SOURCE_IMLS:
        return dist > _COORD_UPGRADE_MIN_M
    return dist > _COORD_UPGRADE_MIN_M


def _drop_defunct(records: list[Landmark], defunct_keys: set[str]) -> list[Landmark]:
    kept = []
    for lm in records:
        key = _name_key(lm.name)
        if key and key in defunct_keys:
            log.debug(log.fmt("museums", f"drop defunct {lm.name!r} ({lm.source})"))
            continue
        kept.append(lm)
    return kept


def _merge_same_category(records: list[Landmark]) -> list[Landmark]:
    """Merge museum records that are near each other and name-similar."""
    n = len(records)
    if n <= 1:
        return list(records)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    grid: dict[tuple[int, int], list[int]] = {}
    for i, lm in enumerate(records):
        key = (round(lm.latitude / 0.002), round(lm.longitude / 0.002))
        grid.setdefault(key, []).append(i)

    for (gx, gy), idxs in grid.items():
        neighbors: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbors.extend(grid.get((gx + dx, gy + dy), []))
        for i in idxs:
            a = records[i]
            for j in neighbors:
                if j <= i:
                    continue
                b = records[j]
                if _haversine_m(a.latitude, a.longitude, b.latitude, b.longitude) > 120.0:
                    continue
                if _name_similar(a.name, b.name):
                    union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    merged: list[Landmark] = []
    for members in clusters.values():
        members.sort(key=lambda i: (
            _SOURCE_RANK.get(records[i].source, 99),
            records[i].name.lower(),
        ))
        primary = records[members[0]]
        for i in members[1:]:
            other = records[i]
            absorbed = _absorb_museum(primary, other)
            dist = _haversine_m(
                primary.latitude, primary.longitude, other.latitude, other.longitude,
            )
            _ok, jaccard, reason = _name_score(primary.name, other.name)
            log.debug(log.fmt(
                "museums",
                f"intra-merge {primary.name!r} ({primary.source}) <- "
                f"{other.name!r} ({other.source}) d={dist:.0f}m "
                f"j={jaccard:.2f} ({reason}) absorbed={','.join(absorbed) or 'tags'}",
            ))
        merged.append(primary)
    return merged


def _absorb_museum(primary: Landmark, other: Landmark) -> list[str]:
    absorbed: list[str] = []
    srcs = list(primary.attributes.get("museum_sources") or [primary.source])
    for s in (other.attributes.get("museum_sources") or [other.source]):
        if s not in srcs:
            srcs.append(s)
            absorbed.append(s)
    primary.attributes["museum_sources"] = srcs
    if not primary.description and other.description:
        primary.description = other.description
        absorbed.append("description")
        for k in ("description_source", "description_license"):
            if other.attributes.get(k):
                primary.attributes[k] = other.attributes[k]
    if not primary.image_url and other.image_url:
        primary.image_url = other.image_url
        primary.image_credit = other.image_credit
        primary.image_license = other.image_license
        absorbed.append("image")
    prev_url = primary.official_url
    primary.official_url = urls.prefer_official(primary.official_url, other.official_url)
    if primary.official_url and primary.official_url != prev_url:
        absorbed.append("official_url")
    if not primary.attributes.get("wikipedia_url") and other.attributes.get("wikipedia_url"):
        primary.attributes["wikipedia_url"] = other.attributes["wikipedia_url"]
        absorbed.append("wikipedia_url")
    if not primary.attributes.get("nara_url") and other.attributes.get("nara_url"):
        primary.attributes["nara_url"] = other.attributes["nara_url"]
        absorbed.append("nara_url")
    if not primary.city and other.city:
        primary.city = other.city
        absorbed.append("city")
    if not primary.address and other.address:
        primary.address = other.address
        absorbed.append("address")
    if not primary.subtype or primary.subtype == "Museum":
        if other.subtype and other.subtype != "Museum":
            primary.subtype = other.subtype
            absorbed.append("subtype")
    for key in (
        "imls_mid", "imls_discipline", "wikidata_qid",
        "geocode_query", "geocode_precision", "geocode_via",
    ):
        if key not in primary.attributes and other.attributes.get(key):
            primary.attributes[key] = other.attributes[key]
            absorbed.append(key)
    rank = {"site": 0, "name": 1, "locality": 2}
    oq = other.location_quality
    pq = primary.location_quality
    if oq and (not pq or rank.get(oq, 9) < rank.get(pq, 9)):
        primary.location_quality = oq
        absorbed.append("location_quality")
    facts.merge_facts(primary, other)
    return absorbed


def _name_key(name: str | None) -> str:
    tokens = _tokens(name or "")
    return " ".join(sorted(tokens))


def _tokens(name: str) -> set[str]:
    name = _NORM_RE.sub(" ", (name or "").lower())
    return {t for t in name.split() if t and t not in _STOPWORDS}


def _name_score(a: str, b: str) -> tuple[bool, float, str]:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False, 0.0, "empty"
    inter = len(ta & tb)
    union = len(ta | tb)
    jaccard = inter / union if union else 0.0
    if jaccard >= 0.5:
        return True, jaccard, "jaccard"
    if ta <= tb or tb <= ta:
        return True, jaccard, "subset"
    return False, jaccard, "none"


def _name_similar(a: str, b: str) -> bool:
    return _name_score(a, b)[0]


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _title_case_name(value: str | None) -> str:
    if not value:
        return ""
    # IMLS names are often ALL CAPS.
    if value.isupper() and len(value) > 3:
        return value.title()
    return value


def _download_bytes(url: str) -> bytes:
    return get_bytes(url, headers={"Accept": "*/*"}, timeout=config.REQUEST_TIMEOUT)


class _WikiMuseumListParser(HTMLParser):
    """Extract Active / Defunct museum entries from the Wikipedia parse HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.active: list[dict] = []
        self.defunct: list[str] = []
        self._section: str | None = None  # "active" | "defunct" | None
        self._in_h2 = False
        self._h2_bits: list[str] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_text: list[str] = []
        self._cell_href: str | None = None
        self._row_cells: list[tuple[str, str | None]] = []
        self._seen_header = False
        self._in_li = False
        self._li_bits: list[str] = []
        self._li_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "h2":
            self._in_h2 = True
            self._h2_bits = []
            hid = (attrs_d.get("id") or "").replace("_", " ").strip().lower()
            if hid.startswith("active"):
                self._section = "active"
            elif hid.startswith("defunct"):
                self._section = "defunct"
            elif hid in ("regions", "see also", "references", "resources"):
                self._section = None
        elif tag == "table" and self._section == "active":
            classes = attrs_d.get("class", "")
            if "wikitable" in classes:
                self._in_table = True
                self._seen_header = False
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row_cells = []
        elif self._in_row and tag in ("td", "th"):
            self._in_cell = True
            self._cell_text = []
            self._cell_href = None
        elif self._in_cell and tag == "a" and self._cell_href is None:
            href = attrs_d.get("href")
            if href and not href.startswith("#"):
                self._cell_href = href
        elif self._section == "defunct" and tag == "li" and self._li_depth == 0:
            self._in_li = True
            self._li_bits = []
            self._li_depth = 1
        elif self._in_li and tag == "li":
            self._li_depth += 1

    def handle_endtag(self, tag):
        if tag == "h2" and self._in_h2:
            title = " ".join(self._h2_bits).strip().lower()
            if title.startswith("active"):
                self._section = "active"
            elif title.startswith("defunct"):
                self._section = "defunct"
            elif title:
                if self._section in ("active", "defunct"):
                    self._section = None
            self._in_h2 = False
            self._h2_bits = []
        elif tag == "table" and self._in_table:
            self._in_table = False
        elif tag == "tr" and self._in_row:
            self._finish_row()
            self._in_row = False
        elif tag in ("td", "th") and self._in_cell:
            text = " ".join("".join(self._cell_text).split())
            self._row_cells.append((text, self._cell_href))
            self._in_cell = False
        elif tag == "li" and self._in_li:
            self._li_depth -= 1
            if self._li_depth <= 0:
                self._in_li = False
                self._li_depth = 0
                text = " ".join("".join(self._li_bits).split())
                name = text.split(",", 1)[0].split(" - ", 1)[0].split(" – ", 1)[0].strip()
                # Drop trailing citation markers like [1]
                name = re.sub(r"\s*\[\d+\]\s*$", "", name).strip()
                if name:
                    self.defunct.append(name)

    def handle_data(self, data):
        if self._in_h2:
            self._h2_bits.append(data)
        elif self._in_cell:
            self._cell_text.append(data)
        elif self._in_li and self._li_depth == 1:
            self._li_bits.append(data)

    def _finish_row(self) -> None:
        if not self._row_cells:
            return
        first = self._row_cells[0][0].strip().lower()
        if first in ("name", "museum"):
            self._seen_header = True
            return
        if not self._seen_header and all(
            c[0].lower() in ("name", "location", "county", "region", "type", "summary", "city")
            for c in self._row_cells[:3]
        ):
            self._seen_header = True
            return
        self._seen_header = True
        name = self._row_cells[0][0].strip()
        if not name or self._section != "active":
            return
        location = self._row_cells[1][0].strip() if len(self._row_cells) > 1 else ""
        mtype = self._row_cells[4][0].strip() if len(self._row_cells) > 4 else ""
        summary = self._row_cells[5][0].strip() if len(self._row_cells) > 5 else ""
        href = self._row_cells[0][1]
        url = _wikipedia_article_url(href)
        self.active.append({
            "name": name,
            "location": location,
            "type": mtype or None,
            "summary": summary or None,
            "url": url,
        })
