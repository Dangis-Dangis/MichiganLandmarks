"""Central configuration for the Michigan Landmarks data pipeline.

All source endpoints, output paths, category definitions, and licensing metadata
live here so the rest of the pipeline stays declarative. Every endpoint below was
verified live against the provider before being committed.
"""
from __future__ import annotations

import os
from pathlib import Path

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DETAILS_DIR = DATA_DIR / "details"
OVERLAY_DIR = DATA_DIR / "overlay"  # KML/CSV per-category (export only)
CACHE_DIR = ROOT / ".cache"  # Nominatim, HTTP bodies, logs, checkpoints, timings
CACHE_READ = True  # False when --fresh (still writes new cache entries)


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from path into os.environ if not already set.

    Existing environment variables win, so a shell-exported NPS_API_KEY still
    overrides a value in .env. Parsing is stdlib-only (no python-dotenv).
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")

# Wikimedia User-Agent policy: identifying client + contact URL, not a generic
# library default. "bot" marks this as automated dataset rebuild traffic.
# https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
_CONTACT = (
    "https://github.com/Dangis-Dangis/MichiganLandmarks; "
    "dangisdangis.dev@gmail.com"
)
USER_AGENT = f"MichiganLandmarksBot/1.0 ({_CONTACT})"

# Identifying user-agent for the app UI (Nominatim policy, etc.).
APP_NAME = "MichiganLandmarks"
APP_VERSION = "1.0"
APP_USER_AGENT = f"{APP_NAME}/{APP_VERSION} ({_CONTACT})"
REQUEST_TIMEOUT = 60
MAX_RETRIES = 4
RETRY_BACKOFF = 2.0  # seconds, exponential

# Concurrency + enrichment tuning.
# Wikimedia Robot policy (unauthenticated): REST ≤3 concurrent / <5 rps;
# Action API ≤1 concurrent / <5 rps. County fill uses the FCC API (not Wikimedia).
SOURCE_WORKERS = 5        # fetch all sources concurrently (mostly ArcGIS / SPARQL)
ENRICH_WORKERS = 3        # parallel Wikipedia REST summaries
COUNTY_WORKERS = 6        # parallel FCC county lookups
ENRICH_TIMEOUT = 20       # seconds per enrichment request
ENRICH_RETRIES = 3        # attempts per enrichment request (then skip)
ENRICH_BACKOFF = 1.5
# Commons Action API: serial batches + pause (≤1 concurrent).
COMMONS_BATCH_SIZE = 50
COMMONS_BATCH_PAUSE = 1.0  # seconds between batch requests

# ----------------------------------------------------------------------------
# Categories
# ----------------------------------------------------------------------------
CATEGORIES = (
    "lighthouse",
    "historical_marker",
    "nrhp_site",
    "state_park",
    "national_park_unit",
    "museum",
)

# Human-readable names for KML folders / overlay titles (must match the app UI).
CATEGORY_LABELS = {
    "lighthouse": "Lighthouses",
    "historical_marker": "Historical markers",
    "nrhp_site": "Historic places (NRHP)",
    "state_park": "State parks",
    "national_park_unit": "National parks",
    "museum": "Museums",
}

# Single map icon key per category (used by overlay exports + app UI).
CATEGORY_ICON = {
    "lighthouse": "lighthouse",
    "historical_marker": "marker",
    "nrhp_site": "landmark",
    "state_park": "park",
    "national_park_unit": "mountain",
    "museum": "museum",
}

# ----------------------------------------------------------------------------
# Source endpoints (verified live)
# ----------------------------------------------------------------------------
# Michigan DNR / Michigan History Center historical markers (public view).
MARKERS_LAYER = (
    "https://services3.arcgis.com/Jdnp1TjADvSDxMAX/arcgis/rest/services/"
    "Historical_Markers_Public_View/FeatureServer/0"
)

# Michigan DNR state park recreation-search points (one row per park unit).
STATE_PARKS_LAYER = (
    "https://services3.arcgis.com/Jdnp1TjADvSDxMAX/arcgis/rest/services/"
    "State_Park_Recreation_Search_Points/FeatureServer/0"
)

# National Register of Historic Places points (NPS National Geospatial Data Asset,
# served via Esri Federal). State stored as full uppercase name, e.g. 'MICHIGAN'.
NRHP_LAYER = (
    "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
    "nrhp_points_v1/FeatureServer/0"
)

# Wikidata SPARQL endpoint (for lighthouses + the no-key NPS fallback + enrichment).
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# Wikipedia REST summary endpoint (state-park enrichment; skip with --skip-wikipedia).
WIKIPEDIA_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"

