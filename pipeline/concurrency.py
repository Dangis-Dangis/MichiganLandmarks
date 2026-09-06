"""Tiny thread-pool helper for I/O-bound work (network fetches).

Results are returned aligned to the input order. Per-item exceptions are captured
and returned as None by default so one failure never aborts the batch.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def map_threaded(
    fn: Callable[[T], R],
    items: Iterable[T],
    workers: int,
    swallow: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[R | None]:
    items = list(items)
    if not items:
        return []
    workers = max(1, min(workers, len(items)))
    total = len(items)

    def _safe(item: T) -> R | None:
        try:
            return fn(item)
        except Exception as exc:  # noqa: BLE001 - best-effort batch work
            if swallow:
                from . import log
                log.get_logger(__name__).warning(f"threaded task failed: {exc!r}")
                return None
            raise

    results: list[R | None] = [None] * total
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_safe, item): i for i, item in enumerate(items)}
        done = 0
        for fut in as_completed(futures):
            idx = futures[fut]
            results[idx] = fut.result()
            done += 1
            if on_progress:
                on_progress(done, total)
    return results
