"""Pipeline orchestrator. Run: python -m pipeline.run [--no-enrich]"""
from __future__ import annotations

import argparse
import sys
import time

from concurrent.futures import ThreadPoolExecutor

from . import config, enrich, licensing, outputs, report
from .dedupe import merge
from .schema import Landmark
from .sources import lighthouses, markers, nps, nrhp, state_parks

SOURCES = [
    ("MI-DNR-Markers", markers.fetch),
    ("MI-DNR-StateParks", state_parks.fetch),
    ("NRHP", nrhp.fetch),
    ("Lighthouses", lighthouses.fetch),
    ("NPS", nps.fetch),
]


def _log(msg: str) -> None:
    print(msg, flush=True)


def _ensure_unique_ids(records: list[Landmark]) -> int:
    """Guarantee globally unique ids so index entries map 1:1 to detail files.

    A few NRHP reference numbers cover multiple distinct points (e.g. a multi-site
    listing), which the dedupe step rightly keeps separate; suffix the collisions.
    """
    seen: dict[str, int] = {}
    fixed = 0
    for lm in records:
        if lm.id not in seen:
            seen[lm.id] = 1
            continue
        seen[lm.id] += 1
        lm.id = f"{lm.id}-{seen[lm.id]}"
        fixed += 1
    return fixed


def run(do_enrich: bool = True) -> dict:
    start = time.time()
    outputs.ensure_dirs()

    all_records: list[Landmark] = []
    raw_counts: dict[str, int] = {}

    def _fetch_source(item):
        name, fn = item
        t0 = time.time()
        try:
            records = fn()
            _log(f"[{name}] fetched {len(records)} records in {time.time() - t0:.1f}s")
            return name, records
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
            _log(f"[{name}] ERROR: {exc}")
            return name, []

    # Sources are independent network calls -> fetch them concurrently.
    with ThreadPoolExecutor(max_workers=config.SOURCE_WORKERS) as pool:
        for name, records in pool.map(_fetch_source, SOURCES):
            raw_counts[name] = len(records)
            all_records.extend(records)

    if not all_records:
        raise SystemExit("No records fetched from any source; aborting.")

    if do_enrich:
        if enrich.wikimedia_reachable():
            _log("[enrich] fetching Wikipedia summaries for state parks...")
            e = enrich.enrich_state_parks(all_records)
            _log(f"[enrich] enriched {e} state parks")
            _log("[enrich] resolving Commons image licenses (batched)...")
            n = enrich.resolve_commons_licenses(all_records)
            _log(f"[enrich] resolved {n} image licenses")
        else:
            _log("[enrich] SKIPPED: Wikimedia API not reachable from this environment "
                 "(re-run where commons.wikimedia.org / en.wikipedia.org are accessible)")

    _log("[dedupe] merging cross-source duplicates...")
    merged, clusters = merge(all_records)
    _log(f"[dedupe] {len(all_records)} -> {len(merged)} records ({clusters} clusters merged)")

    collisions = _ensure_unique_ids(merged)
    if collisions:
        _log(f"[ids] disambiguated {collisions} records sharing a source id "
             "(e.g. multi-point NRHP listings)")

    _log("[region] backfilling counties from coordinates...")
    filled = enrich.fill_missing_counties(merged)
    for lm in merged:
        lm.region = config.region_for_county(lm.county)
    regioned = sum(1 for lm in merged if lm.region)
    _log(f"[region] filled {filled} counties; {regioned}/{len(merged)} records have a region")

    _log("[license] stripping images without a known license...")
    stripped = licensing.strip_unlicensed_images(merged)
    if stripped:
        _log(f"[license] omitted {stripped} images (unspecified or disallowed license)")

    _log("[output] writing geojson / csv / kml / app data / overlays...")
    outputs.write_geojson(merged)
    outputs.write_csv(merged)
    outputs.write_kml(merged)
    _, details = outputs.write_app_data(merged)
    outputs.write_overlays(merged)
    _log(f"[output] wrote {details} detail files")

    _log("[report] building data report...")
    rep = report.build(merged, raw_counts, clusters, images_stripped=stripped)
    json_path, md_path = report.write(rep)
    _log(f"[report] {md_path}")

    _log(f"[done] {len(merged)} records in {time.time() - start:.1f}s")
    return rep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Michigan landmarks dataset.")
    parser.add_argument("--no-enrich", action="store_true", help="skip Wikipedia/Commons enrichment")
    args = parser.parse_args(argv)
    run(do_enrich=not args.no_enrich)
    return 0


if __name__ == "__main__":
    sys.exit(main())
