"""Tier 1: Feature Coverage — Feature 2 & 3: Offline/Online Validator & Node Locking (FEAT-LIC-02/03).

Covers:
6. test_feat2_offline_validator_verifies_valid_key_without_network
7. test_feat2_online_validator_returns_active_status
8. test_feat2_activate_license_binds_machine_hardware_id
9. test_feat2_revoked_license_fails_online_validation
10. test_feat2_feature_flag_check_confirms_entitlement
+ Pure-Python RFC 8032 malleability rejection, SUSPENDED/EXPIRED enforcement, domain locking, and revocation ledger persistence
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from app.domain.entities.license import LicenseStatus
from app.infrastructure.database.connection import create_connection
from app.infrastructure.repositories.sqlite_license_repo import SqliteLicenseRepo
from app.infrastructure.security.ed25519_signer import _L_PARAM, b64url_decode, b64url_encode
from app.infrastructure.security.offline_validator import validate_offline
from tests.conftest import (
    BaseKeyForgeTestCase,
    TEST_ED25519_PUBLIC_KEY_HEX,
)


class TestValidatorAndNodeLocking(BaseKeyForgeTestCase):
    """E2E Verification for FEAT-LIC-02 and FEAT-LIC-03: Dual Verification & Hardware Locking."""

    def test_feat2_offline_validator_verifies_valid_key_without_network(self):
        """validate_offline verifies valid key in both OpenSSL and pure-Python modes and rejects malleable s+L signatures."""
        self.require_app()
        res = self.client.post(
            "/api/v1/licenses/issue",
            json={
                "customer_email": "offline@acme.ai",
                "tier": "pro",
                "machine_id": "HW-OFFLINE-42",
            },
        )
        self.assertEqual(res.status_code, 200)
        license_key = res.json()["data"]["license_key"]

        # 1. OpenSSL-backed validate_offline
        ok_native, payload_native, err_native = validate_offline(
            license_key,
            TEST_ED25519_PUBLIC_KEY_HEX,
            expected_machine_id="hw-offline-42",
        )
        self.assertTrue(ok_native, f"Native offline validation failed: {err_native}")
        self.assertIsNone(err_native)
        self.assertEqual(payload_native["tier"], "pro")

        # 2. Pure-Python RFC 8032 extended coordinates validate_offline
        ok_pure, payload_pure, err_pure = validate_offline(
            license_key=license_key,
            public_key_hex=TEST_ED25519_PUBLIC_KEY_HEX,
            expected_machine_id="HW-OFFLINE-42",
            force_pure_python=True,
        )
        self.assertTrue(ok_pure, f"Pure-Python offline validation failed: {err_pure}")
        self.assertEqual(payload_pure, payload_native)

        # 3. Wrong machine_id fails offline node-lock check
        ok_wrong_hw, _, err_wrong_hw = validate_offline(
            license_key,
            TEST_ED25519_PUBLIC_KEY_HEX,
            expected_machine_id="hw-intruder-99",
            force_pure_python=True,
        )
        self.assertFalse(ok_wrong_hw)
        self.assertEqual(err_wrong_hw, "ERR_NODE_LOCK_VIOLATION")

        # 4. RFC 8032 §5.1.3 malleability rejection: s' = s + L must be rejected
        prefix_part, sig_b64 = license_key.split(".")
        sig_bytes = b64url_decode(sig_b64)
        r_bytes = sig_bytes[:32]
        s_int = int.from_bytes(sig_bytes[32:], "little")
        malleable_s = s_int + _L_PARAM
        if malleable_s < (1 << 256):
            malleable_sig = b64url_encode(r_bytes + malleable_s.to_bytes(32, "little"))
            malleable_token = f"{prefix_part}.{malleable_sig}"
            ok_mal, _, _ = validate_offline(
                malleable_token, TEST_ED25519_PUBLIC_KEY_HEX, force_pure_python=True
            )
            self.assertFalse(ok_mal, "RFC 8032 requires rejecting s >= L")

    def test_feat2_online_validator_returns_active_status(self):
        """Online endpoint confirms license validity against database."""
        self.require_app()
        data = self.issue_license_api(customer_email="online@acme.ai", tier="pro")
        license_key = data["license_key"]

        res = self.verify_license_api(license_key=license_key)
        self.assertEqual(res.status_code, 200, f"Verify API returned: {res.text}")
        body = res.json()
        payload = body.get("data", body)

        self.assertTrue(payload.get("valid"), "License must be marked valid")
        self.assertEqual(payload.get("status"), "active", "License status must be active")
        self.assertEqual(payload.get("tier"), "pro", "License tier must match")

    def test_feat2_activate_license_binds_machine_hardware_id(self):
        """Successfully registers machine ID (case-normalized) and returns activation grant."""
        self.require_app()
        data = self.issue_license_api(customer_email="node@acme.ai", tier="pro", max_seats=2)
        license_key = data["license_key"]

        res = self.activate_license_api(
            license_key=license_key,
            hardware_id="HW-Node-001",
            machine_name="production-worker-alpha",
        )
        self.assertEqual(res.status_code, 200, f"Activation failed: {res.text}")
        payload = res.json().get("data", {})

        self.assertTrue(payload.get("activated"), "Activation must succeed")
        self.assertEqual(payload.get("current_activations"), 1)
        self.assertEqual(payload.get("max_seats"), 2)

        # Case-insensitive verify succeeds
        ver_ok = self.verify_license_api(license_key=license_key, hardware_id="hw-node-001")
        self.assertTrue(ver_ok.json()["data"]["valid"])

    def test_feat2_revoked_license_fails_online_validation(self):
        """Revoked license fails online validation even if license row is later purged."""
        self.require_app()
        data = self.issue_license_api(customer_email="revoked@acme.ai", tier="pro")
        license_key = data["license_key"]
        license_id = data["license_id"]

        revoke_res = self.client.post(
            "/api/v1/licenses/revoke",
            json={"license_key": license_key, "reason": "chargeback_dispute"},
        )
        self.assertEqual(revoke_res.status_code, 200, f"Revoke failed: {revoke_res.text}")

        verify_res = self.verify_license_api(license_key=license_key)
        self.assertEqual(verify_res.status_code, 200)
        payload = verify_res.json()["data"]
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["status"], "revoked")

        # Delete the row from licenses table -> revoked_licenses ledger must STILL block stateless fallback!
        conn = create_connection()
        try:
            conn.execute("DELETE FROM licenses WHERE id = ?", (license_id,))
            conn.commit()
        finally:
            conn.close()

        verify_after_purge = self.verify_license_api(license_key=license_key)
        self.assertEqual(verify_after_purge.status_code, 200)
        self.assertFalse(verify_after_purge.json()["data"]["valid"])
        self.assertEqual(verify_after_purge.json()["data"]["status"], "revoked")

    def test_feat2_feature_flag_check_confirms_entitlement(self):
        """Verifies feature flags in verification payload confirm customer entitlements."""
        self.require_app()
        data = self.issue_license_api(
            customer_email="entitlements@acme.ai",
            tier="studio",
            features=["core", "cli_offline", "telemetry_sync"],
        )
        license_key = data["license_key"]

        res = self.verify_license_api(license_key=license_key)
        self.assertEqual(res.status_code, 200)
        features = res.json()["data"].get("features", [])

        self.assertIn("cli_offline", features)
        self.assertIn("telemetry_sync", features)
        self.assertNotIn("unauthorized_feature_flag", features)

    def test_suspended_expired_and_domain_lock_enforcement(self):
        """Verifies SUSPENDED, EXPIRED (persisted to SQLite), and wildcard domain locks across endpoints."""
        self.require_app()
        issue_res = self.client.post(
            "/api/v1/licenses/issue",
            json={
                "customer_email": "locks@acme.ai",
                "tier": "pro",
                "allowed_domains": ["*.acme.ai"],
            },
        )
        self.assertEqual(issue_res.status_code, 200)
        lic_data = issue_res.json()["data"]
        key = lic_data["license_key"]
        lic_id = lic_data["license_id"]

        # Domain lock check: matching subdomain succeeds, mismatched domain fails
        dom_ok = self.verify_license_api(license_key=key, domain="api.acme.ai")
        self.assertTrue(dom_ok.json()["data"]["valid"])

        dom_bad = self.verify_license_api(license_key=key, domain="evil.org")
        self.assertFalse(dom_bad.json()["data"]["valid"])
        self.assertEqual(dom_bad.json()["data"]["status"], "domain_lock_violation")

        # Mark SUSPENDED -> verify returns valid=False, status=suspended; activate & deduct return 403
        conn = create_connection()
        try:
            repo = SqliteLicenseRepo(conn)
            repo.update_status(lic_id, LicenseStatus.SUSPENDED)
        finally:
            conn.close()

        ver_susp = self.verify_license_api(license_key=key, domain="api.acme.ai")
        self.assertFalse(ver_susp.json()["data"]["valid"])
        self.assertEqual(ver_susp.json()["data"]["status"], "suspended")

        act_susp = self.activate_license_api(license_key=key, hardware_id="hw-susp-1")
        self.assertEqual(act_susp.status_code, 403)
        self.assertEqual(act_susp.json()["error"]["code"], "LICENSE_SUSPENDED")

        ded_susp = self.deduct_quota_api(license_key=key, credits=1)
        self.assertEqual(ded_susp.status_code, 403)
        self.assertEqual(ded_susp.json()["error"]["code"], "LICENSE_SUSPENDED")

        # Set status back to ACTIVE but expires_at in the past -> verify persists EXPIRED to SQLite
        past_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        conn = create_connection()
        try:
            conn.execute(
                "UPDATE licenses SET status = 'active', expires_at = ? WHERE id = ?",
                (past_iso, lic_id),
            )
            conn.commit()
        finally:
            conn.close()

        ver_exp = self.verify_license_api(license_key=key, domain="api.acme.ai")
        self.assertFalse(ver_exp.json()["data"]["valid"])
        self.assertEqual(ver_exp.json()["data"]["status"], "expired")

        conn = create_connection()
        try:
            persisted_status = conn.execute(
                "SELECT status FROM licenses WHERE id = ?", (lic_id,)
            ).fetchone()["status"]
        finally:
            conn.close()
        self.assertEqual(persisted_status, "expired")


if __name__ == "__main__":
    unittest.main()
