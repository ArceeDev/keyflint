"""Tier 1: Feature Coverage — Feature 1: Cryptographic License Key Generator (FEAT-LIC-01).

Covers positive path execution:
1. test_feat1_issue_license_creates_valid_ed25519_signature
2. test_feat1_issue_license_creates_valid_hmac_signature
3. test_feat1_license_encodes_correct_tier_and_capabilities
4. test_feat1_license_contains_valid_future_expiration
5. test_feat1_license_includes_unique_cryptographic_nonce
"""

from __future__ import annotations

import time
import unittest
from tests.conftest import (
    BaseKeyFlintTestCase,
    decode_license_token,
    verify_payload_ed25519,
    verify_payload_hmac,
    TEST_ED25519_PUBLIC_KEY_HEX,
    TEST_SECRET_KEY,
)


class TestLicenseLifecycle(BaseKeyFlintTestCase):
    """E2E Verification for FEAT-LIC-01: Cryptographic License Generator."""

    def test_feat1_issue_license_creates_valid_ed25519_signature(self):
        """Verifies Ed25519 signature verifies against server public key."""
        self.require_app()
        data = self.issue_license_api(
            customer_email="alex@acme.ai",
            tier="pro",
            max_seats=2,
            features=["core", "cli_offline"],
            signing_algorithm="ed25519",
        )
        license_key = data.get("license_key")
        self.assertIsNotNone(license_key, "Response must include 'license_key'")
        self.assertTrue(license_key.startswith("LIC-PRO-"), f"Key must have LIC-PRO- prefix: {license_key}")

        tier, payload, sig_b64 = decode_license_token(license_key)
        self.assertEqual(tier, "pro")
        self.assertEqual(payload["customer_email"], "alex@acme.ai")

        # Cryptographically verify the Ed25519 signature
        is_valid = verify_payload_ed25519(payload, sig_b64, TEST_ED25519_PUBLIC_KEY_HEX)
        self.assertTrue(is_valid, "Ed25519 signature on issued license key must be cryptographically valid")

    def test_feat1_issue_license_creates_valid_hmac_signature(self):
        """Verifies HMAC-SHA256 signature against server secret."""
        self.require_app()
        data = self.issue_license_api(
            customer_email="symmetric@acme.ai",
            tier="community",
            max_seats=1,
            features=["core"],
            signing_algorithm="hmac-sha256",
        )
        license_key = data.get("license_key")
        self.assertIsNotNone(license_key)
        self.assertTrue(license_key.startswith("LIC-COMMUNITY-"))

        tier, payload, sig_b64 = decode_license_token(license_key)
        self.assertEqual(tier, "community")

        # Verify HMAC-SHA256 signature
        is_valid = verify_payload_hmac(payload, sig_b64, TEST_SECRET_KEY)
        self.assertTrue(is_valid, "HMAC-SHA256 signature on issued license must be valid")

    def test_feat1_license_encodes_correct_tier_and_capabilities(self):
        """Verifies decoded payload matches requested entitlements."""
        self.require_app()
        features = ["core", "cli_offline", "telemetry_sync"]
        data = self.issue_license_api(
            customer_email="capabilities@acme.ai",
            tier="studio",
            max_seats=5,
            features=features,
        )
        license_key = data.get("license_key")
        tier, payload, _ = decode_license_token(license_key)

        self.assertEqual(tier, "studio")
        self.assertEqual(payload.get("tier"), "studio")
        self.assertEqual(payload.get("customer_email"), "capabilities@acme.ai")
        self.assertEqual(payload.get("max_seats"), 5)
        self.assertListEqual(sorted(payload.get("features", [])), sorted(features))

    def test_feat1_license_contains_valid_future_expiration(self):
        """Verifies expires_at > issued_at and matches requested duration."""
        self.require_app()
        now = int(time.time())
        expires_days = 90
        data = self.issue_license_api(
            customer_email="expiry@acme.ai",
            tier="pro",
            expires_in_days=expires_days,
        )
        license_key = data.get("license_key")
        _, payload, _ = decode_license_token(license_key)

        issued_at = payload.get("issued_at")
        expires_at = payload.get("expires_at")

        self.assertIsNotNone(issued_at, "Payload must include issued_at")
        self.assertIsNotNone(expires_at, "Payload must include expires_at")
        self.assertAlmostEqual(issued_at, now, delta=15, msg="issued_at must be close to current time")
        expected_expiry = issued_at + (expires_days * 86400)
        self.assertAlmostEqual(expires_at, expected_expiry, delta=60, msg="expires_at must match requested duration")
        self.assertGreater(expires_at, issued_at)

    def test_feat1_license_includes_unique_cryptographic_nonce(self):
        """Verifies two licenses for same customer have distinct nonces and signatures."""
        self.require_app()
        data1 = self.issue_license_api(customer_email="alex@acme.ai", tier="pro")
        data2 = self.issue_license_api(customer_email="alex@acme.ai", tier="pro")

        key1 = data1.get("license_key")
        key2 = data2.get("license_key")

        self.assertNotEqual(key1, key2, "Two separately issued license keys must be unique")

        _, payload1, sig1 = decode_license_token(key1)
        _, payload2, sig2 = decode_license_token(key2)

        self.assertNotEqual(sig1, sig2, "Signatures must differ due to unique cryptographic nonce")
        self.assertNotEqual(
            payload1.get("nonce"),
            payload2.get("nonce"),
            "Payload nonces must be uniquely generated for replay resistance"
        )


if __name__ == "__main__":
    unittest.main()
