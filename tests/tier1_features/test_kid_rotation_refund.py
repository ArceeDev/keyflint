"""Tier 1: v1.1 — key rotation with `kid` and compensating refunds for metered calls."""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

from tests.conftest import BaseKeyForgeTestCase, TEST_ED25519_PUBLIC_KEY_HEX, decode_license_token

_ROTATION_ENV = ("ED25519_KID", "ED25519_RETIRED_PUBLIC_KEYS", "QUOTA_REFUND_WINDOW_SECONDS")


class TestKidRotation(BaseKeyForgeTestCase):
    def tearDown(self):
        for k in _ROTATION_ENV:
            os.environ.pop(k, None)
        os.environ["ED25519_PRIVATE_KEY_HEX"] = self._orig_priv
        os.environ["ED25519_PUBLIC_KEY_HEX"] = self._orig_pub
        from app.config import get_settings
        get_settings.cache_clear()
        super().tearDown()

    def setUp(self):
        self._orig_priv = os.environ["ED25519_PRIVATE_KEY_HEX"]
        self._orig_pub = os.environ["ED25519_PUBLIC_KEY_HEX"]
        super().setUp()

    def _rotate(self, kid: str = "k2") -> None:
        from app.config import get_settings
        from app.infrastructure.security.ed25519_signer import Ed25519Signer
        priv, pub = Ed25519Signer.generate_keypair()
        os.environ["ED25519_PRIVATE_KEY_HEX"] = priv
        os.environ["ED25519_PUBLIC_KEY_HEX"] = pub
        os.environ["ED25519_KID"] = kid
        os.environ["ED25519_RETIRED_PUBLIC_KEYS"] = TEST_ED25519_PUBLIC_KEY_HEX
        get_settings.cache_clear()

    def test_default_issuer_emits_v1_0_tokens_without_kid(self):
        data = self.issue_license_api(customer_email="nokid@acme.ai")
        _, payload, _ = decode_license_token(data["license_key"])
        self.assertNotIn("kid", payload)
        keys = self.client.get("/api/v1/licenses/public-key").json()["data"]
        self.assertEqual(keys["public_key_hex"], TEST_ED25519_PUBLIC_KEY_HEX)
        self.assertEqual(keys["keys"], [{"kid": None, "public_key_hex": TEST_ED25519_PUBLIC_KEY_HEX, "status": "active"}])
        self.assertEqual(keys["keyring"], TEST_ED25519_PUBLIC_KEY_HEX)

    def test_rotation_keeps_old_tokens_valid_and_stamps_kid(self):
        old = self.issue_license_api(customer_email="old@acme.ai")["license_key"]
        self._rotate("k2")

        new = self.issue_license_api(customer_email="new@acme.ai")["license_key"]
        _, payload, _ = decode_license_token(new)
        self.assertEqual(payload["kid"], "k2")

        for token in (old, new):
            res = self.verify_license_api(token)
            self.assertEqual(res.status_code, 200, res.text)

        data = self.client.get("/api/v1/licenses/public-key").json()["data"]
        self.assertEqual(data["kid"], "k2")
        self.assertEqual([k["status"] for k in data["keys"]], ["active", "retired"])
        self.assertTrue(data["keyring"].startswith("k2="))
        self.assertIn(f"legacy-1={TEST_ED25519_PUBLIC_KEY_HEX}", data["keyring"])

        # Published keyring is consumable by the client SDK (KEYFORGE_PUBLIC_KEYS format).
        sdk = Path(__file__).resolve().parents[2] / "sdks" / "python-verify" / "src"
        sys.path.insert(0, str(sdk))
        try:
            from keyforge_verify import verify_license
            from keyforge_verify.mcp import _parse_keys_env
            ring = _parse_keys_env(data["keyring"])
            for token in (old, new):
                self.assertTrue(verify_license(token, ring).valid, token[:20])
        finally:
            sys.path.remove(str(sdk))

    def test_signer_rejects_token_from_unknown_key(self):
        from app.infrastructure.security.ed25519_signer import Ed25519Signer
        rogue = Ed25519Signer(*Ed25519Signer.generate_keypair(), kid="k2")
        priv, pub = Ed25519Signer.generate_keypair()
        server = Ed25519Signer(priv, pub, kid="k2", retired_public_keys=f"k1={TEST_ED25519_PUBLIC_KEY_HEX}")
        ok, _, err = server.verify_token(rogue.sign_token({"tier": "pro", "license_id": "x"}))
        self.assertFalse(ok)
        self.assertEqual(err, "ERR_SIGNATURE_TAMPERED")

    def test_kid_is_bound_to_its_key(self):
        from app.infrastructure.security.ed25519_signer import Ed25519Signer
        old_priv, old_pub = Ed25519Signer.generate_keypair()
        old = Ed25519Signer(old_priv, old_pub, kid="k1")
        priv, pub = Ed25519Signer.generate_keypair()
        server = Ed25519Signer(priv, pub, kid="k2", retired_public_keys=f"k1={old_pub}")
        # Retired key k1 signing a token that claims kid "k2" must not verify.
        forged = Ed25519Signer(old_priv, old_pub).sign_token({"tier": "pro", "license_id": "x", "kid": "k2"})
        self.assertEqual(server.verify_token(forged)[2], "ERR_SIGNATURE_TAMPERED")
        self.assertTrue(server.verify_token(old.sign_token({"tier": "pro", "license_id": "y"}))[0])

    def test_mismatched_public_key_is_rejected(self):
        from app.config import Settings
        from app.infrastructure.security.ed25519_signer import Ed25519Signer
        priv, _ = Ed25519Signer.generate_keypair()
        _, other_pub = Ed25519Signer.generate_keypair()
        with self.assertRaises(ValueError):
            Ed25519Signer(private_key_hex=priv, public_key_hex=other_pub)
        derived = Ed25519Signer(private_key_hex=priv).get_public_key_hex()
        self.assertEqual(Ed25519Signer(private_key_hex=priv, public_key_hex=derived).get_public_key_hex(), derived)
        with self.assertRaises(RuntimeError) as cm:
            Settings(ENVIRONMENT="production", SECRET_KEY="s" * 48, ED25519_PRIVATE_KEY_HEX=priv,
                     ED25519_PUBLIC_KEY_HEX=other_pub, ADMIN_API_KEY="kf_" + "a" * 30,
                     STRIPE_WEBHOOK_SECRET="whsec_real", LEMONSQUEEZY_WEBHOOK_SECRET="ls_real",
                     ).validate_production_secrets()
        self.assertIn("does not match", str(cm.exception))

    def test_invalid_kid_and_retired_key_rejected(self):
        from app.infrastructure.security.ed25519_signer import Ed25519Signer
        with self.assertRaises(ValueError):
            Ed25519Signer(*Ed25519Signer.generate_keypair(), kid="bad kid!")
        with self.assertRaises(ValueError):
            Ed25519Signer(*Ed25519Signer.generate_keypair(), retired_public_keys="k1=abcd")


