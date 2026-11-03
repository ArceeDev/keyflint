"""Tier 2: landing/console stay truthful (vector count, Go SDK) and in sync (v1.2)."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = (ROOT / "docs" / "index.html", ROOT / "app" / "presentation" / "static" / "index.html")
SCRIPTS = (ROOT / "docs" / "app.js", ROOT / "app" / "presentation" / "static" / "app.js")


def _main(html: str) -> str:
    # Footers differ on purpose (Pages links legal pages, the gateway links /docs).
    return html[html.index("<main"):html.index("<footer")]


class TestLandingV12(unittest.TestCase):
    def test_vector_count_matches_suite(self):
        n = len(json.loads((ROOT / "sdks" / "vectors" / "vectors.json").read_text(encoding="utf-8"))["vectors"])
        for page in PAGES:
            counts = {int(m) for m in re.findall(r"(\d+) vectores", page.read_text(encoding="utf-8"))}
            self.assertEqual(counts, {n}, page)

    def test_go_sdk_generator_and_pricing_cleanup(self):
        for page in PAGES:
            html = page.read_text(encoding="utf-8")
            self.assertIn("go get github.com/ArceeDev/keyflint/sdks/go-verify@v1.1.0", html)
            self.assertIn('data-tab="go-offline"', html)
            for el in ('id="genLang"', 'id="genCredits"', 'id="genPubKey"', 'id="genOutput"',
                       'id="btnNodesList"', 'id="portalWelcome"'):
                self.assertIn(el, html)
            pricing = html[html.index('id="pricing-section"'):html.index('id="portal-section"')]
            self.assertNotIn("/api/v1/billing/checkout", pricing)
            self.assertNotIn("BEGIN IMMEDIATE", html)

    def test_pages_and_console_bodies_and_scripts_in_sync(self):
        a, b = (_main(p.read_text(encoding="utf-8")) for p in PAGES)
        self.assertEqual(a, b)
        self.assertEqual(SCRIPTS[0].read_bytes(), SCRIPTS[1].read_bytes())

    def test_snippets_use_real_sdk_api(self):
        js = SCRIPTS[0].read_text(encoding="utf-8")
        self.assertNotIn("createMcpWrapper", js)
        self.assertIn("createKeyFlint", js)


if __name__ == "__main__":
    unittest.main()
