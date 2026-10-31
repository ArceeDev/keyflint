"""Tier 3: Interactions and Pairwise Workflows.

Covers cross-feature state machines:
51. test_pair1_checkout_to_activation_full_cycle
52. test_pair2_quota_exhaustion_paywall_upgrade_recovery
53. test_pair3_concurrent_atomic_debit_integrity
54. test_pair4_webhook_replay_deduplication
55. test_pair5_subscription_cancellation_instant_lockout
56. test_pair6_rate_limiter_precedes_credit_deduction
"""

from __future__ import annotations

import concurrent.futures
import json
import uuid
import unittest
from tests.conftest import (
    BaseKeyForgeTestCase,
    decode_license_token,
    verify_payload_ed25519,
    TEST_ED25519_PUBLIC_KEY_HEX,
    generate_stripe_signature,
    TEST_STRIPE_WEBHOOK_SECRET,
)


class TestPairwiseWorkflows(BaseKeyForgeTestCase):
    """Pairwise integration workflows testing cross-module state machines."""

    def test_pair1_checkout_to_activation_full_cycle(self):
        """Checkout simulation -> Account auto-created -> Signed Ed25519 key -> Machine activated -> Verified."""
        self.require_app()
        customer_email = f"cycle_{uuid.uuid4().hex[:6]}@acme.ai"
        machine_hw_id = f"hw-node-{uuid.uuid4().hex[:8]}"

        # Step 1: Simulate checkout webhook for pro tier
        sim_res = self.simulate_webhook_api(
            event_type="checkout.session.completed",
            customer_email=customer_email,
            tier="pro"
        )
        self.assertEqual(sim_res.status_code, 200)
        sim_data = sim_res.json().get("data", sim_res.json())
        license_key = sim_data.get("license_key")

        self.assertIsNotNone(license_key, "Webhook checkout must provision and return signed license_key")
        self.assertTrue(license_key.startswith("LIC-PRO-"))

        # Step 2: Register & activate machine
        act_res = self.activate_license_api(
            license_key=license_key,
            hardware_id=machine_hw_id,
            machine_name="production-server-01"
        )
        self.assertEqual(act_res.status_code, 200)
        act_data = act_res.json().get("data", act_res.json())
        self.assertTrue(act_data.get("activated"))

        # Step 3: Offline validation with Ed25519 public key
        tier, payload, sig_b64 = decode_license_token(license_key)
        self.assertTrue(verify_payload_ed25519(payload, sig_b64, TEST_ED25519_PUBLIC_KEY_HEX))

        # Step 4: Online validation with hardware ID
        ver_res = self.verify_license_api(license_key=license_key, hardware_id=machine_hw_id)
        self.assertEqual(ver_res.status_code, 200)
        ver_data = ver_res.json().get("data", ver_res.json())
        self.assertTrue(ver_data.get("valid"))

    def test_pair2_quota_exhaustion_paywall_upgrade_recovery(self):
        """Quota exhaustion -> 402 Paywall -> Webhook upgrade to Pro -> Recovery succeeds."""
        self.require_app()
        customer_email = f"recovery_{uuid.uuid4().hex[:6]}@acme.ai"
        
        # 1. Issue Community license (25 credits)
        data = self.issue_license_api(customer_email=customer_email, tier="community")
        license_key = data["license_key"]

        # 2. Exhaust credits to 0
        deduct1 = self.deduct_quota_api(license_key=license_key, credits=25)
        self.assertEqual(deduct1.status_code, 200)

        # 3. Action returns 402 Payment Required
        deduct2 = self.deduct_quota_api(license_key=license_key, credits=5)
        self.assertEqual(deduct2.status_code, 402, "Zero balance must trigger 402")

        # 4. Ingest upgrade webhook to Pro (+500 credits, re-signed LIC-PRO-* key)
        up_res = self.simulate_webhook_api(
            event_type="checkout.session.completed",
            customer_email=customer_email,
            tier="pro"
        )
        self.assertEqual(up_res.status_code, 200)
        upgraded_key = up_res.json().get("data", {}).get("license_key")
        self.assertTrue(upgraded_key and upgraded_key.startswith("LIC-PRO-"))

        # 5. Retrying original 5-credit action immediately succeeds
        deduct3 = self.deduct_quota_api(license_key=license_key, credits=5)
        self.assertEqual(deduct3.status_code, 200, "Operation must succeed after tier upgrade")
        self.assertEqual(deduct3.json()["data"]["remaining_balance"], 495)

    def test_pair3_concurrent_atomic_debit_integrity(self):
        """Account initialized with 15 credits. 10 concurrent requests for 5 credits.
        Exactly 3 must return 200 OK; exactly 7 must return 402 Payment Required.
        Final balance must be exactly 0.
        """
        self.require_app()
        customer_email = f"concurrency_{uuid.uuid4().hex[:6]}@acme.ai"
        
        # Issue community license and adjust to 15 credits
        data = self.issue_license_api(customer_email=customer_email, tier="community")
        license_key = data["license_key"]
        
        # Deduct 10 credits so balance becomes 15 (25 - 10 = 15)
        prep = self.deduct_quota_api(license_key=license_key, credits=10)
        self.assertEqual(prep.status_code, 200)

        # Fire 10 concurrent 5-credit debit requests
        def attempt_debit():
            return self.deduct_quota_api(
                license_key=license_key,
                credits=5,
                idempotency_key=str(uuid.uuid4())
            ).status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(attempt_debit) for _ in range(10)]
            results = [f.result() for f in futures]

        success_count = results.count(200)
        paywall_count = results.count(402)

        self.assertEqual(success_count, 3, f"Exactly 3 debits must succeed (got {success_count})")
        self.assertEqual(paywall_count, 7, f"Exactly 7 debits must fail with 402 (got {paywall_count})")

        # Check final balance is 0
        bal_res = self.client.get(f"/api/v1/quota/balance?license_key={license_key}")
        bal = bal_res.json().get("data", bal_res.json()).get("credit_balance")
        self.assertEqual(bal, 0, f"Final balance must be exactly 0 (got {bal})")

    def test_pair4_webhook_replay_deduplication(self):
        """Ingest identical event ID 5 times. First processes; subsequent 4 return cached 200 OK."""
        self.require_app()
        event_id = f"evt_replay_{uuid.uuid4().hex}"
        event_body = {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer_email": "replay_dedup@acme.ai",
                    "metadata": {"tier": "pro"},
                    "payment_status": "paid"
                }
            }
        }
        raw_body = json.dumps(event_body).encode("utf-8")
        sig = generate_stripe_signature(raw_body, TEST_STRIPE_WEBHOOK_SECRET)
        headers = {"Stripe-Signature": sig, "Content-Type": "application/json"}

        statuses = []
        for _ in range(5):
            res = self.client.post("/api/v1/webhooks/stripe", content=raw_body, headers=headers)
            statuses.append(res.status_code)

        # All 5 requests must return 200 OK
        self.assertEqual(statuses, [200, 200, 200, 200, 200], "Replays must all return 200 OK")

    def test_pair5_subscription_cancellation_instant_lockout(self):
        """Subscription cancelled -> License revoked -> Online verification fails."""
        self.require_app()
        customer_email = f"lockout_{uuid.uuid4().hex[:6]}@acme.ai"
        
        # 1. Issue Pro license
        data = self.issue_license_api(customer_email=customer_email, tier="pro")
        license_key = data["license_key"]

        # Confirm initially valid
        ver1 = self.verify_license_api(license_key=license_key)
        self.assertEqual(ver1.status_code, 200)

        # 2. Ingest subscription cancellation webhook
        self.simulate_webhook_api(
            event_type="customer.subscription.deleted",
            customer_email=customer_email,
            tier="community"
        )

        # 3. Subsequent verification returns revoked / invalid
        ver2 = self.verify_license_api(license_key=license_key)
        self.assertEqual(ver2.status_code, 200)
        payload = ver2.json().get("data", ver2.json())
        self.assertFalse(payload.get("valid"))
        self.assertEqual(payload.get("status"), "revoked")

    def test_pair6_rate_limiter_precedes_credit_deduction(self):
        """Rate limit rejection (429) must short-circuit BEFORE deducting any credit balance."""
        from app.presentation.middlewares import rate_limiter

        self.require_app()
        # Request #1 in 25-req window
        data = self.issue_license_api(customer_email="rate_precede@acme.ai", tier="community")
        license_key = data["license_key"]

        # Requests #2..#25 (24 balance reads) saturate the sliding window
        for _ in range(24):
            r = self.client.get(f"/api/v1/quota/balance?license_key={license_key}")
            self.assertEqual(r.status_code, 200)

        # Next 5 quota deductions (5 credits each) MUST all be blocked with 429 BEFORE touching SQLite
        for _ in range(5):
            blocked = self.deduct_quota_api(license_key=license_key, credits=5)
            self.assertEqual(blocked.status_code, 429, f"Expected 429 rate limit: {blocked.text}")

        # Reset rate limiter window and verify balance is still untouched at 25 (zero credits lost!)
        rate_limiter.reset()
        bal_res = self.client.get(f"/api/v1/quota/balance?license_key={license_key}")
        self.assertEqual(bal_res.status_code, 200)
        self.assertEqual(bal_res.json()["data"]["credit_balance"], 25)

        # Subsequent normal 1-credit deduction succeeds (25 -> 24)
        ok_deduct = self.deduct_quota_api(license_key=license_key, credits=1)
        self.assertEqual(ok_deduct.status_code, 200)
        self.assertEqual(ok_deduct.json()["data"]["remaining_balance"], 24)


if __name__ == "__main__":
    unittest.main()
