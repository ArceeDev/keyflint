"""Tier 2: Boundary & Corner Cases — License Cryptography & Token Formatting.

Covers:
26. test_bound1_tampered_payload_byte_fails_signature_check
27. test_bound1_expired_license_fails_verification
28. test_bound1_malformed_token_missing_dot_delimiter_rejected
29. test_bound1_empty_string_or_whitespace_license_rejected
30. test_bound1_rogue_public_key_fails_verification
"""

from __future__ import annotations

import time
import unittest
from tests.conftest import (
    BaseKeyFlintTestCase,
    decode_license_token,
    encode_license_token,
    verify_payload_ed25519,
    sign_payload_ed25519,
    TEST_ED25519_PUBLIC_KEY_HEX,
    ROGUE_ED25519_PRIVATE_KEY_HEX,
)


class TestLicenseBoundaries(BaseKeyFlintTestCase):
    """Boundary verification for cryptographic license parsing and verification."""

    def test_bound1_tampered_payload_byte_fails_signature_check(self):
        """Mutating one character in base64 payload fails signature verification."""
        self.require_app()
        data = self.issue_license_api(customer_email="tamper@acme.ai", tier="pro")
        valid_key = data["license_key"]
        tier, payload, sig = decode_license_token(valid_key)

        # Tamper payload: change customer email
        payload["customer_email"] = "hacker@evil.com"
        tampered_key = encode_license_token(tier, payload, sig)

        # 1. Offline verification must reject tampered token
        self.assertFalse(
            verify_payload_ed25519(payload, sig, TEST_ED25519_PUBLIC_KEY_HEX),
            "Tampered payload must fail Ed25519 verification"
        )

        # 2. Online verification endpoint must reject tampered token
        res = self.verify_license_api(license_key=tampered_key)
        if res.status_code == 200:
            body = res.json()
            payload_res = body.get("data", body)
            self.assertFalse(payload_res.get("valid"))
        else:
            self.assertIn(res.status_code, (400, 401, 422))

    def test_bound1_expired_license_fails_verification(self):
        """Setting expires_at in the past returns ERR_LICENSE_EXPIRED or valid=False."""
        self.require_app()
        # Create an expired payload
        past_time = int(time.time()) - 3600
        expired_payload = {
            "license_id": "lic_expired_test",
            "tier": "pro",
            "customer_id": "cus_expired",
            "customer_email": "expired@acme.ai",
            "issued_at": past_time - 86400,
            "expires_at": past_time,
            "features": ["core"],
            "max_seats": 1,
            "nonce": "exp_nonce_123",
        }
        sig = sign_payload_ed25519(expired_payload)
        expired_key = encode_license_token("pro", expired_payload, sig)

        res = self.verify_license_api(license_key=expired_key)
        if res.status_code == 200:
            body = res.json()
            payload_res = body.get("data", body)
            self.assertFalse(payload_res.get("valid"), "Expired license must be invalid")
        else:
            self.assertIn(res.status_code, (400, 403, 422))

    def test_bound1_malformed_token_missing_dot_delimiter_rejected(self):
        """Token without '.' delimiter raises format error."""
        self.require_app()
        malformed_token = "LIC-PRO-eyJzb21lIjoidmFsdWUifQnoDotDelimiterSignatureHere"
        res = self.verify_license_api(license_key=malformed_token)
        self.assertIn(res.status_code, (400, 422), f"Malformed token must return 400/422: {res.text}")

    def test_bound1_empty_string_or_whitespace_license_rejected(self):
        """Empty string or whitespace-only token fails validation with HTTP 422."""
        self.require_app()
        for invalid_input in ["", "   ", "\t\n"]:
            res = self.verify_license_api(license_key=invalid_input)
            self.assertIn(res.status_code, (400, 422), f"Input '{invalid_input}' should be rejected")

    def test_bound1_rogue_public_key_fails_verification(self):
        """Token signed with rogue external private key fails verification against authentic public key."""
        self.require_app()
        payload = {
            "license_id": "lic_rogue_001",
            "tier": "pro",
            "customer_email": "rogue@attacker.io",
            "issued_at": int(time.time()),
            "expires_at": int(time.time()) + 86400,
            "features": ["core", "all_admin_capabilities"],
            "max_seats": 999,
            "nonce": "rogue_nonce",
        }
        rogue_sig = sign_payload_ed25519(payload, ROGUE_ED25519_PRIVATE_KEY_HEX)
        rogue_key = encode_license_token("pro", payload, rogue_sig)

        # Authentic public key check must fail
        self.assertFalse(
            verify_payload_ed25519(payload, rogue_sig, TEST_ED25519_PUBLIC_KEY_HEX),
            "Rogue signed payload must not verify with server authentic public key"
        )

        # Server online verification must reject rogue token
        res = self.verify_license_api(license_key=rogue_key)
        if res.status_code == 200:
            body = res.json()
            payload_res = body.get("data", body)
            self.assertFalse(payload_res.get("valid"))
        else:
            self.assertIn(res.status_code, (400, 401, 422))


if __name__ == "__main__":
    unittest.main()
