"""Generate the data report - the decision gate for the app-delivery choice.

Emits data/data_report.json (machine-readable) and data/DATA_REPORT.md (human).
Covers: per-category counts, field completeness, image availability + licenses,
cross-source dedup overlap, and output file sizes.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .schema import Landmark

_COMPLETENESS_FIELDS = ["description", "image_url", "official_url", "year", "county"]


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def build(
    landmarks: list[Landmark],
    raw_counts: dict[str, int],
    merged_clusters: int,
    *,
    images_stripped: int = 0,
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

    unspecified = license_breakdown.get("unspecified", 0)

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
    }


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


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
    a("## Field completeness (% present, by category)")
    a("")
    a("| Category | Count | description | image | official_url | year | county |")
    a("|---|---|---|---|---|---|---|")
    for cat, c in report["field_completeness_pct"].items():
        a(f"| {cat} | {c['count']} | {c['description']}% | {c['image_url']}% | "
          f"{c['official_url']}% | {c['year']}% | {c['county']}% |")
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

    md_path = config.DATA_DIR / "DATA_REPORT.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
