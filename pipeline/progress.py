"""In-terminal stage / ETA / options banners (stderr, stdlib only)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import config

_KEEP_TIMINGS = 8  # fingerprints to retain
_HEURISTIC_S = {
    "fetch": 25.0,
    "fetch:museum-geocode": 120.0,  # overwritten when leftover count is known
    "enrich:wikipedia": 20.0,
    "enrich:commons": 30.0,
    "dedupe": 2.0,
    "enrich:heritage": 8.0,
    "counties": 15.0,
    "license": 1.0,
    "output": 8.0,
    "report": 2.0,
}

_stages: list[str] = []
_index = 0
_stage_started = 0.0
_run_started = 0.0
_options: dict[str, bool] = {}
_estimates: dict[str, float] = {}
_actual: dict[str, float] = {}
_log_path: str | None = None
_last_tick_len = 0


def _tty() -> bool:
    return bool(getattr(sys.stderr, "isatty", lambda: False)())


def _fmt_s(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = max(0.0, seconds)
    if seconds < 90:
        return f"{seconds:.0f}s"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}m{s:02d}s"


def _fingerprint(options: dict[str, bool]) -> str:
    return (
        f"enrich={int(options.get('enrich', False))},"
        f"geocode_museums={int(options.get('geocode_museums', False))},"
        f"nps_api={int(options.get('nps_api', False))}"
    )


def _timings_path() -> Path:
    return config.CACHE_DIR / "pipeline_timings.json"


def _status_path() -> Path:
    return config.CACHE_DIR / "pipeline_status.json"


def _load_timings(fp: str) -> dict[str, float]:
    path = _timings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    block = data.get(fp) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in block.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _save_timings(fp: str, actual: dict[str, float]) -> None:
    path = _timings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    data[fp] = actual
    # Drop oldest fingerprints if the file grows.
    if len(data) > _KEEP_TIMINGS:
        # Preserve insertion order; drop keys not just written.
        keys = [k for k in data if k != fp]
        for old in keys[: len(data) - _KEEP_TIMINGS]:
            data.pop(old, None)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_status(*, running: bool, extra: str | None = None) -> None:
    remaining_stage = None
    remaining_overall = None
    if _stages and 0 < _index <= len(_stages):
        name = _stages[_index - 1]
        elapsed_stage = time.monotonic() - _stage_started
        est = _estimates.get(name, 0.0)
        remaining_stage = max(0.0, est - elapsed_stage)
        rest = sum(_estimates.get(s, 0.0) for s in _stages[_index:])
        remaining_overall = remaining_stage + rest
    payload = {
        "running": running,
        "stage": _stages[_index - 1] if 0 < _index <= len(_stages) else None,
        "index": _index,
        "total": len(_stages),
        "options": dict(_options),
        "elapsed_s": round(time.monotonic() - _run_started, 1) if _run_started else 0,
        "eta_stage_s": None if remaining_stage is None else round(remaining_stage),
        "eta_overall_s": None if remaining_overall is None else round(remaining_overall),
        "log_file": _log_path,
        "extra": extra,
    }
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _banner(line: str) -> None:
    from . import log
    log.stage(line)


def plan_stages(*, do_enrich: bool, geocode_museums: bool) -> list[str]:
    stages = ["fetch"]
    if geocode_museums:
        stages.append("fetch:museum-geocode")
    if do_enrich:
        stages.extend(["enrich:wikipedia", "enrich:commons"])
    stages.extend(["dedupe", "enrich:heritage", "counties", "license", "output", "report"])
    return stages


def start(
    stages: list[str],
    options: dict[str, bool],
    *,
    log_path: str | None = None,
    geocode_leftovers: int = 0,
) -> None:
    global _stages, _index, _run_started, _options, _estimates, _actual, _log_path
    _stages = list(stages)
    _index = 0
    _run_started = time.monotonic()
    _options = dict(options)
    _actual = {}
    _log_path = log_path
    prior = _load_timings(_fingerprint(options))
    _estimates = {}
    for name in _stages:
        if name in prior:
            _estimates[name] = prior[name]
        elif name == "fetch:museum-geocode" and geocode_leftovers:
            _estimates[name] = max(8.0, geocode_leftovers * 2.0)
        else:
            _estimates[name] = _HEURISTIC_S.get(name, 10.0)

    opt = (
        f"enrich={'on' if options.get('enrich') else 'off'}  "
        f"nps_api={'on' if options.get('nps_api') else 'off'}  "
        f"geocode_museums={'on' if options.get('geocode_museums') else 'off'}"
    )
    _banner(f"[stage] options: {opt}")
    bits = [f"{n} ~{_fmt_s(_estimates[n])}" for n in _stages]
    overall = sum(_estimates.values())
    _banner(f"[stage] plan: {', '.join(bits)}  (overall ~{_fmt_s(overall)}, rough)")
    _write_status(running=True)


def _finish_current() -> None:
    if _index <= 0 or _index > len(_stages):
        return
    name = _stages[_index - 1]
    _actual[name] = time.monotonic() - _stage_started


def begin(name: str) -> None:
    global _index, _stage_started
    _finish_current()
    if name not in _stages:
        return
    _index = _stages.index(name) + 1
    _stage_started = time.monotonic()
    elapsed = time.monotonic() - _run_started
    est = _estimates.get(name, 0.0)
    rest = sum(_estimates.get(s, 0.0) for s in _stages[_index:])
    _banner(
        f"[stage] {_index}/{len(_stages)}  {name}  "
        f"this ~{_fmt_s(est)}, overall ~{_fmt_s(est + rest)} remaining  "
        f"(elapsed {_fmt_s(elapsed)})"
    )
    _write_status(running=True)


def skip(reason: str) -> None:
    _banner(f"[stage]   skipped: {reason}")
    _write_status(running=True, extra=reason)


def tick(done: int, total: int, *, label: str = "geocode") -> None:
    global _last_tick_len
    if total <= 0:
        return
    elapsed_stage = time.monotonic() - _stage_started
    rate = elapsed_stage / done if done else 0.0
    eta = rate * (total - done) if done else _estimates.get(_stages[_index - 1] if _index else "", 0.0)
    text = f"[stage]   {label} {done}/{total}  eta {_fmt_s(eta)}"
    step = 25 if total > 25 else 1
    milestone = done == 1 or done == total or done % step == 0
    if _tty():
        pad = max(0, _last_tick_len - len(text))
        sys.stderr.write("\r" + text + (" " * pad))
        sys.stderr.flush()
        _last_tick_len = len(text)
        if done >= total:
            sys.stderr.write("\n")
            sys.stderr.flush()
            _last_tick_len = 0
        if milestone:
            from . import log
            log.to_file(text)
    else:
        if milestone:
            _banner(text)
    _write_status(running=True, extra=f"{label} {done}/{total}")


def finish() -> None:
    _finish_current()
    if _tty() and _last_tick_len:
        sys.stderr.write("\n")
        sys.stderr.flush()
    elapsed = time.monotonic() - _run_started
    _banner(f"[stage] done  {len(_stages)}/{len(_stages)}  elapsed {_fmt_s(elapsed)}")
    _save_timings(_fingerprint(_options), _actual)
    _write_status(running=False)
