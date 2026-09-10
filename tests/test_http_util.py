from __future__ import annotations

import email.message
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import helpers  # noqa: F401
from pipeline import config, http_util, stats


def _http_error(code: int, url: str = "https://example.test/x") -> urllib.error.HTTPError:
    hdrs = email.message.Message()
    return urllib.error.HTTPError(url, code, "err", hdrs, io.BytesIO(b""))


class _CacheDirMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old_cache = config.CACHE_DIR
        self._old_read = config.CACHE_READ
        config.CACHE_DIR = Path(self.tmp.name)
        config.CACHE_READ = True
        stats.reset()

    def tearDown(self):
        config.CACHE_DIR = self._old_cache
        config.CACHE_READ = self._old_read


class RetryTests(_CacheDirMixin, unittest.TestCase):
    def test_404_is_not_retried(self):
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            raise _http_error(404)

        with patch.object(http_util, "_open", side_effect=boom), patch.object(http_util, "time") as t:
            with self.assertRaises(RuntimeError) as ctx:
                http_util.get_json("https://example.test/x", retries=4, backoff=0.01)
            t.sleep.assert_not_called()
        self.assertEqual(calls["n"], 1)
        self.assertIn("404", str(ctx.exception))

    def test_403_is_not_retried(self):
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            raise _http_error(403)

        with patch.object(http_util, "_open", side_effect=boom):
            with self.assertRaises(RuntimeError):
                http_util.get_bytes("https://example.test/x", retries=3, backoff=0.01)
        self.assertEqual(calls["n"], 1)

    def test_500_is_retried(self):
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            raise _http_error(500)

        with patch.object(http_util, "_open", side_effect=boom), patch.object(http_util.time, "sleep"):
            with self.assertRaises(RuntimeError):
                http_util.get_json("https://example.test/x", retries=3, backoff=0.01)
        self.assertEqual(calls["n"], 3)

    def test_429_is_retried(self):
        self.assertTrue(http_util._is_retryable(_http_error(429)))
        self.assertFalse(http_util._is_retryable(_http_error(404)))


class JsonSuccessTests(_CacheDirMixin, unittest.TestCase):
    def test_parses_json(self):
        class Resp:
            headers = {"Content-Encoding": ""}

            def read(self):
                return json.dumps({"ok": True}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch.object(http_util, "_open", return_value=Resp()):
            self.assertEqual(http_util.get_json("https://example.test/x"), {"ok": True})

    def test_second_call_does_not_hit_network(self):
        calls = {"n": 0}

        class Resp:
            headers = {"Content-Encoding": ""}

            def read(self):
                return json.dumps({"ok": True}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(*a, **k):
            calls["n"] += 1
            return Resp()

        with patch.object(http_util, "_open", side_effect=opener):
            self.assertEqual(http_util.get_json("https://example.test/cache-me"), {"ok": True})
            self.assertEqual(http_util.get_json("https://example.test/cache-me"), {"ok": True})
        self.assertEqual(calls["n"], 1)
        self.assertEqual(stats.http_cache_hits, 1)

    def test_fresh_bypasses_cache_read(self):
        calls = {"n": 0}

        class Resp:
            headers = {"Content-Encoding": ""}

            def read(self):
                return json.dumps({"n": calls["n"]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(*a, **k):
            calls["n"] += 1
            return Resp()

        with patch.object(http_util, "_open", side_effect=opener):
            http_util.get_json("https://example.test/fresh")
            config.CACHE_READ = False
            http_util.get_json("https://example.test/fresh")
        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
