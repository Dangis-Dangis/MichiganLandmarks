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
CACHE_DIR = ROOT / ".cache"  # raw source responses (optional, for debugging/reruns)

USER_AGENT = "michigan-landmarks-pipeline/0.1 (personal project; contact via repo)"

# Identifying user-agent for the app UI (Nominatim policy, etc.).
APP_NAME = "MichiganLandmarks"
APP_VERSION = "1.0"
APP_USER_AGENT = f"{APP_NAME}/{APP_VERSION} (https://github.com/michigan-landmarks; personal project)"
REQUEST_TIMEOUT = 60
MAX_RETRIES = 4
RETRY_BACKOFF = 2.0  # seconds, exponential

# Concurrency + enrichment tuning. Enrichment hits Wikimedia (Commons/Wikipedia)
# with many small requests, so it runs in a thread pool and fails fast: a slow or
# throttled response is skipped rather than allowed to stall the whole build.
SOURCE_WORKERS = 5        # fetch all sources concurrently
ENRICH_WORKERS = 6        # parallel Wikipedia summaries (not Commons batches)
ENRICH_TIMEOUT = 20       # seconds per enrichment request
ENRICH_RETRIES = 3        # attempts per enrichment request (then skip)
ENRICH_BACKOFF = 1.5
# Commons imageinfo is batched to avoid 429 rate limits from per-file parallel calls.
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
)

# Single map icon key per category (used by overlay exports + app UI).
CATEGORY_ICON = {
    "lighthouse": "lighthouse",
    "historical_marker": "marker",
    "nrhp_site": "landmark",
    "state_park": "park",
    "national_park_unit": "mountain",
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

# Wikipedia REST summary endpoint (used for optional enrichment of parks).
WIKIPEDIA_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"

# NPS Data API (requires a free API key in the NPS_API_KEY environment variable).
# When the key is absent the pipeline falls back to Wikidata for Michigan NPS units.
NPS_API_BASE = "https://developer.nps.gov/api/v1"
NPS_API_KEY = os.environ.get("NPS_API_KEY", "").strip()

# Wikidata entity ids used in SPARQL queries.
WD_MICHIGAN = "Q1166"
WD_LIGHTHOUSE = "Q39715"
WD_NPS = "Q308439"  # National Park Service (operator)

# ----------------------------------------------------------------------------
# Licensing metadata (per source). Honest, real values.
# ----------------------------------------------------------------------------
DATA_LICENSE = {
    "MI-DNR-Markers": "Michigan open data (Michigan DNR; attribution requested)",
    "MI-DNR-StateParks": "Michigan open data (Michigan DNR; attribution requested)",
    "NRHP": "Public domain (U.S. Government work, NPS)",
    "Wikidata": "CC0 1.0",
    "NPS": "Public domain (U.S. Government work, NPS)",
}

# Text pulled from Wikipedia during enrichment (CC BY-SA 4.0).
WIKIPEDIA_TEXT_LICENSE = "CC BY-SA 4.0"

# ----------------------------------------------------------------------------
# Regions: each Michigan county mapped to one of 9 tourism-style regions.
# The UP is split west/east along the Marquette–Alger line.
# Region labels (display order) are exposed to the app as the region filter.
# ----------------------------------------------------------------------------
REGIONS = (
    "Western UP",
    "Eastern UP",
    "Northwest",
    "Northeast",
    "West Michigan",
    "Central",
    "East/Thumb",
    "Southwest",
    "Southeast",
)

# County -> region. Keys are normalized (uppercase, no periods) so lookups are
# robust to source variations like "St. Clair" vs "ST CLAIR".
_COUNTY_REGION_RAW = {
    "Western UP": [
        "Baraga", "Delta", "Dickinson", "Gogebic", "Houghton", "Iron", "Keweenaw",
        "Menominee", "Ontonagon",
    ],
    "Eastern UP": [
        "Alger", "Chippewa", "Luce", "Mackinac", "Marquette", "Schoolcraft",
    ],
    "Northwest": [
        "Antrim", "Benzie", "Charlevoix", "Emmet", "Grand Traverse", "Kalkaska",
        "Leelanau", "Manistee", "Missaukee", "Wexford",
    ],
    "Northeast": [
        "Alcona", "Alpena", "Cheboygan", "Crawford", "Iosco", "Montmorency",
        "Ogemaw", "Oscoda", "Otsego", "Presque Isle", "Roscommon",
    ],
    "West Michigan": [
        "Allegan", "Barry", "Ionia", "Kent", "Lake", "Mason", "Mecosta", "Montcalm",
        "Muskegon", "Newaygo", "Oceana", "Osceola", "Ottawa",
    ],
    "Central": [
        "Arenac", "Bay", "Clare", "Clinton", "Eaton", "Gladwin", "Gratiot",
        "Ingham", "Isabella", "Midland", "Saginaw", "Shiawassee",
    ],
    "East/Thumb": [
        "Genesee", "Huron", "Lapeer", "Sanilac", "St. Clair", "Tuscola",
    ],
    "Southwest": [
        "Berrien", "Branch", "Calhoun", "Cass", "Kalamazoo", "St. Joseph", "Van Buren",
    ],
    "Southeast": [
        "Hillsdale", "Jackson", "Lenawee", "Livingston", "Macomb", "Monroe",
        "Oakland", "Washtenaw", "Wayne",
    ],
}


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


def _norm_county(name: str) -> str:
    return name.upper().replace(".", "").replace(" COUNTY", "").strip()


COUNTY_REGION = {
    _norm_county(county): region
    for region, counties in _COUNTY_REGION_RAW.items()
    for county in counties
}


def region_for_county(county: str | None) -> str | None:
    if not county:
        return None
    return COUNTY_REGION.get(_norm_county(county))
