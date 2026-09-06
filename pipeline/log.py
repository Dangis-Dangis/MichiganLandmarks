"""Pipeline logging on the stdlib ``logging`` module.

Named loggers (``pipeline``, ``pipeline.stage``, ``pipeline.geocode``, …) share
one rotating per-run file. Handlers filter by level:

- **stdout:** INFO+ (DEBUG when ``--verbose``)
- **stderr:** ``pipeline.stage`` banners only (ETA / plan), not duplicated on stdout
- **file:** DEBUG+ always, including stage lines and stderr banners

``log.info`` / ``warn`` / ``error`` / ``debug`` stay as convenience wrappers.
Modules that need a dedicated logger should call ``get_logger(__name__)`` (or
accept a ``logger=`` argument).
"""
from __future__ import annotations

import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import config

_KEEP_LOGS = 10
_ROOT_NAME = "pipeline"
_STAGE_NAME = "pipeline.stage"

_counts: Counter[str] = Counter()
_log_path: Path | None = None
_verbose = False
_file_handler: logging.Handler | None = None
_stdout_handler: logging.Handler | None = None


class _BracketFormatter(logging.Formatter):
    """Stdout lines match the historic `[info] message` shape."""

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname.lower()
        if level == "warning":
            level = "warn"
        return f"[{level}] {record.getMessage()}"


class _FileFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname.lower()
        if level == "warning":
            level = "warn"
        stamp = datetime.fromtimestamp(record.created, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        return f"{stamp} [{level}] {record.name} {record.getMessage()}"


class _CountHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        level = record.levelname.lower()
        if level == "warning":
            level = "warn"
        _counts[level] += 1


class _SkipStageFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name != _STAGE_NAME and not record.name.startswith(_STAGE_NAME + ".")


class _SkipFileOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "file_only", False)


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the pipeline logger (safe to call before ``start_run``)."""
    if not name or name == _ROOT_NAME:
        return logging.getLogger(_ROOT_NAME)
    if name == _STAGE_NAME or name.startswith(_ROOT_NAME + "."):
        return logging.getLogger(name)
    if name.startswith("pipeline."):
        return logging.getLogger(name)
    # `__name__` inside this package is already `pipeline.*`.
    return logging.getLogger(name)


def log_path() -> Path | None:
    return _log_path


def verbose() -> bool:
    return _verbose


def set_verbose(enabled: bool) -> None:
    global _verbose
    _verbose = bool(enabled)
    if _stdout_handler is not None:
        _stdout_handler.setLevel(logging.DEBUG if _verbose else logging.INFO)


def reset() -> None:
    global _file_handler, _stdout_handler, _log_path
    _counts.clear()
    root = logging.getLogger(_ROOT_NAME)
    stage = logging.getLogger(_STAGE_NAME)
    seen: set[int] = set()
    for logger in (root, stage):
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            if id(handler) in seen:
                continue
            seen.add(id(handler))
            try:
                handler.close()
            except OSError:
                pass
    _file_handler = None
    _stdout_handler = None
    _log_path = None


def start_run() -> Path:
    """Reset counters, attach handlers, open a new rotating log file."""
    global _file_handler, _stdout_handler, _log_path
    reset()
    log_dir = config.CACHE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    _log_path = log_dir / f"pipeline-{stamp}.log"

    file_handler = logging.FileHandler(_log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_FileFormatter())
    _file_handler = file_handler

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG if _verbose else logging.INFO)
    stdout_handler.setFormatter(_BracketFormatter())
    stdout_handler.addFilter(_SkipStageFilter())
    _stdout_handler = stdout_handler

    count_handler = _CountHandler()
    count_handler.setLevel(logging.DEBUG)

    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(logging.DEBUG)
    root.propagate = False
    root.addHandler(file_handler)
    root.addHandler(stdout_handler)
    root.addHandler(count_handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(logging.Formatter("%(message)s"))
    stderr_handler.addFilter(_SkipFileOnlyFilter())

    stage = logging.getLogger(_STAGE_NAME)
    stage.setLevel(logging.INFO)
    stage.propagate = False
    stage.addHandler(file_handler)
    stage.addHandler(stderr_handler)

    _rotate(log_dir)
    return _log_path


def _rotate(log_dir: Path) -> None:
    logs = sorted(log_dir.glob("pipeline-*.log"), key=lambda p: p.name)
    extra = len(logs) - _KEEP_LOGS
    if extra <= 0:
        return
    for old in logs[:extra]:
        try:
            old.unlink()
        except OSError:
            pass


def fmt(component: str, msg: str, *, step: str | None = None,
        idx: int | None = None, total: int | None = None) -> str:
    """Build `[component] [step] (idx/total) msg` (step and progress optional)."""
    parts = [f"[{component}]"]
    if step:
        parts.append(f"[{step}]")
    if idx is not None and total is not None:
        parts.append(f"({idx}/{total})")
    parts.append(msg)
    return " ".join(parts)


def to_file(line: str) -> None:
    """Append a raw line to the log file only (no stdout/stderr, no level counter)."""
    logging.getLogger(_STAGE_NAME).info(line, extra={"file_only": True})


def stage(line: str) -> None:
    """Write a stage/ETA banner to stderr and the log file (not stdout)."""
    logging.getLogger(_STAGE_NAME).info(line)


def info(msg: str) -> None:
    logging.getLogger(_ROOT_NAME).info(msg)


def warn(msg: str) -> None:
    logging.getLogger(_ROOT_NAME).warning(msg)


def error(msg: str) -> None:
    logging.getLogger(_ROOT_NAME).error(msg)


def debug(msg: str) -> None:
    logging.getLogger(_ROOT_NAME).debug(msg)


def counts() -> dict[str, int]:
    return dict(_counts)


def summary_line() -> str:
    path = f"  log={_log_path}" if _log_path else ""
    bits = [
        f"info={_counts.get('info', 0)}",
        f"warn={_counts.get('warn', 0)}",
        f"error={_counts.get('error', 0)}",
        f"debug={_counts.get('debug', 0)}",
    ]
    return f"log totals: {' '.join(bits)}{path}"
