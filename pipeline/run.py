"""Pipeline orchestrator. Run: python -m pipeline.run --help"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import (
    checkpoint, config, enrich, facts, heritage, licensing, log, outputs,
    progress, report, stages, stats, urls,
)
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
    Collision suffixes are assigned in a stable order (lat, lon, name, source_id)
    so rebuilds do not swap which record keeps the unsuffixed id.
    """
    groups: dict[str, list[Landmark]] = {}
    for lm in records:
        groups.setdefault(lm.id, []).append(lm)
    used = {lm.id for lm in records}
    fixed = 0
    for base_id, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda lm: (
            lm.latitude, lm.longitude, lm.name or "", str(lm.source_id or ""),
        ))
        for lm in group[1:]:
            n = 2
            candidate = f"{base_id}-{n}"
            while candidate in used:
                n += 1
                candidate = f"{base_id}-{n}"
            lm.id = candidate
            used.add(candidate)
            fixed += 1
    return fixed


def _select_sources(wanted: list[str] | None):
    if not wanted:
        return list(SOURCES)
    allow = set(wanted)
    return [item for item in SOURCES if item[0] in allow]


def run(
    *,
    do_enrich: bool = True,
    geocode_museums: bool = True,
    skip: set[str] | None = None,
    until: str | None = None,
    from_stage: str | None = None,
    source_names: list[str] | None = None,
    export_gis: bool = False,
    output_dir: str | Path | None = None,
    fresh: bool = False,
) -> dict:
    start = time.time()
    stats.reset()
    skip = set(skip or ())
    if output_dir is not None:
        config.set_data_dir(output_dir)
    config.set_museum_geocode(geocode_museums)
    log_path = log.start_run()
    outputs.ensure_dirs(export_gis=export_gis)
    previous_index = report.read_index_snapshot()
    config.set_cache_read(not fresh)

    source_items = _select_sources(source_names)
    options = {
        "enrich": do_enrich,
        "geocode_museums": geocode_museums,
        "nps_api": bool(config.NPS_API_KEY),
        "export_gis": export_gis,
        "output_dir": str(config.DATA_DIR),
        "fresh": fresh,
        "skip": sorted(skip),
        "until": until,
        "from_stage": from_stage,
        "sources": [name for name, _fn in source_items],
        "sources_incomplete": source_names is not None,
    }
    planned_full = progress.plan_stages(
        do_enrich=do_enrich, geocode_museums=geocode_museums, skip=skip,
    )
    if from_stage and from_stage != "fetch":
        ck = checkpoint.load()
        pred = stages.predecessor(from_stage, planned_full)
        if ck["stage"] != pred:
            raise SystemExit(
                f"--from {from_stage} needs a checkpoint at {pred}, "
                f"found {ck['stage']!r}"
            )
        records: list[Landmark] = ck["records"]
        raw_counts: dict[str, int] = dict(ck["raw_counts"])
    else:
        records = []
        raw_counts = {}

    stage_list = progress.plan_stages(
        do_enrich=do_enrich,
        geocode_museums=geocode_museums,
        skip=skip,
        until=until,
        from_stage=from_stage,
    )
    progress.start(stage_list, options, log_path=str(log_path))
    active = set(stage_list)

    def finish_stage(name: str, current: list[Landmark]) -> bool:
        checkpoint.save(
            stage=name, records=current, raw_counts=raw_counts, options=options,
        )
        return until == name

    stopped = False

    if "fetch" in active:
        progress.begin("fetch")

        def _fetch_source(item):
            name, fn = item
            t0 = time.time()
            try:
                recs = fn()
                if not recs:
                    stats.note_source_zero(name)
                return name, recs, time.time() - t0, None
            except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
                stats.note_source_failed(name, exc)
                stats.note_source_zero(name)
                return name, [], time.time() - t0, exc

        total_sources = len(source_items)
        done_sources = 0
        fetched: dict[str, tuple[list, float, Exception | None]] = {}
        with ThreadPoolExecutor(max_workers=config.SOURCE_WORKERS) as pool:
            futures = [pool.submit(_fetch_source, item) for item in source_items]
            for fut in as_completed(futures):
                name, recs, elapsed, err = fut.result()
                fetched[name] = (recs, elapsed, err)
                done_sources += 1
                raw_counts[name] = len(recs)
                if err is not None:
                    log.error(log.fmt(
                        "fetch", f"[{name}] fetch failed: {err}",
                        idx=done_sources, total=total_sources,
                    ))
                else:
                    log.info(log.fmt(
                        "fetch",
                        f"[{name}] fetched {len(recs)} records in {elapsed:.1f}s",
                        idx=done_sources, total=total_sources,
                    ))
        records = []
        for src_name, _fn in source_items:
            records.extend(fetched[src_name][0])

        if not records:
            raise SystemExit("No records fetched from any source; aborting.")
        stopped = finish_stage("fetch", records)

    if not stopped and "fetch:museum-geocode" in active:
        progress.begin("fetch:museum-geocode")
        extra = museums.geocode_leftovers()
        if extra:
            museum_recs = [lm for lm in records if lm.category == "museum"]
            others = [lm for lm in records if lm.category != "museum"]
            records = others + museums.absorb_geocoded(museum_recs, extra)
            raw_counts["Museums"] = sum(1 for lm in records if lm.category == "museum")
        stopped = finish_stage("fetch:museum-geocode", records)

    if not stopped and "enrich:wikipedia" in active:
        progress.begin("enrich:wikipedia")
        if enrich.wikimedia_reachable():
            log.info("[enrich] fetching Wikipedia summaries for state parks...")
            e = enrich.enrich_state_parks(records)
            log.info(f"[enrich] enriched {e} state parks")
            stopped = finish_stage("enrich:wikipedia", records)
            if not stopped and "enrich:commons" in active:
                progress.begin("enrich:commons")
                log.info("[enrich] resolving Commons image licenses (batched)...")
                n = enrich.resolve_commons_licenses(records)
                log.info(f"[enrich] resolved {n} image licenses")
                stopped = finish_stage("enrich:commons", records)
        else:
            stats.enrich_skipped = "unreachable"
            log.warn(
                "[enrich] SKIPPED: Wikimedia API not reachable from this environment "
                "(re-run where commons.wikimedia.org / en.wikipedia.org are accessible)"
            )
            progress.skip("Wikimedia unreachable")
            stopped = finish_stage("enrich:wikipedia", records)
            if not stopped and "enrich:commons" in active:
                progress.begin("enrich:commons")
                progress.skip("Wikimedia unreachable")
                stopped = finish_stage("enrich:commons", records)
    elif not do_enrich:
        stats.enrich_skipped = "flag"
        log.info("[enrich] skipped (--skip-wikipedia / --skip-commons)")
    elif "enrich:wikipedia" in skip or "enrich:commons" in skip:
        stats.enrich_skipped = "flag"
        log.info("[enrich] skipped (--skip-wikipedia / --skip-commons)")

    if not stopped and "enrich:commons" in active and "enrich:wikipedia" not in active:
        progress.begin("enrich:commons")
        if enrich.wikimedia_reachable():
            log.info("[enrich] resolving Commons image licenses (batched)...")
            n = enrich.resolve_commons_licenses(records)
            log.info(f"[enrich] resolved {n} image licenses")
        else:
            progress.skip("Wikimedia unreachable")
        stopped = finish_stage("enrich:commons", records)

    if not stopped and "dedupe" in active:
        progress.begin("dedupe")
        log.info("[dedupe] merging cross-source duplicates...")
        records, clusters = merge(records)
        stats.merged_clusters = clusters
        log.info(f"[dedupe] merged to {len(records)} records ({clusters} clusters merged)")
        for lm in records:
            urls.sanitize_landmark(lm)

        collisions = _ensure_unique_ids(records)
        stats.id_collisions = collisions
        if collisions:
            log.warn(
                f"[ids] disambiguated {collisions} records sharing a source id "
                "(e.g. multi-point NRHP listings)"
            )
        records.sort(key=lambda lm: (lm.category, lm.id))
        stopped = finish_stage("dedupe", records)

    if not stopped and "enrich:heritage" in active:
        progress.begin("enrich:heritage")
        log.info("[heritage] fetching Wikidata heritage designations...")
        n_heritage = heritage.apply(records)
        log.info(f"[heritage] attached {n_heritage} designation rows")
        stopped = finish_stage("enrich:heritage", records)

    if not stopped and "counties" in active:
        progress.begin("counties")
        log.info("[counties] backfilling counties from coordinates...")
        filled = enrich.fill_missing_counties(records)
        stats.counties_filled = filled
        log.info(f"[counties] filled {filled} missing counties")
        stopped = finish_stage("counties", records)

    if not stopped and "license" in active:
        progress.begin("license")
        log.info("[license] stripping images without a known license...")
        stripped = licensing.strip_unlicensed_images(records)
        stats.images_stripped = stripped
        if stripped:
            log.warn(f"[license] omitted {stripped} images (unspecified or disallowed license)")
        for lm in records:
            q = stamp_location_quality(lm)
            stats.location_quality[q] += 1
            facts.finalize(lm)
        stopped = finish_stage("license", records)

    if not stopped and "output" in active:
        progress.begin("output")
        log.info("[output] writing app data" + (
            " + GIS exports..." if export_gis else "..."
        ))
        _, details = outputs.write_app_data(records)
        if export_gis:
            outputs.write_geojson(records)
            outputs.write_csv(records)
            outputs.write_kml(records)
            outputs.write_overlays(records)
        log.info(f"[output] wrote {details} detail files")
        stopped = finish_stage("output", records)

    if not stopped and "report" in active:
        progress.begin("report")
        log.info("[report] building data report...")
        changes = report.diff_index(previous_index, records)
        rep = report.build(
            records, raw_counts, stats.merged_clusters,
            images_stripped=stats.images_stripped,
            changes=changes,
            options=options,
        )
        rep["log_counts"] = log.counts()
        json_path, md_path = report.write(rep)
        log.info(f"[report] {md_path}")
        finish_stage("report", records)
    else:
        changes = report.diff_index(previous_index, records) if records else {}
        rep = report.build(
            records, raw_counts, stats.merged_clusters,
            images_stripped=stats.images_stripped,
            changes=changes,
            options=options,
        )
        rep["log_counts"] = log.counts()
        if until:
            log.info(f"[done] stopped after --until {until} ({len(records)} records)")

    progress.finish()
    log.info(f"[done] {len(records)} records in {time.time() - start:.1f}s")
    summary = report.stdout_summary(rep, log_line=log.summary_line())
    if log.console_mode() != "silent":
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


