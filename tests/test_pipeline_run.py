from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import helpers
from pipeline import checkpoint, config, enrich, log, outputs, progress, run as run_mod, stages, stats
from pipeline.schema import Landmark


def _one() -> Landmark:
    return helpers.landmark(
        id="museum:test:1",
        name="Test Museum",
        category="museum",
        latitude=42.3,
        longitude=-83.7,
        source="Wikidata",
        source_id="1",
    )


class StageFlagTests(unittest.TestCase):
    def test_skip_license_refused(self):
        with self.assertRaises(stages.StageError):
            stages.parse_skip("license")
        with self.assertRaises(stages.StageError):
            stages.parse_skip("dedupe")

    def test_skip_counties_ok(self):
        self.assertEqual(stages.parse_skip("counties"), {"counties"})

    def test_plan_omits_skipped(self):
        planned = progress.plan_stages(
            do_enrich=False, geocode_museums=False, skip={"counties", "enrich:heritage"},
        )
        self.assertNotIn("counties", planned)
        self.assertNotIn("enrich:heritage", planned)
        self.assertIn("license", planned)

    def test_plan_default_includes_geocode_and_wikipedia(self):
        planned = progress.plan_stages(do_enrich=True, geocode_museums=True)
        self.assertIn("fetch:museum-geocode", planned)
        self.assertIn("enrich:wikipedia", planned)
        self.assertIn("enrich:commons", planned)

    def test_convenience_skips(self):
        skip = stages.apply_convenience_skips(
            set(),
            skip_wikipedia=True,
            skip_commons=True,
            skip_nominatim_geocode=True,
        )
        self.assertEqual(
            skip,
            {"enrich:wikipedia", "enrich:commons", "fetch:museum-geocode"},
        )
        planned = progress.plan_stages(
            do_enrich=False, geocode_museums=False, skip=skip,
        )
        self.assertNotIn("fetch:museum-geocode", planned)
        self.assertNotIn("enrich:wikipedia", planned)
        self.assertNotIn("enrich:commons", planned)

    def test_main_skip_license_exits(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                run_mod.main(["--skip", "license"])
        self.assertEqual(ctx.exception.code, 2)
        text = err.getvalue()
        self.assertIn("refusing to skip license", text)
        self.assertNotIn("usage:", text.lower())

    def test_main_rejects_old_opt_in_flags(self):
        for flag in ("--no-enrich", "--geocode-museums", "--verbose"):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    run_mod.main([flag])
            self.assertNotEqual(ctx.exception.code, 0)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                run_mod.main(["--outputs", "all"])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_quiet_and_silent_are_exclusive(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                run_mod.main(["--quiet", "--silent"])
        self.assertNotEqual(ctx.exception.code, 0)


class PipelineRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        data = root / "data"
        data.mkdir()
        (data / "details").mkdir()
        (data / "overlay").mkdir()
        cache = root / "cache"
        cache.mkdir()
        self._dirs = {
            "DATA_DIR": config.DATA_DIR,
            "DETAILS_DIR": config.DETAILS_DIR,
            "OVERLAY_DIR": config.OVERLAY_DIR,
            "CACHE_DIR": config.CACHE_DIR,
            "CACHE_READ": config.CACHE_READ,
        }
        config.DATA_DIR = data
        config.DETAILS_DIR = data / "details"
        config.OVERLAY_DIR = data / "overlay"
        config.CACHE_DIR = cache
        config.CACHE_READ = True
        self.data = data
        stats.reset()
        config.set_museum_geocode(True)
        log.set_console("verbose")

    def tearDown(self):
        log.reset()
        log.set_console("verbose")
        config.set_museum_geocode(True)
        for key, value in self._dirs.items():
            setattr(config, key, value)

    def _run(self, **kwargs):
        lm = _one()

        def fetch():
            return [helpers.landmark(
                id="museum:test:1",
                name="Test Museum",
                category="museum",
                latitude=42.3,
                longitude=-83.7,
                source="Wikidata",
                source_id="1",
            )]

        kw = dict(
            do_enrich=False,
            geocode_museums=False,
            skip={"counties", "enrich:heritage"},
        )
        kw.update(kwargs)
        sink = io.StringIO()
        with patch.object(run_mod, "SOURCES", [("Museums", fetch)]):
            with patch.object(enrich, "fill_missing_counties", side_effect=AssertionError("counties")):
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    return run_mod.run(**kw)

    def test_until_fetch_does_not_write_details(self):
        self._run(until="fetch")
        self.assertEqual(list(self.data.joinpath("details").glob("*.json")), [])
        self.assertFalse((self.data / "landmarks.kml").exists())
        ck = checkpoint.load()
        self.assertEqual(ck["stage"], "fetch")
        self.assertEqual(len(ck["records"]), 1)

    def test_default_skips_gis_exports(self):
        self._run()
        self.assertTrue((self.data / "landmarks.index.json").is_file())
        self.assertTrue(list(self.data.joinpath("details").glob("*.json")))
        self.assertFalse((self.data / "landmarks.kml").exists())
        self.assertFalse((self.data / "landmarks.geojson").exists())

    def test_export_gis_writes_kml(self):
        self._run(export_gis=True)
        self.assertTrue((self.data / "landmarks.kml").is_file())
        self.assertTrue((self.data / "landmarks.geojson").is_file())

    def test_output_dir_writes_elsewhere(self):
        other = Path(self.tmp.name) / "elsewhere"
        self._run(output_dir=other)
        self.assertTrue((other / "landmarks.index.json").is_file())
        self.assertTrue(list(other.joinpath("details").glob("*.json")))
        self.assertFalse((self.data / "landmarks.index.json").exists())

    def test_checkpoint_resume(self):
        self._run(until="dedupe")
        n = len(checkpoint.load()["records"])
        self._run(from_stage="license")
        self.assertEqual(n, 1)
        self.assertTrue((self.data / "landmarks.index.json").is_file())

    def test_skip_counties_not_called(self):
        self._run()

    def test_silent_writes_nothing_to_stdout(self):
        log.set_console("silent")

        def fetch():
            return [helpers.landmark(
                id="museum:test:1",
                name="Test Museum",
                category="museum",
                latitude=42.3,
                longitude=-83.7,
                source="Wikidata",
                source_id="1",
            )]

        buf = io.StringIO()
        with patch.object(run_mod, "SOURCES", [("Museums", fetch)]):
            with patch.object(enrich, "fill_missing_counties", side_effect=AssertionError("counties")):
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    run_mod.run(
                        do_enrich=False,
                        geocode_museums=False,
                        skip={"counties", "enrich:heritage"},
                    )
        self.assertEqual(buf.getvalue(), "")


class IncrementalDetailsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = Path(self.tmp.name)
        details = data / "details"
        details.mkdir()
        self._old = (config.DATA_DIR, config.DETAILS_DIR)
        config.DATA_DIR = data
        config.DETAILS_DIR = details
        stats.reset()

    def tearDown(self):
        config.DATA_DIR, config.DETAILS_DIR = self._old

    def test_second_write_skips_unchanged(self):
        lm = _one()
        outputs.write_app_data([lm])
        stats.reset()
        outputs.write_app_data([lm])
        self.assertEqual(stats.details_skipped_unchanged, 1)


if __name__ == "__main__":
    unittest.main()