# NPS Data API (requires a free API key in NPS_API_KEY, from .env or the environment).
# When the key is absent the pipeline falls back to Wikidata for Michigan NPS units.
NPS_API_BASE = "https://developer.nps.gov/api/v1"
NPS_API_KEY = os.environ.get("NPS_API_KEY", "").strip()

# Wikidata entity ids used in SPARQL queries.
WD_MICHIGAN = "Q1166"
WD_LIGHTHOUSE = "Q39715"
WD_NPS = "Q308439"  # National Park Service (operator)
WD_MUSEUM = "Q33506"

# IMLS Museum Data Files (2018 CSV ZIP) — retired snapshot, still public.
IMLS_MUSEUM_ZIP = (
    "https://www.imls.gov/sites/default/files/2018_csv_museum_data_files.zip"
)
# Public landing page for that dataset (user-facing source_url; zip stays in attributes).
IMLS_DATASET_PAGE = (
    "https://www.imls.gov/research-evaluation/data-collection/museum-data-files"
)

# Leftover museum Nominatim is on by default. `--skip-nominatim-geocode` turns it off.
MUSEUM_GEOCODE = True


def set_museum_geocode(enabled: bool) -> None:
    """Enable leftover museum Nominatim for this process (default on)."""
    global MUSEUM_GEOCODE
    MUSEUM_GEOCODE = bool(enabled)


def set_cache_read(enabled: bool) -> None:
    """When False, skip reading HTTP/Nominatim caches (`--fresh`). Writes still happen."""
    global CACHE_READ
    CACHE_READ = bool(enabled)


def set_data_dir(path: str | Path) -> None:
    """Write index, details, report (and optional GIS files) under this directory."""
    global DATA_DIR, DETAILS_DIR, OVERLAY_DIR
    DATA_DIR = Path(path).expanduser().resolve()
    DETAILS_DIR = DATA_DIR / "details"
    OVERLAY_DIR = DATA_DIR / "overlay"

# ----------------------------------------------------------------------------
# Licensing metadata (per source). Honest, real values.
# ----------------------------------------------------------------------------
DATA_LICENSE = {
    "MI-DNR-Markers": "Michigan open data (Michigan DNR; attribution requested)",
    "MI-DNR-StateParks": "Michigan open data (Michigan DNR; attribution requested)",
    "NRHP": "Public domain (U.S. Government work, NPS)",
    "Wikidata": "CC0 1.0",
    "NPS": "Public domain (U.S. Government work, NPS)",
    "IMLS": "U.S. Government work (public domain; IMLS Museum Data Files 2018)",
    "Wikipedia": "CC BY-SA 4.0",
}

# Text pulled from Wikipedia during enrichment (CC BY-SA 4.0).
WIKIPEDIA_TEXT_LICENSE = "CC BY-SA 4.0"

# Michigan's official county codes are alphabetical 1-83 (St. = "Saint" in sort).
# The historical-markers source stores this code instead of a name.
MICHIGAN_COUNTIES = (
    "Alcona", "Alger", "Allegan", "Alpena", "Antrim", "Arenac", "Baraga", "Barry",
    "Bay", "Benzie", "Berrien", "Branch", "Calhoun", "Cass", "Charlevoix",
    "Cheboygan", "Chippewa", "Clare", "Clinton", "Crawford", "Delta", "Dickinson",
    "Eaton", "Emmet", "Genesee", "Gladwin", "Gogebic", "Grand Traverse", "Gratiot",
    "Hillsdale", "Houghton", "Huron", "Ingham", "Ionia", "Iosco", "Iron", "Isabella",
    "Jackson", "Kalamazoo", "Kalkaska", "Kent", "Keweenaw", "Lake", "Lapeer",
    "Leelanau", "Lenawee", "Livingston", "Luce", "Mackinac", "Macomb", "Manistee",
    "Marquette", "Mason", "Mecosta", "Menominee", "Midland", "Missaukee", "Monroe",
    "Montcalm", "Montmorency", "Muskegon", "Newaygo", "Oakland", "Oceana", "Ogemaw",
    "Ontonagon", "Osceola", "Oscoda", "Otsego", "Ottawa", "Presque Isle", "Roscommon",
    "Saginaw", "St. Clair", "St. Joseph", "Sanilac", "Schoolcraft", "Shiawassee",
    "Tuscola", "Van Buren", "Washtenaw", "Wayne", "Wexford",
)


def county_from_code(code) -> str | None:
    try:
        n = int(str(code).strip())
    except (TypeError, ValueError):
        return None
    return MICHIGAN_COUNTIES[n - 1] if 1 <= n <= len(MICHIGAN_COUNTIES) else None
