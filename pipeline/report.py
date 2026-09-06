"""Generate the data report - the decision gate for the app-delivery choice.

Emits data/data_report.json (machine-readable) and data/DATA_REPORT.md (human).
Covers: per-category counts, field completeness, image availability + licenses,
cross-source dedup overlap, fallbacks, change-vs-previous, and output file sizes.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import config, stats
from .schema import Landmark

_COMPLETENESS_FIELDS = [
    "description", "image_url", "official_url", "source_url", "address", "year", "county",
]
_HISTORY_CAP = 50
_MOVE_M = 25.0


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def read_index_snapshot() -> list[dict]:
    path = config.DATA_DIR / "landmarks.index.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("landmarks") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def diff_index(previous: list[dict], landmarks: list[Landmark]) -> dict:
    prev = {str(r.get("id")): r for r in previous if isinstance(r, dict) and r.get("id")}
    cur = {lm.id: lm for lm in landmarks}
    added = sorted(id_ for id_ in cur if id_ not in prev)
    removed = sorted(id_ for id_ in prev if id_ not in cur)
    moved: list[str] = []
    renamed: list[str] = []
    category_changed: list[str] = []
    for id_, lm in cur.items():
        old = prev.get(id_)
        if not old:
            continue
        try:
            dist = _haversine_m(
                float(old["latitude"]), float(old["longitude"]),
                lm.latitude, lm.longitude,
            )
        except (KeyError, TypeError, ValueError):
            dist = 0.0
        if dist > _MOVE_M:
            moved.append(id_)
        if (old.get("name") or "") != lm.name:
            renamed.append(id_)
        if (old.get("category") or "") != lm.category:
            category_changed.append(id_)
    prev_by_cat = Counter(str(r.get("category") or "") for r in prev.values())
    cur_by_cat = Counter(lm.category for lm in landmarks)
    cats = sorted(set(prev_by_cat) | set(cur_by_cat))
    return {
        "added": len(added),
        "removed": len(removed),
        "moved": len(moved),
        "renamed": len(renamed),
        "category_changed": len(category_changed),
        "net_total": len(cur) - len(prev),
        "per_category_delta": {
            cat: cur_by_cat.get(cat, 0) - prev_by_cat.get(cat, 0) for cat in cats if cat
        },
        "had_previous": bool(previous),
    }


def build(
    landmarks: list[Landmark],
    raw_counts: dict[str, int],
    merged_clusters: int,
    *,
    images_stripped: int = 0,
    changes: dict | None = None,
    options: dict | None = None,
) -> dict:
    total = len(landmarks)
    by_cat = Counter(lm.category for lm in landmarks)

    completeness = {}
    for cat in config.CATEGORIES:
        items = [lm for lm in landmarks if lm.category == cat]
        if not items:
            continue
        completeness[cat] = {
            "count": len(items),
            **{
                f: _pct(sum(1 for lm in items if getattr(lm, f)), len(items))
                for f in _COMPLETENESS_FIELDS
            },
        }

    with_image = sum(1 for lm in landmarks if lm.image_url)
    license_breakdown = Counter(
        (lm.image_license or "unspecified") for lm in landmarks if lm.image_url
    )

    overlap_tags = Counter()
    for lm in landmarks:
        for t in lm.tags:
            if t.startswith("also_"):
                overlap_tags[t] += 1

    sizes = {}
    if config.DATA_DIR.exists():
        for p in sorted(config.DATA_DIR.rglob("*")):
            if p.is_file():
                sizes[str(p.relative_to(config.DATA_DIR)).replace("\\", "/")] = p.stat().st_size

    details_total = sum(s for k, s in sizes.items() if k.startswith("details/"))
    details_files = sum(1 for k in sizes if k.startswith("details/"))
    index_bytes = sizes.get("landmarks.index.json", 0)

    ui_shell_bytes = 0
    ui_shell_files = 0
    for rel in ("index.html", "app.js", "styles.css", "legal.html", "manifest.webmanifest"):
        p = config.ROOT / rel
        if p.is_file():
            ui_shell_bytes += p.stat().st_size
            ui_shell_files += 1
    icons_dir = config.ROOT / "icons"
    if icons_dir.is_dir():
        for p in icons_dir.rglob("*"):
            if p.is_file() and p.suffix != ".py":
                ui_shell_bytes += p.stat().st_size
                ui_shell_files += 1

    unspecified = license_breakdown.get("unspecified", 0)
    snap = stats.snapshot()

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "total_records": total,
        "raw_counts_by_source": raw_counts,
        "merged_clusters": merged_clusters,
        "counts_by_category": dict(by_cat),
        "field_completeness_pct": completeness,
        "images": {
            "records_with_image": with_image,
            "records_with_image_pct": _pct(with_image, total),
            "license_breakdown": dict(license_breakdown),
            "unspecified_licenses": unspecified,
            "omitted_at_build": images_stripped,
        },
        "cross_source_overlap": dict(overlap_tags),
        "output_sizes_bytes": sizes,
        "details_summary": {"files": details_files, "total_bytes": details_total},
        "bundled_landmark_data": {
            "index_bytes": index_bytes,
            "details_bytes": details_total,
            "details_files": details_files,
            "total_bytes": index_bytes + details_total,
        },
        "ui_shell": {
            "files": ui_shell_files,
            "total_bytes": ui_shell_bytes,
        },
        "options": options or {},
        "fallbacks": snap,
        "changes_since_last_run": changes or {"had_previous": False},
    }


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


def _fallbacks_md(fb: dict) -> list[str]:
    lines: list[str] = []
    a = lines.append
    a("## Failures and fallbacks")
    a("")
    failed = fb.get("source_fetch_failed") or {}
    if failed:
        for src, err in failed.items():
            a(f"- source fetch failed: {src} ({err})")
    else:
        a("- source fetch failed: none")
    zero = fb.get("source_returned_zero") or []
    a(f"- sources returning 0 records: {', '.join(zero) if zero else 'none'}")
    a(f"- NPS path: {fb.get('nps_via') or 'unknown'}")
    skipped = fb.get("enrich_skipped")
    if skipped == "flag":
        a("- Wikimedia enrich: skipped (`--no-enrich`)")
    elif skipped == "unreachable":
        a("- Wikimedia enrich: skipped (API unreachable)")
    else:
        a("- Wikimedia enrich: ran")
    a(f"- images omitted (unlicensed): {fb.get('images_stripped', 0)}")
    a(f"- museum leftovers uncovered (no geocode this run): {fb.get('museum_leftovers_uncovered', 0)}")
    a(
        f"- museum leftover geocode: article={fb.get('museum_geocode_article', 0)}, "
        f"name={fb.get('museum_geocode_name', 0)}, "
        f"locality={fb.get('museum_geocode_locality', 0)}, "
        f"unplaced={fb.get('museum_geocode_unplaced', 0)}, "
        f"429 abort remaining={fb.get('museum_geocode_429_abort', 0)}"
    )
    a(f"- Wikipedia coordinate upgrades: {fb.get('museum_coord_upgrades', 0)}")
    a(f"- Wikipedia coordinate skips (name mismatch): {fb.get('museum_coord_skips_name_mismatch', 0)}")
    a(f"- cross-source merge clusters: {fb.get('merged_clusters', 0)}")
    a(f"- intra-museum merges: {fb.get('museum_intra_merges', 0)}")
    a(f"- counties filled from coordinates: {fb.get('counties_filled', 0)}")
    a(f"- id collisions disambiguated: {fb.get('id_collisions', 0)}")
    lq = fb.get("location_quality") or {}
    a(
        f"- location quality: site={lq.get('site', 0)}, "
        f"name={lq.get('name', 0)}, locality={lq.get('locality', 0)}"
    )
    a("")
    return lines


def _changes_md(ch: dict) -> list[str]:
    lines: list[str] = []
    a = lines.append
    a("## Changes since last run")
    a("")
    if not ch.get("had_previous"):
        a("- no previous `landmarks.index.json` to compare")
        a("")
        return lines
    a(f"- added: {ch.get('added', 0)}")
    a(f"- removed: {ch.get('removed', 0)}")
    a(f"- moved (over {_MOVE_M:.0f} m): {ch.get('moved', 0)}")
    a(f"- renamed: {ch.get('renamed', 0)}")
    a(f"- category changed: {ch.get('category_changed', 0)}")
    a(f"- net total: {ch.get('net_total', 0):+d}")
    deltas = ch.get("per_category_delta") or {}
    for cat, n in deltas.items():
        if n:
            a(f"- {cat} delta: {n:+d}")
    a("")
    return lines


def stdout_summary(report: dict, *, log_line: str) -> str:
    """Same figures as the markdown fallbacks/changes blocks, for the end of the run."""
    opts = report.get("options") or {}
    body = [ln for ln in _fallbacks_md(report.get("fallbacks") or {}) if ln.startswith("- ")]
    ch_body = [
        ln for ln in _changes_md(report.get("changes_since_last_run") or {})
        if ln.startswith("- ")
    ]
    lines = [
        "",
        "=== pipeline summary ===",
        f"total records: {report.get('total_records')}",
        (
            "options: "
            f"enrich={'on' if opts.get('enrich') else 'off'}  "
            f"nps_api={'on' if opts.get('nps_api') else 'off'}  "
            f"geocode_museums={'on' if opts.get('geocode_museums') else 'off'}"
        ),
        "fallbacks:",
        *body,
        "changes:",
        *ch_body,
        log_line,
        "=== end summary ===",
        "",
    ]
    return "\n".join(lines)


def _history_paths() -> tuple[Path, Path]:
    return config.DATA_DIR / "data_history.json", config.DATA_DIR / "DATA_HISTORY.md"


def append_history(report: dict) -> None:
    json_path, md_path = _history_paths()
    rows: list[dict] = []
    if json_path.is_file():
        try:
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                rows = loaded
        except (OSError, json.JSONDecodeError):
            rows = []
    fb = report.get("fallbacks") or {}
    lq = fb.get("location_quality") or {}
    ch = report.get("changes_since_last_run") or {}
    logc = report.get("log_counts") or {}
    rows.append({
        "generated": report.get("generated"),
        "total_records": report.get("total_records"),
        "added": ch.get("added", 0) if ch.get("had_previous") else None,
        "removed": ch.get("removed", 0) if ch.get("had_previous") else None,
        "moved": ch.get("moved", 0) if ch.get("had_previous") else None,
        "quality_site": lq.get("site", 0),
        "quality_name": lq.get("name", 0),
        "quality_locality": lq.get("locality", 0),
        "warn": logc.get("warn", 0),
        "error": logc.get("error", 0),
    })
    rows = rows[-_HISTORY_CAP:]
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Pipeline run history",
        "",
        f"Latest {len(rows)} of up to {_HISTORY_CAP} runs.",
        "",
        "| Generated (UTC) | Total | Added | Removed | Moved | site/name/locality | Warn | Error |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in reversed(rows):
        added = "—" if r.get("added") is None else r.get("added")
        removed = "—" if r.get("removed") is None else r.get("removed")
        moved = "—" if r.get("moved") is None else r.get("moved")
        q = f"{r.get('quality_site', 0)}/{r.get('quality_name', 0)}/{r.get('quality_locality', 0)}"
        lines.append(
            f"| {r.get('generated', '')} | {r.get('total_records', '')} | "
            f"{added} | {removed} | {moved} | {q} | {r.get('warn', 0)} | {r.get('error', 0)} |"
        )
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def write(report: dict) -> tuple[Path, Path]:
    json_path = config.DATA_DIR / "data_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    a = lines.append
    a("# Michigan Landmarks - Data Report")
    a("")
    a(f"Generated: {report['generated']}")
    a("")
    a(f"**Total records (after merge): {report['total_records']}**")
    a("")
    bundled = report.get("bundled_landmark_data") or {}
    if bundled:
        a(
            f"**Bundled landmark data (in the APK):** {_human_bytes(bundled.get('total_bytes', 0))} "
            f"— {bundled.get('details_files', 0)} detail files + `landmarks.index.json`"
        )
        a("")
        a(
            "Map tiles and overlay CSV/KML/GeoJSON are not included. "
            "The finished APK is larger (Capacitor / WebView)."
        )
        a("")
        ui = report.get("ui_shell") or {}
        if ui:
            a(
                f"- UI shell (html/js/css/legal/icons): {_human_bytes(ui.get('total_bytes', 0))} "
                f"({ui.get('files', 0)} files)"
            )
            a("")
    opts = report.get("options") or {}
    if opts:
        a("## Run options")
        a("")
        a(f"- enrich: {'on' if opts.get('enrich') else 'off'}")
        a(f"- NPS API key: {'on' if opts.get('nps_api') else 'off'}")
        a(f"- geocode museums: {'on' if opts.get('geocode_museums') else 'off'}")
        a("")
    a("## Raw counts by source (before merge)")
    a("")
    for src, n in report["raw_counts_by_source"].items():
        a(f"- {src}: {n}")
    a(f"- merged duplicate clusters: {report['merged_clusters']}")
    a("")
    a("## Records by category")
    a("")
    for cat, n in report["counts_by_category"].items():
        a(f"- {cat}: {n}")
    a("")
    lines.extend(_fallbacks_md(report.get("fallbacks") or {}))
    lines.extend(_changes_md(report.get("changes_since_last_run") or {}))
    a("## Field completeness (% present, by category)")
    a("")
    a("| Category | Count | description | image | official_url | source_url | address | year | county |")
    a("|---|---|---|---|---|---|---|---|---|")
    for cat, c in report["field_completeness_pct"].items():
        a(f"| {cat} | {c['count']} | {c['description']}% | {c['image_url']}% | "
          f"{c['official_url']}% | {c['source_url']}% | {c['address']}% | "
          f"{c['year']}% | {c['county']}% |")
    a("")
    a("## Images")
    a("")
    img = report["images"]
    a(f"- Records with an image: {img['records_with_image']} ({img['records_with_image_pct']}%)")
    omitted = img.get("omitted_at_build", 0)
    if omitted:
        a(f"- Images omitted at build (no known license): {omitted}")
    a("- License breakdown:")
    for lic, n in img["license_breakdown"].items():
        a(f"  - {lic}: {n}")
    unspecified = img.get("unspecified_licenses", 0)
    if unspecified:
        a(f"- **Warning:** {unspecified} image(s) still have unspecified licenses (re-run enrichment or review pipeline).")
    else:
        a("- All retained images have a known license.")
    a("")
    a("## Cross-source overlap (merged places)")
    a("")
    if report["cross_source_overlap"]:
        for tag, n in report["cross_source_overlap"].items():
            a(f"- {tag}: {n}")
    else:
        a("- none detected")
    a("")
    a("## Output file sizes")
    a("")
    for name, size in report["output_sizes_bytes"].items():
        if name.startswith("details/"):
            continue
        a(f"- {name}: {_human_bytes(size)}")
    ds = report["details_summary"]
    a(f"- details/ ({ds['files']} files): {_human_bytes(ds['total_bytes'])}")
    a("")
    log_counts = report.get("log_counts") or {}
    if log_counts:
        a("## Pipeline log totals")
        a("")
        a(f"- info: {log_counts.get('info', 0)}")
        a(f"- warn: {log_counts.get('warn', 0)}")
        a(f"- error: {log_counts.get('error', 0)}")
        a(f"- debug: {log_counts.get('debug', 0)}")
        a("")

    md_path = config.DATA_DIR / "DATA_REPORT.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    append_history(report)
    return json_path, md_path
