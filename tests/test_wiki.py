from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from urllib.parse import unquote

import helpers  # noqa: F401

ROOT = helpers.ROOT
WIKI = ROOT / "docs"
CATALOG = WIKI / "index.json"
LEGAL_HTML = ROOT / "legal.html"
DEV = WIKI / "dev"

_MD_LINK = re.compile(r"!?\[(?:[^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_HREF = re.compile(r'(?:src|href)="([^"]+)"', re.I)

_REQUIRED_LEGAL_IDS = ("unofficial", "privacy", "sources", "disclaimer", "software")
_SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "app:")


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _resolve(from_file: Path, href: str) -> Path | None:
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    if href.startswith(_SKIP_SCHEMES) or href.startswith("app:"):
        return None
    path, _, _frag = href.partition("#")
    if not path:
        return None
    return (from_file.parent / unquote(path)).resolve()


class WikiCatalogTests(unittest.TestCase):
    def test_catalog_pages_exist(self):
        data = _catalog()
        pages = data.get("pages")
        self.assertIsInstance(pages, list)
        self.assertTrue(pages)
        ids = []
        for page in pages:
            pid = page["id"]
            ids.append(pid)
            rel = page["file"]
            path = (WIKI / rel).resolve()
            self.assertTrue(path.is_file(), f"missing {rel} for page {pid}")
            try:
                path.relative_to(DEV)
            except ValueError:
                pass
            else:
                self.fail(f"Help catalog must not include docs/dev: {rel}")
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("legal", ids)
        self.assertIn("changelog", ids)
        self.assertIn("home", ids)
        self.assertIn("roadmap", ids)
        self.assertIn("ios", ids)

    def test_legal_html_section_ids(self):
        text = LEGAL_HTML.read_text(encoding="utf-8")
        for sid in _REQUIRED_LEGAL_IDS:
            self.assertIn(f'id="{sid}"', text)

    def test_legal_md_heading_slugs(self):
        text = (WIKI / "LEGAL.md").read_text(encoding="utf-8")
        for heading in ("## Unofficial", "## Privacy", "## Sources", "## Disclaimer", "## Software"):
            self.assertIn(heading, text)

    def test_relative_links_resolve(self):
        data = _catalog()
        files = [WIKI / "README.md"]
        for page in data["pages"]:
            files.append((WIKI / page["file"]).resolve())
        files.extend(sorted(WIKI.glob("*.md")))
        files.extend(sorted((WIKI / "roadmap").glob("*.md")))
        seen = set()
        missing = []
        for path in files:
            if path in seen or not path.is_file():
                continue
            # Changelog keeps historical paths on purpose (additive corrections).
            if path.name == "CHANGELOG.md":
                continue
            seen.add(path)
            raw = path.read_text(encoding="utf-8")
            hrefs = _MD_LINK.findall(raw)
            if path.suffix.lower() in {".html", ".htm"}:
                hrefs.extend(_HTML_HREF.findall(raw))
            for href in hrefs:
                if href.startswith(_SKIP_SCHEMES):
                    continue
                target = _resolve(path, href)
                if target is None:
                    continue
                try:
                    target.relative_to(ROOT)
                except ValueError:
                    continue
                if not target.exists():
                    missing.append(f"{path.relative_to(ROOT)} -> {href}")
        self.assertEqual(missing, [], "broken relative wiki links:\n" + "\n".join(missing))

    def test_asset_svgs_exist(self):
        self.assertTrue((WIKI / "assets" / "chrome.svg").is_file())
        self.assertTrue((WIKI / "assets" / "offline.svg").is_file())

    def test_app_protocol_is_not_the_only_path(self):
        started = (WIKI / "getting-started.md").read_text(encoding="utf-8")
        using = (WIKI / "using-the-app.md").read_text(encoding="utf-8")
        combined = started + using
        self.assertIn("(app:filters)", combined)
        self.assertIn("Filters", combined)
        self.assertIn("Near me", combined)
        self.assertIn("[Open Filters](app:filters)", started + using)
        self.assertRegex(combined, r"☰|Filters")
        self.assertIn("[Legal & Privacy](LEGAL.md", started + using + (WIKI / "home.md").read_text(encoding="utf-8"))

    def test_build_info_versions(self):
        info = json.loads((WIKI / "build-info.json").read_text(encoding="utf-8"))
        pkg = json.loads((ROOT / "mobile" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(info["app_version"], pkg["version"])
        self.assertTrue(info["pipeline_version"])
        self.assertTrue(info["maplibre_version"])

    def test_ios_roadmap_page_linked(self):
        roadmap = (WIKI / "roadmap.md").read_text(encoding="utf-8")
        ios = (WIKI / "roadmap" / "ios.md").read_text(encoding="utf-8")
        self.assertIn("roadmap/ios.md", roadmap)
        self.assertIn("$99", roadmap)
        self.assertIn("Mac / Xcode", roadmap)
        self.assertIn("WKWebView", roadmap)
        self.assertIn("Capacitor", ios)
        self.assertIn("## Mac and Xcode", ios)
        self.assertIn("## Apple Developer Program", ios)
        self.assertIn("## No sideload APK analog", ios)
        self.assertIn("## App Review", ios)
        self.assertIn("## MapLibre in WKWebView", ios)
        self.assertIn("## Same app, two stores", ios)

    def test_dev_handbooks_exist_outside_help_copy(self):
        self.assertTrue((DEV / "DEVELOP.md").is_file())
        self.assertTrue((DEV / "PLAYSTORE.md").is_file())
        self.assertFalse((WIKI / "DEVELOP.md").exists())
        self.assertFalse((WIKI / "PLAYSTORE.md").exists())


if __name__ == "__main__":
    unittest.main()
