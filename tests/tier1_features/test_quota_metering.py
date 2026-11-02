"""Tier 1: Feature Coverage — Feature 3: Token-Bucket Quota Metering & Deductions (FEAT-QUO-01).

Covers:
11. test_feat3_new_account_initialized_with_tier_credits
12. test_feat3_atomic_deduct_reduces_balance_accurately
13. test_feat3_deduction_creates_audit_transaction_record
14. test_feat3_idempotent_deduction_returns_cached_balance
15. test_feat3_billing_status_endpoint_reports_accurate_usage
+ Replenish endpoint, cumulative consumed_total accuracy, cross-tenant idempotency isolation, and telemetry audit trail
"""

from __future__ import annotations

import unittest
import uuid

from tests.conftest import BaseKeyFlintTestCase


class TestQuotaMetering(BaseKeyFlintTestCase):
    """E2E Verification for FEAT-QUO-01: Token-Bucket Usage Quotas and Atomic Deductions."""

    def test_feat3_new_account_initialized_with_tier_credits(self):
        """Community account initialized with 25 credits; Pro initialized with 500 credits."""
        self.require_app()
        comm_data = self.issue_license_api(customer_email="comm_quota@acme.ai", tier="community")
        comm_res = self.client.get(f"/api/v1/quota/balance?license_key={comm_data['license_key']}")
        self.assertEqual(comm_res.status_code, 200, f"Get balance failed: {comm_res.text}")
        comm_payload = comm_res.json().get("data", {})
        self.assertEqual(comm_payload.get("credit_balance"), 25)

        pro_data = self.issue_license_api(customer_email="pro_quota@acme.ai", tier="pro")
        pro_res = self.client.get(f"/api/v1/quota/balance?license_key={pro_data['license_key']}")
        self.assertEqual(pro_res.status_code, 200)
        pro_payload = pro_res.json().get("data", {})
        self.assertEqual(pro_payload.get("credit_balance"), 500)

    def test_feat3_atomic_deduct_reduces_balance_accurately(self):
        """Sequential deductions drop balance accurately and report cumulative consumed_total."""
        self.require_app()
        data = self.issue_license_api(customer_email="deduct@acme.ai", tier="community")
        license_key = data["license_key"]

        res1 = self.deduct_quota_api(license_key=license_key, credits=5)
        self.assertEqual(res1.status_code, 200)
        p1 = res1.json()["data"]
        self.assertEqual(p1["deducted"], 5)
        self.assertEqual(p1["remaining_balance"], 20)
        self.assertEqual(p1["consumed_total"], 5)

        res2 = self.deduct_quota_api(license_key=license_key, credits=7)
        self.assertEqual(res2.status_code, 200)
        p2 = res2.json()["data"]
        self.assertEqual(p2["consumed_credits"], 7)
        self.assertEqual(p2["consumed_total"], 12)
        self.assertEqual(p2["remaining_balance"], 13)

    def test_feat3_deduction_creates_audit_transaction_record(self):
        """Ledger records event and exposes it via GET /api/v1/telemetry/events."""
        self.require_app()
        data = self.issue_license_api(customer_email="audit@acme.ai", tier="community")
        license_key = data["license_key"]
        idem_key = str(uuid.uuid4())

        res = self.deduct_quota_api(
            license_key=license_key,
            credits=3,
            idempotency_key=idem_key,
            event_type="test_audit_event",
            metadata={"source": "cli_batch"},
        )
        self.assertEqual(res.status_code, 200)
        payload = res.json()["data"]
        self.assertIn("transaction_id", payload)
        self.assertEqual(payload.get("idempotency_key"), idem_key)

        tel_res = self.client.get(f"/api/v1/telemetry/events?license_key={license_key}")
        self.assertEqual(tel_res.status_code, 200)
        tel_data = tel_res.json()["data"]
        self.assertEqual(tel_data["count"], 1)
        self.assertEqual(tel_data["events"][0]["idempotency_key"], idem_key)
        self.assertEqual(tel_data["events"][0]["credits_consumed"], 3)

    def test_feat3_idempotent_deduction_returns_cached_balance(self):
        """Replaying same Idempotency-Key caches per license, rejects conflicting amount with 409, and isolates tenants."""
        self.require_app()
        lic_a = self.issue_license_api(customer_email="tenant_a@acme.ai", tier="community")["license_key"]
        lic_b = self.issue_license_api(customer_email="tenant_b@acme.ai", tier="community")["license_key"]
        shared_idem = f"idem_{uuid.uuid4().hex}"

        # Tenant A first deduction
        res1 = self.deduct_quota_api(license_key=lic_a, credits=5, idempotency_key=shared_idem)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["data"]["remaining_balance"], 20)

        # Tenant A replay with identical credits -> cached 200
        res2 = self.deduct_quota_api(license_key=lic_a, credits=5, idempotency_key=shared_idem)
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.json()["data"]["is_cached"])
        self.assertEqual(res2.json()["data"]["remaining_balance"], 20)

        # Tenant A conflicting credits with same idempotency_key -> 409 without cross-tenant leak
        conflict = self.deduct_quota_api(license_key=lic_a, credits=9, idempotency_key=shared_idem)
        self.assertEqual(conflict.status_code, 409)
        self.assertNotIn("cached_license_id", conflict.json()["error"].get("details", {}))

        # Tenant B using the EXACT SAME idempotency_key string succeeds independently!
        res_b = self.deduct_quota_api(license_key=lic_b, credits=4, idempotency_key=shared_idem)
        self.assertEqual(res_b.status_code, 200)
        self.assertEqual(res_b.json()["data"]["remaining_balance"], 21)

    def test_feat3_billing_status_endpoint_reports_accurate_usage(self):
        """Returns accurate credit_balance, quota allowance, consumed credits, and supports POST /quota/replenish."""
        self.require_app()
        data = self.issue_license_api(customer_email="status@acme.ai", tier="community")
        license_key = data["license_key"]

        self.deduct_quota_api(license_key=license_key, credits=4)
        self.deduct_quota_api(license_key=license_key, credits=3)

        res = self.client.get(f"/api/v1/billing/status?license_key={license_key}")
        self.assertEqual(res.status_code, 200)
        payload = res.json()["data"]
        self.assertEqual(payload.get("credit_balance"), 18)
        self.assertEqual(payload.get("consumed"), 7)

        # Top-up replenish +10 credits
        rep_res = self.client.post(
            "/api/v1/quota/replenish",
            json={"license_key": license_key, "credits": 10, "reset_cycle": False},
        )
        self.assertEqual(rep_res.status_code, 200)
        rep_data = rep_res.json()["data"]
        self.assertEqual(rep_data["balance"], 28)
        self.assertEqual(rep_data["total_allowance"], 35)
        self.assertEqual(rep_data["consumed"], 7)


if __name__ == "__main__":
    unittest.main()