def _epilog() -> str:
    return (
        "A bare run writes the Android dataset under data/ (index, details, "
        "report), including leftover Nominatim and Wikipedia/Commons, and "
        "prints [debug] to stdout.\n"
        "Stages: " + ", ".join(stages.STAGE_ORDER) + "\n"
        "Optional --skip: " + ", ".join(sorted(stages.SKIPPABLE)) + "\n"
        "Sources: " + ", ".join(stages.SOURCE_NAMES)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description="Build the Michigan landmarks dataset. A bare run does every stage.",
        epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    skip_g = parser.add_argument_group(
        "skip expensive steps (default is to run them)"
    )
    skip_g.add_argument(
        "--skip-nominatim-geocode",
        action="store_true",
        help=(
            "skip leftover-museum Nominatim (slow, 429-prone). "
            "Wikipedia article coordinates still run during fetch"
        ),
    )
    skip_g.add_argument(
        "--skip-wikipedia",
        action="store_true",
        help=(
            "skip post-fetch Wikipedia summaries for state parks. "
            "Fetch-time museum Wikipedia still runs"
        ),
    )
    skip_g.add_argument(
        "--skip-commons",
        action="store_true",
        help="skip Wikimedia Commons image-license lookups",
    )
    skip_g.add_argument(
        "--skip",
        metavar="STAGE[,STAGE]",
        help="omit optional stage(s): " + ",".join(sorted(stages.SKIPPABLE)),
    )
    out_g = parser.add_argument_group(
        "dataset files (default is the Android files under data/)"
    )
    out_g.add_argument(
        "--output-dir",
        metavar="DIR",
        help="write the dataset here instead of data/ (Sync / the APK still read data/)",
    )
    out_g.add_argument(
        "--export-gis",
        action="store_true",
        help=(
            "also write GeoJSON, CSV, and KML for QGIS, Google Earth, and My Maps "
            "(not used by the Android app)"
        ),
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="ignore HTTP and Nominatim caches and refetch (new results are still stored)",
    )
    parser.add_argument(
        "--until",
        metavar="STAGE",
        help="run through STAGE (inclusive), write a checkpoint, then stop",
    )
    parser.add_argument(
        "--from",
        dest="from_stage",
        metavar="STAGE",
        help="resume from STAGE using .cache/checkpoint.json.gz",
    )
    parser.add_argument(
        "--sources",
        metavar="NAME[,NAME]",
        help="fetch only these sources (dataset is incomplete): " + ",".join(stages.SOURCE_NAMES),
    )
    console_g = parser.add_argument_group(
        "console (default is verbose: [debug] on stdout; log file is always written)"
    )
    console = console_g.add_mutually_exclusive_group()
    console.add_argument(
        "--quiet",
        action="store_true",
        help="stdout: warnings, errors, and the end-of-run summary",
    )
    console.add_argument(
        "--silent",
        action="store_true",
        help="write nothing to stdout",
    )
    args = parser.parse_args(argv)
    if args.silent:
        log.set_console("silent")
    elif args.quiet:
        log.set_console("quiet")
    else:
        log.set_console("verbose")
    try:
        skip = stages.parse_skip(args.skip)
        skip = stages.apply_convenience_skips(
            skip,
            skip_wikipedia=args.skip_wikipedia,
            skip_commons=args.skip_commons,
            skip_nominatim_geocode=args.skip_nominatim_geocode,
        )
        until = stages.parse_until(args.until)
        from_stage = stages.parse_from(args.from_stage)
        source_names = stages.parse_sources(args.sources)
    except stages.StageError as exc:
        print(f"python -m pipeline.run: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    geocode_museums = "fetch:museum-geocode" not in skip
    do_enrich = "enrich:wikipedia" not in skip or "enrich:commons" not in skip
    run(
        do_enrich=do_enrich,
        geocode_museums=geocode_museums,
        skip=skip,
        until=until,
        from_stage=from_stage,
        source_names=source_names,
        export_gis=args.export_gis,
        output_dir=args.output_dir,
        fresh=args.fresh,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
