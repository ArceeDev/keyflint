"""Guards for the live Stripe Payment Links shown on the landing pages."""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = [ROOT / "docs" / "index.html", ROOT / "app" / "presentation" / "static" / "index.html"]
LINK_RE = re.compile(
    r'<a href="(https://buy\.stripe\.com/[^"]+)"[^>]*data-tier="([a-z]+)">([^<]*)</a>'
)
EXPECTED = {"indie": "($149)", "agency": "($349)", "pro": "($29/mo)", "studio": "($89/mo)"}


def _links(page: Path) -> dict[str, tuple[str, str]]:
    return {tier: (url, label) for url, tier, label in LINK_RE.findall(page.read_text("utf-8"))}


class TestPaymentLinks(unittest.TestCase):
    def test_every_tier_has_one_live_link_with_its_price(self):
        for page in PAGES:
            links = _links(page)
            self.assertEqual(set(links), set(EXPECTED), page)
            for tier, (url, label) in links.items():
                self.assertNotIn("/test_", url, f"{page}: {tier} uses a test-mode link")
                self.assertTrue(label.endswith(EXPECTED[tier]), f"{page}: {tier} label {label!r}")
            self.assertEqual(len({u for u, _ in links.values()}), 4, f"{page}: duplicated link")

    def test_pages_and_console_stay_in_sync(self):
        self.assertEqual(_links(PAGES[0]), _links(PAGES[1]))

    def test_no_test_links_or_stripe_secrets_tracked(self):
        files = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
        self.assertFalse([f for f in files if f.lower().endswith(".csv")], "CSV export tracked")
        bad = re.compile(r"buy\.stripe\.com/test_|(?:sk|rk)_live_[A-Za-z0-9]{8}|whsec_(?!unconfigured_)[A-Za-z0-9]{16}")
        hits = []
        for f in files:
            p = ROOT / f
            if p.suffix in {".png", ".ico", ".whl", ".tgz", ".pyc"} or not p.is_file():
                continue
            try:
                if bad.search(p.read_text("utf-8")):
                    hits.append(f)
            except UnicodeDecodeError:
                continue
        self.assertEqual(hits, [])
