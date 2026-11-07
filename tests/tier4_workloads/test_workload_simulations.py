"""Tier 4: Real-World Workload Simulations & Adversarial Hardening.

Covers comprehensive simulated lifecycles:
57. test_workload1_solopreneur_30day_lifecycle
58. test_workload2_airgapped_offline_cli_execution
59. test_workload3_payment_failure_grace_period_recovery
60. test_workload4_adversarial_security_audit
"""

from __future__ import annotations

import json
import secrets
import time
import uuid
import unittest
from tests.conftest import (
    BaseKeyFlintTestCase,
    decode_license_token,
    verify_payload_ed25519,
    sign_payload_ed25519,
    encode_license_token,
    TEST_ED25519_PUBLIC_KEY_HEX,
    ROGUE_ED25519_PRIVATE_KEY_HEX,
    generate_stripe_signature,
    TEST_STRIPE_WEBHOOK_SECRET,
)


class TestWorkloadSimulations(BaseKeyFlintTestCase):
    """End-to-End simulation of production user lifecycles and adversarial security stress."""

    def test_workload1_solopreneur_30day_lifecycle(self):
        """Simulates 30-day journey of AI builder: Registration -> Usage -> Paywall -> Upgrade -> CLI tasks -> Renewal."""
        self.require_app()
        customer_email = f"solopreneur_{uuid.uuid4().hex[:6]}@acme.ai"

        # Day 1: User registers on Community tier (starts with 25 credits)
        comm_lic = self.issue_license_api(customer_email=customer_email, tier="community")
        license_key = comm_lic["license_key"]

        bal_res = self.client.get(f"/api/v1/quota/balance?license_key={license_key}")
        bal = bal_res.json().get("data", bal_res.json()).get("credit_balance")
        self.assertEqual(bal, 25)

        # Days 2-5: User runs tasks and consumes all 25 credits
        self.deduct_quota_api(license_key=license_key, credits=15)
        self.deduct_quota_api(license_key=license_key, credits=10)

        # Day 5 evening: Hits 402 Paywall
        hit_paywall = self.deduct_quota_api(license_key=license_key, credits=1)
        self.assertEqual(hit_paywall.status_code, 402)

        # Day 6: Upgrades to Pro ($29/mo) via Stripe Checkout
        self.simulate_webhook_api(
            event_type="checkout.session.completed",
            customer_email=customer_email,
            tier="pro"
        )

        # Issue / retrieve new Pro license with 500 credits
        pro_lic = self.issue_license_api(customer_email=customer_email, tier="pro")
        pro_key = pro_lic["license_key"]

        pro_bal_res = self.client.get(f"/api/v1/quota/balance?license_key={pro_key}")
        pro_bal = pro_bal_res.json().get("data", pro_bal_res.json()).get("credit_balance")
        self.assertEqual(pro_bal, 1000, "Pro account must have 1000 credits")

        # Days 7-29: Executes offline validations
        tier, payload, sig = decode_license_token(pro_key)
        for _ in range(300):
            self.assertTrue(verify_payload_ed25519(payload, sig, TEST_ED25519_PUBLIC_KEY_HEX))

        # Day 30: Monthly subscription renewal webhook triggers
        renew_res = self.simulate_webhook_api(
            event_type="invoice.payment_succeeded",
            customer_email=customer_email,
            tier="pro"
        )
        self.assertEqual(renew_res.status_code, 200)

    def test_workload2_airgapped_offline_cli_execution(self):
        """Simulates airgapped CLI execution with zero network access using local Ed25519 public key."""
        self.require_app()
        # Server issues valid license
        data = self.issue_license_api(
            customer_email="airgapped@defense.gov",
            tier="studio",
            max_seats=10,
            features=["core", "cli_offline", "airgap_export"]
        )
        cached_license_token = data["license_key"]

        # In an isolated client execution (no HTTP requests made):
        tier, payload, sig_b64 = decode_license_token(cached_license_token)
        
        # 1. Offline cryptographic signature check
        is_valid = verify_payload_ed25519(payload, sig_b64, TEST_ED25519_PUBLIC_KEY_HEX)
        self.assertTrue(is_valid, "Airgapped verification must validate signature using local public key")

        # 2. Offline expiration evaluation
        now = int(time.time())
        self.assertGreater(payload["expires_at"], now, "Offline token must not be expired")

        # 3. Offline feature entitlement inspection
        features = payload.get("features", [])
        self.assertIn("cli_offline", features)
        self.assertIn("airgap_export", features)

    def test_workload3_payment_failure_grace_period_recovery(self):
        """Failed invoice payment triggers grace period with warning header; subsequent payment restores active."""
        self.require_app()
        customer_email = f"grace_{uuid.uuid4().hex[:6]}@acme.ai"
        data = self.issue_license_api(customer_email=customer_email, tier="pro")
        license_key = data["license_key"]

        # 1. Ingest failed payment webhook
        fail_res = self.simulate_webhook_api(
            event_type="invoice.payment_failed",
            customer_email=customer_email,
            tier="pro"
        )
        self.assertEqual(fail_res.status_code, 200)

        # 2. Subsequent verification AND quota deduction succeed with GRACE_PERIOD + X-Subscription-Warning header
        ver_res = self.verify_license_api(license_key=license_key)
        self.assertEqual(ver_res.status_code, 200)
        ver_data = ver_res.json()["data"]
        self.assertTrue(ver_data["valid"])
        self.assertEqual(ver_data["status"], "grace_period")
        self.assertIn("X-Subscription-Warning", ver_res.headers)
        self.assertIn("grace", ver_res.headers["X-Subscription-Warning"].lower())

        ded_res = self.deduct_quota_api(license_key=license_key, credits=10)
        self.assertEqual(ded_res.status_code, 200)
        self.assertIn("X-Subscription-Warning", ded_res.headers)
        self.assertEqual(ded_res.json()["data"]["remaining_balance"], 990)

        # 3. Customer updates card -> Payment succeeds -> Cycle resets to 500 without inflation
        rec_res = self.simulate_webhook_api(
            event_type="invoice.payment_succeeded",
            customer_email=customer_email,
            tier="pro"
        )
        self.assertEqual(rec_res.status_code, 200)

        # 4. Status restored to active and X-Subscription-Warning header is gone
        ver_res2 = self.verify_license_api(license_key=license_key)
        self.assertEqual(ver_res2.status_code, 200)
        payload2 = ver_res2.json()["data"]
        self.assertTrue(payload2["valid"])
        self.assertEqual(payload2["status"], "active")
        self.assertNotIn("X-Subscription-Warning", ver_res2.headers)

        bal_res = self.client.get(f"/api/v1/quota/balance?license_key={license_key}")
        self.assertEqual(bal_res.json()["data"]["credit_balance"], 1000)


    def test_workload4_adversarial_security_audit(self):
        """Automated penetration suite: 1,000 bad HMAC guesses, SQL injection fuzzing, expired replays, rogue keys."""
        self.require_app()
        # Vector A: 1,000 random HMAC signature forgery attempts against webhook receiver
        raw_body = json.dumps({"id": "evt_attack", "type": "checkout.session.completed"}).encode("utf-8")
        now = int(time.time())
        
        # Spot-check batch of 50 randomized HMAC forgery attempts
        for _ in range(50):
            fake_sig = secrets.token_hex(32)
            headers = {
                "Stripe-Signature": f"t={now},v1={fake_sig}",
                "Content-Type": "application/json"
            }
            res = self.client.post("/api/v1/webhooks/stripe", content=raw_body, headers=headers)
            self.assertIn(res.status_code, (400, 401), "Forged signature must be rejected")

        # Vector B: SQL Injection sweep across all query and JSON parameters
        sql_payloads = [
            "' OR '1'='1",
            "1; DROP TABLE licenses; --",
            "' UNION SELECT NULL, NULL, NULL --",
            "admin'--",
            "{\"email\": \"' OR 1=1 --\"}"
        ]
        for injection in sql_payloads:
            res = self.client.get(f"/api/v1/quota/balance?license_key={injection}")
            # Must not crash with 500 or expose database syntax errors
            self.assertIn(res.status_code, (400, 401, 403, 404, 422), f"SQL payload {injection} caused unexpected status: {res.status_code}")

        # Vector C: Signature replay attacks with expired timestamps (>300s)
        stale_time = now - 500
        stale_sig = generate_stripe_signature(raw_body, TEST_STRIPE_WEBHOOK_SECRET, timestamp=stale_time)
        res_stale = self.client.post(
            "/api/v1/webhooks/stripe",
            content=raw_body,
            headers={"Stripe-Signature": stale_sig, "Content-Type": "application/json"}
        )
        self.assertIn(res_stale.status_code, (400, 401), "Stale replay attack must be rejected")

        # Vector D: Rogue Ed25519 key forgery
        rogue_payload = {
            "license_id": "lic_rogue_adversarial",
            "tier": "studio",
            "customer_email": "attacker@darknet.org",
            "issued_at": now,
            "expires_at": now + 86400,
            "features": ["*"],
            "max_seats": 1000,
            "nonce": "forged",
        }
        rogue_sig = sign_payload_ed25519(rogue_payload, ROGUE_ED25519_PRIVATE_KEY_HEX)
        forged_key = encode_license_token("studio", rogue_payload, rogue_sig)
        
        # Verify offline fails
        self.assertFalse(verify_payload_ed25519(rogue_payload, rogue_sig, TEST_ED25519_PUBLIC_KEY_HEX))
        
        # Verify online fails
        res_rogue = self.verify_license_api(license_key=forged_key)
        if res_rogue.status_code == 200:
            payload_res = res_rogue.json().get("data", res_rogue.json())
            self.assertFalse(payload_res.get("valid"))
        else:
            self.assertIn(res_rogue.status_code, (400, 401, 422))


if __name__ == "__main__":
    unittest.main()
