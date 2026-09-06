"""Pipeline orchestrator. Run: python -m pipeline.run [--no-enrich]"""
from __future__ import annotations

import argparse
import sys
import time

from concurrent.futures import ThreadPoolExecutor

from . import config, enrich, licensing, log, outputs, report
from .dedupe import merge
from .schema import Landmark
from .sources import lighthouses, markers, museums, nps, nrhp, state_parks

SOURCES = [
    ("MI-DNR-Markers", markers.fetch),
    ("MI-DNR-StateParks", state_parks.fetch),
    ("NRHP", nrhp.fetch),
    ("Lighthouses", lighthouses.fetch),
    ("NPS", nps.fetch),
    ("Museums", museums.fetch),
]


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
    log.reset()
    outputs.ensure_dirs()

    all_records: list[Landmark] = []
    raw_counts: dict[str, int] = {}

    def _fetch_source(item):
        name, fn = item
        t0 = time.time()
        try:
            records = fn()
            log.info(f"[{name}] fetched {len(records)} records in {time.time() - t0:.1f}s")
            return name, records
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
            log.error(f"[{name}] fetch failed: {exc}")
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
            log.info("[enrich] fetching Wikipedia summaries for state parks...")
            e = enrich.enrich_state_parks(all_records)
            log.info(f"[enrich] enriched {e} state parks")
            log.info("[enrich] resolving Commons image licenses (batched)...")
            n = enrich.resolve_commons_licenses(all_records)
            log.info(f"[enrich] resolved {n} image licenses")
        else:
            log.warn(
                "[enrich] SKIPPED: Wikimedia API not reachable from this environment "
                "(re-run where commons.wikimedia.org / en.wikipedia.org are accessible)"
            )

    log.info("[dedupe] merging cross-source duplicates...")
    merged, clusters = merge(all_records)
    log.info(f"[dedupe] {len(all_records)} -> {len(merged)} records ({clusters} clusters merged)")

    collisions = _ensure_unique_ids(merged)
    if collisions:
        log.warn(
            f"[ids] disambiguated {collisions} records sharing a source id "
            "(e.g. multi-point NRHP listings)"
        )

    log.info("[region] backfilling counties from coordinates...")
    filled = enrich.fill_missing_counties(merged)
    for lm in merged:
        lm.region = config.region_for_county(lm.county)
    regioned = sum(1 for lm in merged if lm.region)
    log.info(f"[region] filled {filled} counties; {regioned}/{len(merged)} records have a region")
    missing_region = len(merged) - regioned
    if missing_region:
        log.warn(f"[region] {missing_region} records still lack a region")

    log.info("[license] stripping images without a known license...")
    stripped = licensing.strip_unlicensed_images(merged)
    if stripped:
        log.warn(f"[license] omitted {stripped} images (unspecified or disallowed license)")

    log.info("[output] writing geojson / csv / kml / app data / overlays...")
    outputs.write_geojson(merged)
    outputs.write_csv(merged)
    outputs.write_kml(merged)
    _, details = outputs.write_app_data(merged)
    outputs.write_overlays(merged)
    log.info(f"[output] wrote {details} detail files")

    log.info("[report] building data report...")
    rep = report.build(merged, raw_counts, clusters, images_stripped=stripped)
    rep["log_counts"] = log.counts()
    json_path, md_path = report.write(rep)
    log.info(f"[report] {md_path}")

    log.info(f"[done] {len(merged)} records in {time.time() - start:.1f}s")
    log.info(log.summary_line())
    return rep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Michigan landmarks dataset.")
    parser.add_argument("--no-enrich", action="store_true", help="skip Wikipedia/Commons enrichment")
    args = parser.parse_args(argv)
    run(do_enrich=not args.no_enrich)
    return 0


if __name__ == "__main__":
    sys.exit(main())
