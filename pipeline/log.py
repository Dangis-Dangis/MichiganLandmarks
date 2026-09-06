"""Lightweight pipeline logging with levels and end-of-run tallies.

Uses stdout so `python -m pipeline.run` remains easy to follow in a terminal.
Warnings and errors are counted so a quiet-looking run still surfaces problems
in the final summary line.
"""
from __future__ import annotations

import sys
from collections import Counter

_counts: Counter[str] = Counter()


def reset() -> None:
    _counts.clear()


def _emit(level: str, msg: str) -> None:
    _counts[level] += 1
    print(f"[{level}] {msg}", flush=True, file=sys.stdout)


def info(msg: str) -> None:
    _emit("info", msg)


def warn(msg: str) -> None:
    _emit("warn", msg)


def error(msg: str) -> None:
    _emit("error", msg)


def counts() -> dict[str, int]:
    return dict(_counts)


def summary_line() -> str:
    return (
        f"log totals: info={_counts.get('info', 0)} "
        f"warn={_counts.get('warn', 0)} error={_counts.get('error', 0)}"
    )
