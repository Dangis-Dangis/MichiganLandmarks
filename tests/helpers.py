"""Repo-root import path for unittest discover from tests/."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.schema import Landmark  # noqa: E402


def landmark(**kwargs) -> Landmark:
    defaults = dict(
        id="x:y:z",
        name="Test Place",
        category="museum",
        latitude=42.3,
        longitude=-83.7,
    )
    defaults.update(kwargs)
    return Landmark(**defaults)
