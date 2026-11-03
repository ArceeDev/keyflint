"""Tier 2: crawl/SEO assets on keyflint.dev stay valid and consistent with the landing."""

from __future__ import annotations

import json
import re
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"
SITE = "https://keyflint.dev/"


class TestSeoAssets(unittest.TestCase):
    def test_robots_points_to_sitemap(self):
        self.assertIn(f"Sitemap: {SITE}sitemap.xml", (DOCS / "robots.txt").read_text(encoding="utf-8"))

    def test_sitemap_urls_exist_in_docs(self):
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [e.text for e in ET.parse(DOCS / "sitemap.xml").getroot().findall("s:url/s:loc", ns)]
        self.assertIn(SITE, locs)
        for loc in locs:
            rel = loc.removeprefix(SITE) or "index.html"
            self.assertTrue((DOCS / rel).is_file(), f"sitemap lists missing page {loc}")

    def test_every_html_page_is_in_sitemap_and_has_canonical_or_is_legal(self):
        sitemap = (DOCS / "sitemap.xml").read_text(encoding="utf-8")
        for page in DOCS.rglob("*.html"):
            rel = page.relative_to(DOCS).as_posix()
            url = SITE if rel == "index.html" else SITE + rel
            self.assertIn(f"<loc>{url}</loc>", sitemap, f"{rel} missing from sitemap.xml")

    def test_json_ld_offers_match_visible_prices(self):
        html = (DOCS / "index.html").read_text(encoding="utf-8")
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        self.assertEqual(len(blocks), 1)
        data = json.loads(blocks[0])
        self.assertEqual(data["@type"], "SoftwareApplication")
        visible = set(re.findall(r'class="tier-price">\$(\d+)', html))
        offered = {o["price"] for o in data["offers"] if o["price"] != "0"}
        self.assertEqual(offered, visible, "JSON-LD prices drifted from the pricing cards")

    def test_security_txt_not_expiring_soon(self):
        txt = (DOCS / ".well-known" / "security.txt").read_text(encoding="utf-8")
        self.assertIn("Contact: mailto:", txt)
        expires = datetime.fromisoformat(re.search(r"^Expires: (.+)$", txt, re.M).group(1).replace("Z", "+00:00"))
        self.assertGreater(expires, datetime.now(timezone.utc) + timedelta(days=30),
                           "Renew docs/.well-known/security.txt Expires (RFC 9116)")

    def test_nojekyll_publishes_well_known(self):
        self.assertTrue((DOCS / ".nojekyll").is_file())


if __name__ == "__main__":
    unittest.main()
