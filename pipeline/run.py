"""Pipeline orchestrator. Run: python -m pipeline.run [--no-enrich] [--geocode-museums] [--verbose]"""
from __future__ import annotations

import argparse
import sys
import time

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, enrich, facts, heritage, licensing, log, outputs, progress, report, stats, urls
from .dedupe import merge
from .schema import Landmark, stamp_location_quality
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


def run(*, do_enrich: bool = True, geocode_museums: bool = False) -> dict:
    start = time.time()
    stats.reset()
    log_path = log.start_run()
    outputs.ensure_dirs()
    previous_index = report.read_index_snapshot()

    options = {
        "enrich": do_enrich,
        "geocode_museums": geocode_museums,
        "nps_api": bool(config.NPS_API_KEY),
    }
    stages = progress.plan_stages(do_enrich=do_enrich, geocode_museums=geocode_museums)
    progress.start(stages, options, log_path=str(log_path))

    all_records: list[Landmark] = []
    raw_counts: dict[str, int] = {}

    def _fetch_source(item):
        name, fn = item
        t0 = time.time()
        try:
            records = fn()
            if not records:
                stats.note_source_zero(name)
            return name, records, time.time() - t0, None
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
            stats.note_source_failed(name, exc)
            stats.note_source_zero(name)
            return name, [], time.time() - t0, exc

    progress.begin("fetch")
    total_sources = len(SOURCES)
    done_sources = 0
    with ThreadPoolExecutor(max_workers=config.SOURCE_WORKERS) as pool:
        futures = [pool.submit(_fetch_source, item) for item in SOURCES]
        for fut in as_completed(futures):
            name, records, elapsed, err = fut.result()
            done_sources += 1
            raw_counts[name] = len(records)
            all_records.extend(records)
            if err is not None:
                log.error(log.fmt(
                    "fetch", f"[{name}] fetch failed: {err}",
                    idx=done_sources, total=total_sources,
                ))
            else:
                log.info(log.fmt(
                    "fetch",
                    f"[{name}] fetched {len(records)} records in {elapsed:.1f}s",
                    idx=done_sources, total=total_sources,
                ))

    if not all_records:
        raise SystemExit("No records fetched from any source; aborting.")

    if geocode_museums:
        progress.begin("fetch:museum-geocode")
        extra = museums.geocode_leftovers()
        if extra:
            museum_recs = [lm for lm in all_records if lm.category == "museum"]
            others = [lm for lm in all_records if lm.category != "museum"]
            all_records = others + museums.absorb_geocoded(museum_recs, extra)
            raw_counts["Museums"] = sum(1 for lm in all_records if lm.category == "museum")

    if do_enrich:
        progress.begin("enrich:wikipedia")
        if enrich.wikimedia_reachable():
            log.info("[enrich] fetching Wikipedia summaries for state parks...")
            e = enrich.enrich_state_parks(all_records)
            log.info(f"[enrich] enriched {e} state parks")
            progress.begin("enrich:commons")
            log.info("[enrich] resolving Commons image licenses (batched)...")
            n = enrich.resolve_commons_licenses(all_records)
            log.info(f"[enrich] resolved {n} image licenses")
        else:
            stats.enrich_skipped = "unreachable"
            log.warn(
                "[enrich] SKIPPED: Wikimedia API not reachable from this environment "
                "(re-run where commons.wikimedia.org / en.wikipedia.org are accessible)"
            )
            progress.skip("Wikimedia unreachable")
            progress.begin("enrich:commons")
            progress.skip("Wikimedia unreachable")
    else:
        stats.enrich_skipped = "flag"
        log.info("[enrich] skipped (--no-enrich)")
        progress.skip("--no-enrich")

    progress.begin("dedupe")
    log.info("[dedupe] merging cross-source duplicates...")
    merged, clusters = merge(all_records)
    stats.merged_clusters = clusters
    log.info(f"[dedupe] {len(all_records)} -> {len(merged)} records ({clusters} clusters merged)")
    for lm in merged:
        urls.sanitize_landmark(lm)

    collisions = _ensure_unique_ids(merged)
    stats.id_collisions = collisions
    if collisions:
        log.warn(
            f"[ids] disambiguated {collisions} records sharing a source id "
            "(e.g. multi-point NRHP listings)"
        )

    progress.begin("enrich:heritage")
    log.info("[heritage] fetching Wikidata heritage designations...")
    n_heritage = heritage.apply(merged)
    log.info(f"[heritage] attached {n_heritage} designation rows")

    progress.begin("counties")
    log.info("[counties] backfilling counties from coordinates...")
    filled = enrich.fill_missing_counties(merged)
    stats.counties_filled = filled
    log.info(f"[counties] filled {filled} missing counties")

    progress.begin("license")
    log.info("[license] stripping images without a known license...")
    stripped = licensing.strip_unlicensed_images(merged)
    stats.images_stripped = stripped
    if stripped:
        log.warn(f"[license] omitted {stripped} images (unspecified or disallowed license)")

    for lm in merged:
        q = stamp_location_quality(lm)
        stats.location_quality[q] += 1
        facts.finalize(lm)

    progress.begin("output")
    log.info("[output] writing geojson / csv / kml / app data / overlays...")
    outputs.write_geojson(merged)
    outputs.write_csv(merged)
    outputs.write_kml(merged)
    _, details = outputs.write_app_data(merged)
    outputs.write_overlays(merged)
    log.info(f"[output] wrote {details} detail files")

    progress.begin("report")
    log.info("[report] building data report...")
    changes = report.diff_index(previous_index, merged)
    rep = report.build(
        merged, raw_counts, clusters,
        images_stripped=stripped,
        changes=changes,
        options=options,
    )
    rep["log_counts"] = log.counts()
    json_path, md_path = report.write(rep)
    log.info(f"[report] {md_path}")

    progress.finish()
    log.info(f"[done] {len(merged)} records in {time.time() - start:.1f}s")
    summary = report.stdout_summary(rep, log_line=log.summary_line())
    print(summary, flush=True)
    path = log.log_path()
    if path is not None:
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(summary)
                if not summary.endswith("\n"):
                    fh.write("\n")
        except OSError:
            pass
    log.info(log.summary_line())
    return rep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Michigan landmarks dataset.")
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="skip post-fetch Wikipedia/Commons enrichment (state-park summaries and image licenses)",
    )
    parser.add_argument(
        "--geocode-museums",
        action="store_true",
        help=(
            "Nominatim-geocode Wikipedia Active museum leftovers not already in "
            "Wikidata/IMLS (slow, 429-prone; not for routine rebuilds)"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="also print [debug] lines to stdout (debug is always written to the log file)",
    )
    args = parser.parse_args(argv)
    log.set_verbose(args.verbose)
    geocode_museums = bool(args.geocode_museums or config.MUSEUM_GEOCODE)
    config.set_museum_geocode(geocode_museums)
    run(do_enrich=not args.no_enrich, geocode_museums=geocode_museums)
    return 0


if __name__ == "__main__":
    sys.exit(main())
