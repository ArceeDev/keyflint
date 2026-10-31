"""Conformance tests against sdks/vectors/vectors.json (shared with the npm package)."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from keyforge_verify import verify_license

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE.parents[1] / "vectors" / "vectors.json").read_text(encoding="utf-8"))
KEYS = DATA["keys"]
BY_NAME = {v["name"]: v for v in DATA["vectors"]}
BACKEND_VALIDATOR = HERE.parents[2] / "app" / "infrastructure" / "security" / "offline_validator.py"
VENDORED = HERE.parent / "src" / "keyforge_verify" / "_validator.py"


class TestVectors(unittest.TestCase):
    def test_all_vectors_both_engines(self) -> None:
        for v in DATA["vectors"]:
            keys = v["public_keys"][0] if len(v["public_keys"]) == 1 else v["public_keys"]
            for pure in (False, True):
                with self.subTest(vector=v["name"], pure_python=pure):
                    r = verify_license(v["token"], keys, now=v["now"], machine_id=v["machine_id"],
                                       domain=v["domain"], force_pure_python=pure)
                    self.assertEqual((r.valid, r.error), (v["expected"]["valid"], v["expected"]["error"]))


class TestKeyRing(unittest.TestCase):
    def test_legacy_token_with_kid_map(self) -> None:
        v = BY_NAME["ring_legacy_token_old_key"]
        r = verify_license(v["token"], {"k2": KEYS["k2"], "legacy": KEYS["k1"]}, now=v["now"])
        self.assertTrue(r)
        self.assertEqual(r.key_id, "legacy")

    def test_kid_selects_key(self) -> None:
        v = BY_NAME["ring_kid_token_new_key"]
        r = verify_license(v["token"], {"legacy": KEYS["k1"], "k2": KEYS["k2"]}, now=v["now"])
        self.assertEqual((r.valid, r.key_id, r.payload["kid"]), (True, "k2", "k2"))

    def test_untrusted_kid_rejected(self) -> None:
        v = BY_NAME["ring_kid_token_new_key"]
        self.assertEqual(verify_license(v["token"], {"legacy": KEYS["k1"]}, now=v["now"]).error,
                         "ERR_SIGNATURE_TAMPERED")

    def test_empty_ring(self) -> None:
        v = BY_NAME["valid_basic"]
        for keys in ("", [], {}):
            self.assertEqual(verify_license(v["token"], keys, now=v["now"]).error, "ERR_INVALID_PUBLIC_KEY")
        self.assertEqual(verify_license("", [], now=v["now"]).error, "ERR_EMPTY_TOKEN")

    def test_expired_reported_from_matching_key(self) -> None:
        v = BY_NAME["expired"]
        self.assertEqual(verify_license(v["token"], [KEYS["k2"], KEYS["k1"]], now=v["now"]).error,
                         "ERR_LICENSE_EXPIRED")


@unittest.skipUnless(BACKEND_VALIDATOR.is_file(), "backend not present")
class TestNoDrift(unittest.TestCase):
    def test_vendored_validator_matches_backend(self) -> None:
        digest = lambda p: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()  # noqa: E731
        self.assertEqual(digest(VENDORED), digest(BACKEND_VALIDATOR),
                         "Re-copy app/infrastructure/security/offline_validator.py into _validator.py")


if __name__ == "__main__":
    unittest.main()
