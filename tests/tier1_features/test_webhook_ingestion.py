"""Tier 1: Feature Coverage — Feature 4: Webhook Event Ingestion & Provisioning (FEAT-WH-01).

Covers:
16. test_feat4_checkout_completed_provisions_pro_account
17. test_feat4_checkout_completed_issues_signed_license_key
18. test_feat4_subscription_renewed_replenishes_quota
19. test_feat4_subscription_deleted_downgrades_to_community
20. test_feat4_valid_stripe_hmac_signature_accepted
+ Native LemonSqueezy HMAC webhooks, Stripe multi-v1 secret rotation, and re-signed tier upgrades
"""

from __future__ import annotations

import json
import time
import unittest
import uuid

from tests.conftest import (
    BaseKeyForgeTestCase,
    TEST_ED25519_PUBLIC_KEY_HEX,
    TEST_LEMONSQUEEZY_WEBHOOK_SECRET,
    TEST_STRIPE_WEBHOOK_SECRET,
    decode_license_token,
    generate_lemonsqueezy_signature,
    generate_stripe_signature,
    verify_payload_ed25519,
)


class TestWebhookIngestion(BaseKeyForgeTestCase):
    """E2E Verification for FEAT-WH-01: Multi-Provider Webhook Ingestion."""

    def test_feat4_checkout_completed_provisions_pro_account(self):
        """Ingesting checkout.session.completed provisions Pro license with 3 seats and 500 credits."""
        self.require_app()
        customer_email = f"buyer_{uuid.uuid4().hex[:6]}@acme.ai"
        event_payload = {
            "id": f"evt_{uuid.uuid4().hex}",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer_email": customer_email,
                    "metadata": {"tier": "pro"},
                    "payment_status": "paid",
                }
            },
        }
        raw_body = json.dumps(event_payload).encode("utf-8")
        headers = {
            "Stripe-Signature": generate_stripe_signature(raw_body, TEST_STRIPE_WEBHOOK_SECRET),
            "Content-Type": "application/json",
        }

        res = self.client.post("/api/v1/webhooks/stripe", content=raw_body, headers=headers)
        self.assertEqual(res.status_code, 200, f"Webhook ingestion failed: {res.text}")
        data = res.json()["data"]
        key = data["license_key"]
        self.assertTrue(key.startswith("LIC-PRO-"))

        status_res = self.client.get(f"/api/v1/billing/status?license_key={key}")
        self.assertEqual(status_res.status_code, 200)
        st = status_res.json()["data"]
        self.assertEqual(st["tier"], "pro")
        self.assertEqual(st["credit_balance"], 500)

    def test_feat4_checkout_completed_issues_signed_license_key(self):
        """Checkout webhook automatically generates and stores valid Ed25519-signed license key."""
        self.require_app()
        customer_email = f"licensee_{uuid.uuid4().hex[:6]}@acme.ai"
        res = self.simulate_webhook_api(
            event_type="checkout.session.completed",
            customer_email=customer_email,
            tier="pro",
        )
        self.assertEqual(res.status_code, 200, f"Simulate webhook failed: {res.text}")
        payload = res.json()["data"]

        license_key = payload.get("license_key")
        self.assertIsNotNone(license_key, "Webhook must return signed license_key")
        self.assertTrue(license_key.startswith("LIC-PRO-"))
        tier, tok_payload, sig_b64 = decode_license_token(license_key)
        self.assertEqual(tier, "pro")
        self.assertTrue(verify_payload_ed25519(tok_payload, sig_b64, TEST_ED25519_PUBLIC_KEY_HEX))

    def test_feat4_subscription_renewed_replenishes_quota(self):
        """invoice.payment_succeeded resets monthly balance to 500 without inflating total_allowance to 1000."""
        self.require_app()
        customer_email = f"renew_{uuid.uuid4().hex[:6]}@acme.ai"
        prov_res = self.simulate_webhook_api(
            event_type="checkout.session.completed",
            customer_email=customer_email,
            tier="pro",
        )
        license_key = prov_res.json()["data"]["license_key"]

        # Consume 120 credits -> remaining 380
        ded = self.deduct_quota_api(license_key=license_key, credits=120)
        self.assertEqual(ded.status_code, 200)
        self.assertEqual(ded.json()["data"]["remaining_balance"], 380)

        # Trigger billing cycle renewal
        res = self.simulate_webhook_api(
            event_type="invoice.payment_succeeded",
            customer_email=customer_email,
            tier="pro",
        )
        self.assertEqual(res.status_code, 200)

        bal = self.client.get(f"/api/v1/quota/balance?license_key={license_key}").json()["data"]
        self.assertEqual(bal["credit_balance"], 500, "Cycle renewal must reset balance to 500 (not 880 or 1000)")
        self.assertEqual(bal["total_allowance"], 500, "total_allowance must stay 500 on cycle reset")
        self.assertEqual(bal["consumed"], 0, "Cycle consumed counter must reset to 0")

    def test_feat4_subscription_deleted_downgrades_to_community(self):
        """customer.subscription.deleted revokes Pro license and blocks further quota deductions."""
        self.require_app()
        customer_email = f"cancel_{uuid.uuid4().hex[:6]}@acme.ai"
        prov_res = self.simulate_webhook_api(
            event_type="checkout.session.completed",
            customer_email=customer_email,
            tier="pro",
        )
        license_key = prov_res.json()["data"]["license_key"]

        res = self.simulate_webhook_api(
            event_type="customer.subscription.deleted",
            customer_email=customer_email,
            tier="community",
        )
        self.assertEqual(res.status_code, 200)

        ver = self.verify_license_api(license_key=license_key)
        self.assertFalse(ver.json()["data"]["valid"])
        self.assertEqual(ver.json()["data"]["status"], "revoked")

        ded = self.deduct_quota_api(license_key=license_key, credits=1)
        self.assertEqual(ded.status_code, 403)

    def test_feat4_valid_stripe_hmac_signature_accepted(self):
        """Valid Stripe-Signature header (including multi-v1 secret rotation) passes verification."""
        self.require_app()
        ts = int(time.time())
        event_payload = {
            "id": f"evt_valid_{uuid.uuid4().hex}",
            "type": "ping",
            "created": ts,
        }
        raw_body = json.dumps(event_payload).encode("utf-8")
        old_sig = generate_stripe_signature(raw_body, "whsec_retired_secret_000", timestamp=ts).split("v1=")[1]
        active_sig = generate_stripe_signature(raw_body, TEST_STRIPE_WEBHOOK_SECRET, timestamp=ts).split("v1=")[1]
        rotated_header = f"t={ts},v1={old_sig},v1={active_sig}"

        res = self.client.post(
            "/api/v1/webhooks/stripe",
            content=raw_body,
            headers={"Stripe-Signature": rotated_header, "Content-Type": "application/json"},
        )
        self.assertEqual(res.status_code, 200, f"Rotated v1 signature rejected: {res.text}")

    def test_lemonsqueezy_native_webhook_and_tier_upgrade_resigning(self):
        """Native LemonSqueezy payload provisions & upgrades tier with re-signed LIC-STUDIO token."""
        self.require_app()
        email = f"ls_founder_{uuid.uuid4().hex[:6]}@acme.ai"
        comm = self.issue_license_api(customer_email=email, tier="community")
        old_key = comm["license_key"]

        ls_payload = {
            "meta": {
                "event_name": "order_created",
                "webhook_id": f"ls_evt_{uuid.uuid4().hex}",
                "custom_data": {"tier": "studio"},
            },
            "data": {
                "id": "ord_9912",
                "type": "orders",
                "attributes": {
                    "user_email": email,
                    "variant_name": "Studio Plan",
                    "status": "paid",
                },
            },
        }
        raw = json.dumps(ls_payload).encode("utf-8")
        sig = generate_lemonsqueezy_signature(raw, TEST_LEMONSQUEEZY_WEBHOOK_SECRET)

        res = self.client.post(
            "/api/v1/webhooks/lemonsqueezy",
            content=raw,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        new_key = res.json()["data"]["license_key"]
        self.assertTrue(new_key.startswith("LIC-STUDIO-"))
        self.assertNotEqual(new_key, old_key)

        ver = self.verify_license_api(license_key=new_key).json()["data"]
        self.assertTrue(ver["valid"])
        self.assertEqual(ver["tier"], "studio")
        self.assertEqual(ver["max_seats"], 25)

        bal = self.client.get(f"/api/v1/quota/balance?license_key={new_key}").json()["data"]
        self.assertEqual(bal["credit_balance"], 5000)


if __name__ == "__main__":
    unittest.main()
