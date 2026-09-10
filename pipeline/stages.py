"""Stage names, skip/until/from validation, and --help listing."""
from __future__ import annotations

STAGE_ORDER = [
    "fetch",
    "fetch:museum-geocode",
    "enrich:wikipedia",
    "enrich:commons",
    "dedupe",
    "enrich:heritage",
    "counties",
    "license",
    "output",
    "report",
]

UNSAFE_SKIP = frozenset({"license", "dedupe"})
SKIPPABLE = frozenset({
    "enrich:wikipedia",
    "enrich:commons",
    "enrich:heritage",
    "counties",
    "fetch:museum-geocode",
})

SOURCE_NAMES = (
    "MI-DNR-Markers",
    "MI-DNR-StateParks",
    "NRHP",
    "Lighthouses",
    "NPS",
    "Museums",
)


class StageError(ValueError):
    """Invalid --skip / --until / --from / --sources combination."""


def parse_csv_flag(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_skip(value: str | None) -> set[str]:
    names = parse_csv_flag(value)
    unknown = [n for n in names if n not in STAGE_ORDER]
    if unknown:
        raise StageError(
            "unknown --skip stage(s): " + ", ".join(unknown)
            + ". Known: " + ", ".join(STAGE_ORDER)
        )
    unsafe = [n for n in names if n in UNSAFE_SKIP]
    if unsafe:
        raise StageError(
            "refusing to skip " + ", ".join(unsafe)
            + " (would produce broken ids or unlicensed images)"
        )
    not_skippable = [n for n in names if n not in SKIPPABLE]
    if not_skippable:
        raise StageError(
            "cannot --skip " + ", ".join(not_skippable)
            + ". Optional stages: " + ", ".join(sorted(SKIPPABLE))
        )
    return set(names)


def apply_convenience_skips(
    skip: set[str],
    *,
    skip_wikipedia: bool = False,
    skip_commons: bool = False,
    skip_nominatim_geocode: bool = False,
) -> set[str]:
    """Fold dedicated skip flags into the stage skip set."""
    out = set(skip)
    if skip_wikipedia:
        out.add("enrich:wikipedia")
    if skip_commons:
        out.add("enrich:commons")
    if skip_nominatim_geocode:
        out.add("fetch:museum-geocode")
    return out


def _require_known(name: str, flag: str) -> str:
    if name not in STAGE_ORDER:
        raise StageError(
            f"unknown {flag} stage {name!r}. Known: " + ", ".join(STAGE_ORDER)
        )
    return name


def parse_until(value: str | None) -> str | None:
    if not value:
        return None
    return _require_known(value, "--until")


def parse_from(value: str | None) -> str | None:
    if not value:
        return None
    name = _require_known(value, "--from")
    if name == "fetch":
        return name
    return name


def parse_sources(value: str | None) -> list[str] | None:
    names = parse_csv_flag(value)
    if not names:
        return None
    lookup = {n.lower(): n for n in SOURCE_NAMES}
    out: list[str] = []
    unknown: list[str] = []
    for raw in names:
        canon = lookup.get(raw.lower())
        if canon is None:
            unknown.append(raw)
        elif canon not in out:
            out.append(canon)
    if unknown:
        raise StageError(
            "unknown --sources name(s): " + ", ".join(unknown)
            + ". Known: " + ", ".join(SOURCE_NAMES)
        )
    return out


def predecessor(stage: str, planned: list[str]) -> str | None:
    if stage not in planned:
        return None
    idx = planned.index(stage)
    return planned[idx - 1] if idx > 0 else None
