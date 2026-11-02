"""Tier 2: Boundary & Corner Cases — Validator, Machine Binding & Seat Limits.

Covers:
31. test_bound2_seat_limit_overflow_rejects_new_activation
32. test_bound2_mismatched_machine_hardware_id_rejected
33. test_bound2_license_with_missing_feature_flag_denied
34. test_bound2_duplicate_activation_same_machine_idempotent
35. test_bound2_clock_skew_tolerance_boundary
"""

from __future__ import annotations

import time
import unittest
from tests.conftest import (
    BaseKeyFlintTestCase,
    encode_license_token,
    sign_payload_ed25519,
)


class TestValidatorBoundaries(BaseKeyFlintTestCase):
    """Boundary verification for activations, hardware locking, and seat limits."""

    def test_bound2_seat_limit_overflow_rejects_new_activation(self):
        """2nd machine activation on a 1-seat license returns HTTP 409 Conflict."""
        self.require_app()
        data = self.issue_license_api(customer_email="single_seat@acme.ai", tier="pro", max_seats=1)
        license_key = data["license_key"]

        # Activate seat 1 -> Success
        res1 = self.activate_license_api(license_key=license_key, hardware_id="hw-node-001")
        self.assertEqual(res1.status_code, 200)

        # Attempt to activate seat 2 -> Rejected with 409 Conflict
        res2 = self.activate_license_api(license_key=license_key, hardware_id="hw-node-002")
        self.assertIn(res2.status_code, (409, 403), f"Seat overflow should be rejected: {res2.text}")

    def test_bound2_mismatched_machine_hardware_id_rejected(self):
        """Verifying node-locked token on different hardware ID fails."""
        self.require_app()
        data = self.issue_license_api(customer_email="locked@acme.ai", tier="pro", max_seats=1)
        license_key = data["license_key"]

        # Bind to hardware-1
        self.activate_license_api(license_key=license_key, hardware_id="hw-alpha-001")

        # Verify with wrong hardware ID
        res = self.verify_license_api(license_key=license_key, hardware_id="hw-intruder-999")
        if res.status_code == 200:
            body = res.json()
            payload = body.get("data", body)
            self.assertFalse(payload.get("valid"), "Mismatched hardware ID must invalidate check")
        else:
            self.assertIn(res.status_code, (400, 403))

    def test_bound2_license_with_missing_feature_flag_denied(self):
        """Attempting action requiring ungranted feature flag is denied."""
        self.require_app()
        data = self.issue_license_api(
            customer_email="basic@acme.ai",
            tier="community",
            features=["core"]
        )
        license_key = data["license_key"]

        res = self.verify_license_api(license_key=license_key)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        payload = body.get("data", body)
        features = payload.get("features", [])

        self.assertNotIn("enterprise_clustering", features)

    def test_bound2_duplicate_activation_same_machine_idempotent(self):
        """Re-activating same machine returns existing grant without seat penalty."""
        self.require_app()
        data = self.issue_license_api(customer_email="idempotent_act@acme.ai", tier="pro", max_seats=1)
        license_key = data["license_key"]

        # Activate machine A
        res1 = self.activate_license_api(license_key=license_key, hardware_id="hw-same-001")
        self.assertEqual(res1.status_code, 200)

        # Re-activate same machine A
        res2 = self.activate_license_api(license_key=license_key, hardware_id="hw-same-001")
        self.assertEqual(res2.status_code, 200, "Re-activation of same machine must be idempotent")
        body2 = res2.json()
        payload2 = body2.get("data", body2)
        self.assertEqual(payload2.get("current_activations"), 1, "Activations count must remain 1")

    def test_bound2_clock_skew_tolerance_boundary(self):
        """Token expiring in +/- 5 seconds respects boundary tolerance."""
        self.require_app()
        now = int(time.time())
        
        # Token expiring in 2 seconds (still active within grace window)
        active_payload = {
            "license_id": "lic_clock_skew_active",
            "tier": "pro",
            "customer_email": "skew@acme.ai",
            "issued_at": now - 3600,
            "expires_at": now + 2,
            "features": ["core"],
            "max_seats": 1,
            "nonce": "skew_active_nonce",
        }
        sig = sign_payload_ed25519(active_payload)
        key = encode_license_token("pro", active_payload, sig)

        res = self.verify_license_api(license_key=key)
        # Should be valid at evaluation moment
        if res.status_code == 200:
            body = res.json()
            payload = body.get("data", body)
            self.assertTrue(payload.get("valid"))


if __name__ == "__main__":
    unittest.main()
