"""Michigan museums from Wikidata, IMLS Museum Data Files, and Wikipedia.

Strategy:
1. Wikidata SPARQL — live museum (or subclass) items in Michigan with coordinates.
2. IMLS 2018 Museum Data Files ZIP — broader coverage; frozen snapshot; lat/lon when present.
3. Wikipedia "List of museums in Michigan" — Active section rows missing from (1)/(2)
   are geocoded (rate-limited Nominatim); Defunct names are excluded from all sources.

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

from .. import config, geocode, log
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
SELECT ?item ?itemLabel ?desc ?coord ?image ?article ?inception WHERE {{
  ?item wdt:P31/wdt:P279* wd:{config.WD_MUSEUM} .
  ?item wdt:P131* wd:{config.WD_MICHIGAN} .
  ?item wdt:P625 ?coord .
  ?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en")
  OPTIONAL {{ ?item schema:description ?desc . FILTER(LANG(?desc) = "en") }}
  OPTIONAL {{ ?item wdt:P18 ?image . }}
  OPTIONAL {{ ?item wdt:P571 ?inception . }}
  OPTIONAL {{
    ?article schema:about ?item ;
             schema:isPartOf <https://en.wikipedia.org/> .
  }}
}}
"""


def fetch() -> list[Landmark]:
    now = datetime.now(timezone.utc).isoformat()
    wd = _fetch_wikidata(now)
    log.info(f"[museums] Wikidata: {len(wd)} with coordinates")
    imls = _fetch_imls(now)
    log.info(f"[museums] IMLS: {len(imls)} Michigan rows with coordinates")

    active, defunct = _fetch_wikipedia_lists()
    log.info(f"[museums] Wikipedia Active={len(active)} Defunct={len(defunct)}")

    defunct_keys = {_name_key(n) for n in defunct if _name_key(n)}
    combined = _drop_defunct(wd + imls, defunct_keys)
    merged = _merge_same_category(combined)

    known = {_name_key(lm.name) for lm in merged}
    leftovers = []
    for row in active:
        key = _name_key(row["name"])
        if not key or key in defunct_keys:
            continue
        if key in known:
            continue
        if any(_name_similar(row["name"], lm.name) for lm in merged):
            continue
        leftovers.append(row)
    log.info(f"[museums] Wikipedia Active not already covered: {len(leftovers)}")

    # Nominatim leftover geocoding is opt-in: public Nominatim rate-limits bulk
    # builds (HTTP 429). Wikidata + IMLS already cover ~1k Michigan museums.
    if leftovers and config.MUSEUM_GEOCODE:
        geocoded = _geocode_wikipedia_leftovers(leftovers, now)
        if geocoded:
            merged = _merge_same_category(merged + geocoded)
    elif leftovers:
        log.warn(
            f"[museums] skipping geocode of {len(leftovers)} Wikipedia Active leftovers "
            "(set MUSEUM_GEOCODE=1 to enable rate-limited Nominatim; "
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
            continue
        if qid in landmarks:
            continue
        lon, lat = coords
        landmarks[qid] = Landmark(
            id=make_id("museum", SOURCE_WD, qid),
            name=r.get("itemLabel") or qid,
            category="museum",
            subtype="Museum",
            latitude=lat,
            longitude=lon,
            description=r.get("desc"),
            official_url=r.get("article"),
            image_url=r.get("image"),
            image_credit="Wikimedia Commons" if r.get("image") else None,
            source=SOURCE_WD,
            source_id=qid,
            source_url=f"https://www.wikidata.org/wiki/{qid}",
            data_license=config.DATA_LICENSE[SOURCE_WD],
            last_fetched=now,
            attributes={"wikidata_qid": qid, "museum_sources": [SOURCE_WD]},
        )
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
        return None
    discipline = (row.get("DISCIPL") or row.get("DISCIPLINE") or "").strip() or None
    city = (row.get("PHCITY") or row.get("GCITY") or row.get("ADCITY") or "").strip() or None
    street = (row.get("PHSTREET") or row.get("GSTREET") or "").strip() or None
    zipc = (row.get("PHZIP") or row.get("GZIP") or "").strip() or None
    url = (row.get("WEBURL") or "").strip() or None
    if url and not url.lower().startswith("http"):
        url = "http://" + url
    county_fips = (row.get("FIPSCO") or "").strip()
    county = None  # filled later from coords when missing
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
        source_url=IMLS_ZIP_URL,
        data_license=config.DATA_LICENSE[SOURCE_IMLS],
        last_fetched=now,
        city=_title_case_name(city) if city else None,
        address=", ".join(p for p in (_title_case_name(street) if street else None,
                                      _title_case_name(city) if city else None,
                                      "MI", zipc) if p),
        county=county,
        attributes={
            "imls_mid": mid,
            "imls_discipline": discipline,
            "imls_snapshot": "2018",
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
    3. Nominatim on the city/township only (approximate pin)
    """
    out: list[Landmark] = []
    total = len(rows)
    geocode.reset_circuit()
    skipped_rate_limit = 0
    n_wiki = n_name = n_city = 0
    for idx, row in enumerate(rows, start=1):
        name = row["name"]
        loc = (row.get("location") or "").strip()
        query = f"{name}, {loc}, Michigan" if loc else f"{name}, Michigan"
        if idx == 1 or idx % 25 == 0 or idx == total:
            log.info(f"[museums] geocoding Wikipedia leftovers {idx}/{total}…")

        coords: tuple[float, float] | None = None
        precision = "name"
        geocode_via = None

        wiki_coords = _wikipedia_article_coords(row.get("url"))
        if wiki_coords:
            coords = wiki_coords
            precision = "article"
            geocode_via = "wikipedia_summary"
            n_wiki += 1
            log.info(f"[museums] wiki coords for {name!r}")

        if coords is None:
            try:
                coords = geocode.geocode_michigan(query)
            except geocode.RateLimitExceeded:
                skipped_rate_limit = total - idx + 1
                log.warn(
                    f"[museums] stopped Wikipedia geocoding early; "
                    f"{skipped_rate_limit} leftovers left without coordinates "
                    "(Wikidata + IMLS coverage retained)"
                )
                break
            if coords:
                precision = "name"
                geocode_via = "nominatim_name"
                n_name += 1

        if coords is None and loc:
            try:
                coords = geocode.geocode_michigan(f"{loc}, Michigan")
            except geocode.RateLimitExceeded:
                skipped_rate_limit = total - idx + 1
                log.warn(
                    f"[museums] stopped Wikipedia geocoding early; "
                    f"{skipped_rate_limit} leftovers left without coordinates "
                    "(Wikidata + IMLS coverage retained)"
                )
                break
            if coords:
                precision = "city"
                geocode_via = "nominatim_city"
                n_city += 1
                log.info(f"[museums] city-level pin for {name!r} via {loc!r}")

        if not coords:
            log.warn(f"[museums] could not geocode Wikipedia Active entry: {name!r} ({loc})")
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
        out.append(Landmark(
            id=make_id("museum", SOURCE_WP, slug),
            name=name,
            category="museum",
            subtype=row.get("type") or "Museum",
            latitude=lat,
            longitude=lon,
            description=row.get("summary") or None,
            official_url=row.get("url"),
            city=loc or None,
            source=SOURCE_WP,
            source_id=slug,
            source_url=f"https://en.wikipedia.org/wiki/{WIKI_PAGE}",
            data_license=config.DATA_LICENSE[SOURCE_WP],
            last_fetched=now,
            attributes=attrs,
        ))
    log.info(
        f"[museums] geocoded {len(out)}/{len(rows)} Wikipedia leftovers "
        f"(article={n_wiki}, name={n_name}, city={n_city})"
    )
    return out


def _wikipedia_article_coords(article_url: str | None) -> tuple[float, float] | None:
    """Return (lon, lat) from a Wikipedia REST page summary, if the article has coords."""
    if not article_url:
        return None
    title = None
    if "/wiki/" in article_url:
        title = article_url.split("/wiki/", 1)[1].split("#", 1)[0].split("?", 1)[0]
    if not title or title.startswith("Special:") or "redlink" in article_url:
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
        return None
    coords = data.get("coordinates") if isinstance(data, dict) else None
    if not isinstance(coords, dict):
        return None
    try:
        lat = float(coords["lat"])
        lon = float(coords["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (41.5 <= lat <= 48.3 and -90.6 <= lon <= -82.0):
        log.warn(f"[museums] Wikipedia coords outside Michigan for {title!r}: {lat},{lon}")
        return None
    return lon, lat


def _enrich_from_wikipedia_active(landmarks: list[Landmark], active: list[dict]) -> int:
    """Fill missing description / subtype / URL from Wikipedia Active rows by name."""
    by_key: dict[str, dict] = {}
    for row in active:
        key = _name_key(row.get("name"))
        if key:
            by_key[key] = row
    enriched = 0
    for lm in landmarks:
        row = by_key.get(_name_key(lm.name))
        if not row:
            # Fall back to fuzzy name match against Active list (small).
            row = next((r for r in active if _name_similar(lm.name, r["name"])), None)
        if not row:
            continue
        changed = False
        if not lm.description and row.get("summary"):
            lm.description = row["summary"]
            lm.attributes["description_source"] = "Wikipedia"
            lm.attributes["description_license"] = config.WIKIPEDIA_TEXT_LICENSE
            changed = True
        if (not lm.subtype or lm.subtype == "Museum") and row.get("type"):
            lm.subtype = row["type"]
            changed = True
        if not lm.official_url and row.get("url"):
            lm.official_url = row["url"]
            changed = True
        if not lm.city and row.get("location"):
            lm.city = row["location"]
            changed = True
        srcs = list(lm.attributes.get("museum_sources") or [lm.source])
        if SOURCE_WP not in srcs and changed:
            srcs.append(SOURCE_WP)
            lm.attributes["museum_sources"] = srcs
        if changed:
            enriched += 1
    if enriched:
        log.info(f"[museums] enriched {enriched} records from Wikipedia Active text")
    return enriched


def _drop_defunct(records: list[Landmark], defunct_keys: set[str]) -> list[Landmark]:
    kept = []
    for lm in records:
        key = _name_key(lm.name)
        if key and key in defunct_keys:
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
            _absorb_museum(primary, records[i])
        merged.append(primary)
    return merged


def _absorb_museum(primary: Landmark, other: Landmark) -> None:
    srcs = list(primary.attributes.get("museum_sources") or [primary.source])
    for s in (other.attributes.get("museum_sources") or [other.source]):
        if s not in srcs:
            srcs.append(s)
    primary.attributes["museum_sources"] = srcs
    if not primary.description and other.description:
        primary.description = other.description
        for k in ("description_source", "description_license"):
            if other.attributes.get(k):
                primary.attributes[k] = other.attributes[k]
    if not primary.image_url and other.image_url:
        primary.image_url = other.image_url
        primary.image_credit = other.image_credit
        primary.image_license = other.image_license
    if not primary.official_url and other.official_url:
        primary.official_url = other.official_url
    if not primary.city and other.city:
        primary.city = other.city
    if not primary.address and other.address:
        primary.address = other.address
    if not primary.subtype or primary.subtype == "Museum":
        if other.subtype and other.subtype != "Museum":
            primary.subtype = other.subtype
    for key in (
        "imls_mid", "imls_discipline", "wikidata_qid",
        "geocode_query", "geocode_precision", "geocode_via",
    ):
        if key not in primary.attributes and other.attributes.get(key):
            primary.attributes[key] = other.attributes[key]


def _name_key(name: str | None) -> str:
    tokens = _tokens(name or "")
    return " ".join(sorted(tokens))


def _tokens(name: str) -> set[str]:
    name = _NORM_RE.sub(" ", (name or "").lower())
    return {t for t in name.split() if t and t not in _STOPWORDS}


def _name_similar(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    if union and inter / union >= 0.5:
        return True
    return ta <= tb or tb <= ta


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
        url = None
        if href:
            if href.startswith("/wiki/") and "redlink" not in href:
                url = "https://en.wikipedia.org" + href.split("?", 1)[0]
            elif href.startswith("http"):
                url = href
        self.active.append({
            "name": name,
            "location": location,
            "type": mtype or None,
            "summary": summary or None,
            "url": url,
        })