class TestMeteredRefund(BaseKeyForgeTestCase):
    def tearDown(self):
        os.environ.pop("QUOTA_REFUND_WINDOW_SECONDS", None)
        from app.config import get_settings
        get_settings.cache_clear()
        super().tearDown()

    def _balance(self, key: str) -> int:
        return self.client.get(f"/api/v1/quota/balance?license_key={key}").json()["data"]["credit_balance"]

    def test_refund_restores_credits_once(self):
        key = self.issue_license_api(customer_email="refund@acme.ai", tier="pro")["license_key"]
        idem = str(uuid.uuid4())
        self.assertEqual(self.deduct_quota_api(key, credits=7, idempotency_key=idem).status_code, 200)
        self.assertEqual(self._balance(key), 493)

        body = {"license_key": key, "idempotency_key": idem, "reason": "tool_failed"}
        first = self.client.post("/api/v1/quota/refund", json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["data"]["refunded"], 7)
        self.assertFalse(first.json()["data"]["is_cached"])
        self.assertEqual(self._balance(key), 500)

        replay = self.client.post("/api/v1/quota/refund", json=body)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["data"]["is_cached"])
        self.assertEqual(self._balance(key), 500)

    def test_deduct_replay_after_refund_is_rejected(self):
        key = self.issue_license_api(customer_email="replay@acme.ai", tier="pro")["license_key"]
        idem = str(uuid.uuid4())
        self.assertEqual(self.deduct_quota_api(key, credits=5, idempotency_key=idem).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/quota/refund",
                                          json={"license_key": key, "idempotency_key": idem}).status_code, 200)
        before = self._balance(key)
        replay = self.deduct_quota_api(key, credits=5, idempotency_key=idem)
        self.assertEqual(replay.status_code, 409, replay.text)
        self.assertEqual(replay.json()["error"]["details"]["reason"], "KEY_REFUNDED")
        self.assertEqual(self._balance(key), before)

    def test_deduct_rejects_reserved_refund_prefix(self):
        key = self.issue_license_api(customer_email="prefix@acme.ai")["license_key"]
        res = self.deduct_quota_api(key, credits=1, idempotency_key=f"refund:{uuid.uuid4()}")
        self.assertIn(res.status_code, (400, 422))

    def test_refund_unknown_or_cross_license_key_is_404(self):
        a = self.issue_license_api(customer_email="a_ref@acme.ai")["license_key"]
        b = self.issue_license_api(customer_email="b_ref@acme.ai")["license_key"]
        idem = str(uuid.uuid4())
        self.deduct_quota_api(a, credits=3, idempotency_key=idem)
        res = self.client.post("/api/v1/quota/refund", json={"license_key": b, "idempotency_key": idem})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "DEDUCTION_NOT_FOUND")
        res = self.client.post("/api/v1/quota/refund", json={"license_key": a, "idempotency_key": f"refund:{idem}"})
        self.assertIn(res.status_code, (400, 404, 422))

    def test_refund_outside_window_is_rejected(self):
        os.environ["QUOTA_REFUND_WINDOW_SECONDS"] = "0"
        from app.config import get_settings
        get_settings.cache_clear()
        key = self.issue_license_api(customer_email="late@acme.ai")["license_key"]
        idem = str(uuid.uuid4())
        self.deduct_quota_api(key, credits=2, idempotency_key=idem)
        res = self.client.post("/api/v1/quota/refund", json={"license_key": key, "idempotency_key": idem})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "REFUND_WINDOW_EXPIRED")


if __name__ == "__main__":
    unittest.main()
