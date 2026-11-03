"""Tier 2: the container installs a hash-locked set that covers every declared runtime dependency."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _name(spec: str) -> str:
    return re.split(r"[<>=!~;\[ ]", spec.strip(), maxsplit=1)[0].lower().replace("_", "-")


class TestDependencyLock(unittest.TestCase):
    def setUp(self):
        self.lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
        self.pins = {
            m.group(1).lower().replace("_", "-"): m.group(2)
            for m in re.finditer(r"^([A-Za-z0-9_.\-]+)==([^\s;\\]+)", self.lock, re.M)
        }

    def test_every_requirement_is_pinned(self):
        declared = [
            _name(line)
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        missing = [n for n in declared if n not in self.pins]
        self.assertEqual(missing, [], "Regenerate requirements.lock (command at its top)")

    def test_every_pin_has_a_hash(self):
        blocks = re.split(r"\n(?=[A-Za-z0-9])", self.lock)
        unhashed = [b.split("==")[0] for b in blocks if "==" in b and "--hash=sha256:" not in b]
        self.assertEqual(unhashed, [])

    def test_dockerfile_installs_only_the_lock_with_hashes(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("--require-hashes -r requirements.lock", dockerfile)
        self.assertNotIn("requirements.txt", dockerfile)


if __name__ == "__main__":
    unittest.main()
