"""Tiny thread-pool helper for I/O-bound work (network fetches).

Results are returned aligned to the input order. Per-item exceptions are captured
and returned as None by default so one failure never aborts the batch.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def map_threaded(
    fn: Callable[[T], R],
    items: Iterable[T],
    workers: int,
    swallow: bool = True,
) -> list[R | None]:
    items = list(items)
    if not items:
        return []
    workers = max(1, min(workers, len(items)))

    def _safe(item: T) -> R | None:
        try:
            return fn(item)
        except Exception:  # noqa: BLE001 - best-effort batch work
            if swallow:
                return None
            raise

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_safe, items))
