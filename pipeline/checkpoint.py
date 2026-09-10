"""Gzip JSON checkpoint of the in-memory landmark list between stages."""
from __future__ import annotations

import gzip
import json
from dataclasses import fields
from typing import Any

from . import config
from .schema import Landmark

_FIELD_NAMES = {f.name for f in fields(Landmark)}


def checkpoint_path():
    return config.CACHE_DIR / "checkpoint.json.gz"


def landmark_from_dict(data: dict[str, Any]) -> Landmark:
    kwargs = {k: v for k, v in data.items() if k in _FIELD_NAMES}
    return Landmark(**kwargs)


def save(
    *,
    stage: str,
    records: list[Landmark],
    raw_counts: dict[str, int],
    options: dict,
) -> None:
    path = checkpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": stage,
        "raw_counts": raw_counts,
        "options": options,
        "records": [lm.to_dict() for lm in records],
    }
    blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    path.write_bytes(gzip.compress(blob, compresslevel=6))


def load() -> dict[str, Any]:
    path = checkpoint_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"no checkpoint at {path}; run with --until first"
        )
    payload = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    raw = payload.get("records") or []
    records = [landmark_from_dict(row) for row in raw if isinstance(row, dict)]
    return {
        "stage": payload.get("stage"),
        "raw_counts": payload.get("raw_counts") or {},
        "options": payload.get("options") or {},
        "records": records,
    }
