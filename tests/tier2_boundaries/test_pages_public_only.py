"""Tier 2: GitHub Pages (docs/ -> keyflint.dev) only publishes the public site.

Internal docs (leads, ops runbooks, legal drafts) once leaked through Pages; this keeps them out.
"""

from __future__ import annotations

import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"
ALLOWED_SUFFIXES = {".html", ".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".ico", ".txt", ".xml", ".webmanifest"}
ALLOWED_NAMES = {"CNAME", ".nojekyll"}


class TestPagesPublicOnly(unittest.TestCase):
    def test_docs_has_no_internal_folders(self):
        for name in ("commercial", "ops", "legal"):
            self.assertFalse((DOCS / name).exists(), f"docs/{name} would be published on keyflint.dev")

    def test_docs_only_contains_public_web_assets(self):
        offenders = [
            str(p.relative_to(DOCS))
            for p in DOCS.rglob("*")
            if p.is_file() and p.name not in ALLOWED_NAMES and p.suffix.lower() not in ALLOWED_SUFFIXES
        ]
        self.assertEqual(offenders, [], "Non-web files under docs/ are published by GitHub Pages")

    def test_no_lead_lists_in_docs(self):
        hits = [str(p.relative_to(DOCS)) for p in DOCS.rglob("*") if p.is_file() and "lead" in p.name.lower()]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
