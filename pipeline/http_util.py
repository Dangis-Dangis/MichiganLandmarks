"""Small, dependency-free HTTP helpers (stdlib only) with retry + JSON parsing.

Using urllib keeps the pipeline runnable with a bare Python install and no pip
step, which matters for a low-maintenance, rebuild-on-demand static dataset.

Wikimedia Robot policy notes (https://wikitech.wikimedia.org/wiki/Robot_policy):
- identifying User-Agent (config.USER_AGENT)
- Accept-Encoding: gzip
- honor HTTP 429 Retry-After
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import config, log, stats

_logger = log.get_logger(__name__)


def _http_cache_dir():
    return config.CACHE_DIR / "http"


def _http_cache_key(method: str, url: str, data: bytes | None) -> str:
    h = hashlib.sha256()
    h.update(method.upper().encode("utf-8"))
    h.update(b"\n")
    h.update(url.encode("utf-8"))
    if data:
        h.update(b"\n")
        h.update(data)
    return h.hexdigest()


def _cache_load(method: str, url: str, data: bytes | None) -> bytes | None:
    if not config.CACHE_READ:
        return None
    path = _http_cache_dir() / (_http_cache_key(method, url, data) + ".bin")
    if not path.is_file():
        stats.inc_cache_miss()
        return None
    try:
        body = path.read_bytes()
    except OSError:
        stats.inc_cache_miss()
        return None
    stats.inc_cache_hit()
    _logger.debug(f"http cache hit {method} {url}")
    return body


def _cache_store(method: str, url: str, data: bytes | None, body: bytes) -> None:
    directory = _http_cache_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        digest = _http_cache_key(method, url, data)
        (directory / (digest + ".bin")).write_bytes(body)
        (directory / (digest + ".json")).write_text(
            json.dumps({"method": method, "url": url}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        _logger.debug(f"http cache store failed: {exc}")


def _decode_body(resp) -> bytes:
    raw = resp.read()
    encoding = (resp.headers.get("Content-Encoding") or "").lower()
    if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    return raw


def _open(url: str, data: bytes | None = None, headers: dict[str, str] | None = None,
          timeout: float | None = None):
    req_headers = {
        "User-Agent": config.USER_AGENT,
        "Accept-Encoding": "gzip",
    }
    if headers:
        req_headers.update(headers)
    # Default Accept only when the caller did not set one.
    req_headers.setdefault("Accept", "application/json")
    req = urllib.request.Request(url, data=data, headers=req_headers)
    return urllib.request.urlopen(req, timeout=timeout or config.REQUEST_TIMEOUT)


def _retry_wait(exc: Exception, attempt: int, pause: float) -> float:
    """Seconds to sleep before the next try; honors Retry-After on HTTP 429."""
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        try:
            wait = float(retry_after) if retry_after else pause * (2 ** (attempt + 1))
        except ValueError:
            wait = pause * (2 ** (attempt + 1))
        return min(max(wait, 2.0), 120.0)
    return pause * (2 ** attempt)


_RETRYABLE_HTTP = frozenset({408, 425, 429, 500, 502, 503, 504})


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _RETRYABLE_HTTP
    return isinstance(exc, (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError))


def _close_http_error(exc: urllib.error.HTTPError) -> None:
    try:
        exc.close()
    except Exception:
        pass


def _sleep_retry(exc: Exception, attempt: int, tries: int, pause: float, url: str) -> None:
    wait = _retry_wait(exc, attempt, pause)
    _logger.debug(f"retry {attempt + 1}/{tries} after {wait:.1f}s ({exc!r}) {url}")
    time.sleep(wait)


def get_bytes(url: str, params: dict[str, Any] | None = None, *,
              headers: dict[str, str] | None = None,
              timeout: float | None = None, retries: int | None = None,
              backoff: float | None = None) -> bytes:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    tries = retries if retries is not None else config.MAX_RETRIES
    pause = backoff if backoff is not None else config.RETRY_BACKOFF
    last_err: Exception | None = None
    cached = _cache_load("GET", url, None)
    if cached is not None:
        return cached
    for attempt in range(tries):
        try:
            with _open(url, headers=headers, timeout=timeout) as resp:
                body = _decode_body(resp)
            _cache_store("GET", url, None, body)
            return body
        except urllib.error.HTTPError as exc:
            last_err = exc
            _close_http_error(exc)
            if _is_retryable(exc) and attempt < tries - 1:
                _sleep_retry(exc, attempt, tries, pause, url)
                continue
            break
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
            if attempt < tries - 1:
                _sleep_retry(exc, attempt, tries, pause, url)
                continue
            break
    raise RuntimeError(f"request failed after {tries} tries: {url}\n  -> {last_err}")


def get_text(url: str, params: dict[str, Any] | None = None, *,
             headers: dict[str, str] | None = None,
             timeout: float | None = None, retries: int | None = None,
             backoff: float | None = None) -> str:
    raw = get_bytes(
        url, params, headers=headers, timeout=timeout, retries=retries, backoff=backoff,
    )
    return raw.decode("utf-8", "replace")


def get_json(url: str, params: dict[str, Any] | None = None, *,
             headers: dict[str, str] | None = None,
             timeout: float | None = None, retries: int | None = None,
             backoff: float | None = None) -> Any:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    return _request_json(
        url, timeout=timeout, retries=retries, backoff=backoff, headers=headers,
    )


def post_json(url: str, params: dict[str, Any], *, timeout: float | None = None,
              retries: int | None = None, backoff: float | None = None) -> Any:
    data = urllib.parse.urlencode(params).encode("utf-8")
    return _request_json(
        url, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout, retries=retries, backoff=backoff,
    )


def _request_json(url: str, data: bytes | None = None, headers: dict[str, str] | None = None,
                  timeout: float | None = None, retries: int | None = None,
                  backoff: float | None = None) -> Any:
    tries = retries if retries is not None else config.MAX_RETRIES
    pause = backoff if backoff is not None else config.RETRY_BACKOFF
    last_err: Exception | None = None
    method = "POST" if data else "GET"
    cached = _cache_load(method, url, data)
    if cached is not None:
        try:
            payload = json.loads(cached.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            payload = None
        else:
            if isinstance(payload, dict) and "error" in payload and "results" not in payload:
                payload = None
            if payload is not None:
                return payload
    for attempt in range(tries):
        try:
            with _open(url, data=data, headers=headers, timeout=timeout) as resp:
                raw = _decode_body(resp).decode("utf-8", "replace")
            payload = json.loads(raw)
            # ArcGIS returns HTTP 200 with an embedded error object.
            if isinstance(payload, dict) and "error" in payload and "results" not in payload:
                err = payload["error"]
                raise RuntimeError(f"service error {err.get('code')}: {err.get('message')}")
            _cache_store(method, url, data, raw.encode("utf-8"))
            return payload
        except urllib.error.HTTPError as exc:
            last_err = exc
            _close_http_error(exc)
            if _is_retryable(exc) and attempt < tries - 1:
                _sleep_retry(exc, attempt, tries, pause, url)
                continue
            break
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            last_err = exc
            if _is_retryable(exc) and attempt < tries - 1:
                _sleep_retry(exc, attempt, tries, pause, url)
                continue
            break
    raise RuntimeError(f"request failed after {tries} tries: {url}\n  -> {last_err}")
