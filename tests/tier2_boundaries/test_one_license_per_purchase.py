"""Tier 2: every paid purchase gets its own license; repeat buyers never lose a tier."""

from __future__ import annotations

import json
import unittest
import uuid

from tests.conftest import BaseKeyFlintTestCase, TEST_STRIPE_WEBHOOK_SECRET, generate_stripe_signature


class TestOneLicensePerPurchase(BaseKeyFlintTestCase):
    def _event(self, event_type: str, obj: dict) -> dict:
        body = json.dumps({"id": f"evt_{uuid.uuid4().hex}", "type": event_type, "data": {"object": obj}}).encode()
        res = self.client.post(
            "/api/v1/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": generate_stripe_signature(body, TEST_STRIPE_WEBHOOK_SECRET)},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["data"]

    def _buy(self, email: str, tier: str, **refs) -> str:
        obj = {"id": f"cs_{uuid.uuid4().hex[:12]}", "customer_details": {"email": email}, "metadata": {"tier": tier}, **refs}
        return self._event("checkout.session.completed", obj)["license_key"]

    def _verify(self, key: str) -> dict:
        return self.verify_license_api(license_key=key).json()["data"]

    def test_lower_tier_purchase_does_not_downgrade(self):
        self.require_app()
        email = f"agency_{uuid.uuid4().hex[:6]}@example.com"
        agency = self._buy(email, "agency", payment_intent=f"pi_{uuid.uuid4().hex[:12]}")
        indie = self._buy(email, "indie", payment_intent=f"pi_{uuid.uuid4().hex[:12]}")
        self.assertNotEqual(agency, indie)
        self.assertEqual(self._verify(agency)["tier"], "agency")
        self.assertTrue(self._verify(agency)["valid"])
        self.assertEqual(self._verify(indie)["tier"], "indie")

    def test_same_tier_twice_gives_two_independent_quotas(self):
        self.require_app()
        email = f"twice_{uuid.uuid4().hex[:6]}@example.com"
        first = self._buy(email, "indie")
        self.assertEqual(self.deduct_quota_api(license_key=first, credits=100).status_code, 200)
        second = self._buy(email, "indie")
        self.assertNotEqual(first, second)
        bal1 = self.client.get(f"/api/v1/quota/balance?license_key={first}").json()["data"]["credit_balance"]
        bal2 = self.client.get(f"/api/v1/quota/balance?license_key={second}").json()["data"]["credit_balance"]
        self.assertEqual(bal1, bal2 - 100)

    def test_free_community_license_is_promoted_in_place(self):
        self.require_app()
        email = f"free_{uuid.uuid4().hex[:6]}@example.com"
        free = self.issue_license_api(customer_email=email, tier="community")
        paid = self._buy(email, "pro")
        self.assertTrue(paid.startswith("LIC-PRO-"))
        # Same license, re-signed: the key already shipped keeps working with the Pro allowance.
        bal = self.client.get(f"/api/v1/quota/balance?license_key={free['license_key']}").json()["data"]
        self.assertEqual(bal["credit_balance"], 500)

    def test_refund_revokes_only_that_purchase(self):
        self.require_app()
        email = f"refund_{uuid.uuid4().hex[:6]}@example.com"
        pi_a, pi_b = f"pi_{uuid.uuid4().hex[:12]}", f"pi_{uuid.uuid4().hex[:12]}"
        a = self._buy(email, "indie", payment_intent=pi_a)
        b = self._buy(email, "agency", payment_intent=pi_b)
        self._event("charge.refunded", {"id": f"ch_{uuid.uuid4().hex[:12]}", "payment_intent": pi_a,
                                        "amount": 14900, "amount_refunded": 14900, "refunded": True})
        self.assertEqual(self._verify(a)["status"], "revoked")
        self.assertTrue(self._verify(b)["valid"])

    def test_refund_matched_only_by_email_with_several_licenses_changes_nothing(self):
        self.require_app()
        email = f"ambig_{uuid.uuid4().hex[:6]}@example.com"
        a = self._buy(email, "indie")
        b = self._buy(email, "indie")
        out = self._event("charge.refunded", {"id": f"ch_{uuid.uuid4().hex[:12]}", "billing_details": {"email": email},
                                              "amount": 14900, "amount_refunded": 14900, "refunded": True})
        self.assertEqual(out["reversal"]["matched_by"], "ambiguous_email")
        self.assertTrue(self._verify(a)["valid"])
        self.assertTrue(self._verify(b)["valid"])

    def test_subscription_cancel_spares_perpetual_licenses(self):
        self.require_app()
        email = f"mixed_{uuid.uuid4().hex[:6]}@example.com"
        sub = f"sub_{uuid.uuid4().hex[:12]}"
        indie = self._buy(email, "indie")
        pro = self._buy(email, "pro", subscription=sub)
        other_pro = self._buy(email, "pro", subscription=f"sub_{uuid.uuid4().hex[:12]}")
        self._event("customer.subscription.deleted", {"id": sub, "customer_email": email})
        self.assertEqual(self._verify(pro)["status"], "revoked")
        self.assertTrue(self._verify(indie)["valid"])
        self.assertTrue(self._verify(other_pro)["valid"])

    def test_subscription_cancel_by_email_only_touches_recurring_tiers(self):
        self.require_app()
        email = f"legacy_{uuid.uuid4().hex[:6]}@example.com"
        indie = self._buy(email, "indie")
        pro = self._buy(email, "pro")
        self.simulate_webhook_api(event_type="customer.subscription.deleted", customer_email=email, tier="pro")
        self.assertEqual(self._verify(pro)["status"], "revoked")
        self.assertTrue(self._verify(indie)["valid"])


if __name__ == "__main__":
    unittest.main()
