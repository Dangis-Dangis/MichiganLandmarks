"""Small, dependency-free HTTP helpers (stdlib only) with retry + JSON parsing.

Using urllib keeps the pipeline runnable with a bare Python install and no pip
step, which matters for a low-maintenance, rebuild-on-demand static dataset.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import config


def _open(url: str, data: bytes | None = None, headers: dict[str, str] | None = None,
          timeout: float | None = None):
    req_headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers)
    return urllib.request.urlopen(req, timeout=timeout or config.REQUEST_TIMEOUT)


def get_json(url: str, params: dict[str, Any] | None = None, *,
             timeout: float | None = None, retries: int | None = None,
             backoff: float | None = None) -> Any:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    return _request_json(url, timeout=timeout, retries=retries, backoff=backoff)


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
    for attempt in range(tries):
        try:
            with _open(url, data=data, headers=headers, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
            payload = json.loads(raw)
            # ArcGIS returns HTTP 200 with an embedded error object.
            if isinstance(payload, dict) and "error" in payload and "results" not in payload:
                err = payload["error"]
                raise RuntimeError(f"service error {err.get('code')}: {err.get('message')}")
            return payload
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code == 429 and attempt < tries - 1:
                retry_after = exc.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else pause * (2 ** (attempt + 1))
                except ValueError:
                    wait = pause * (2 ** (attempt + 1))
                time.sleep(min(max(wait, 2.0), 60.0))
                continue
            if attempt < tries - 1:
                time.sleep(pause * (2 ** attempt))
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            last_err = exc
            if attempt < tries - 1:
                time.sleep(pause * (2 ** attempt))
    raise RuntimeError(f"request failed after {tries} tries: {url}\n  -> {last_err}")
