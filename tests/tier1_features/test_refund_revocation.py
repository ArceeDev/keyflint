"""Tier 1: charge.refunded / charge.dispute.* revoke or suspend the purchased license."""

from __future__ import annotations

import json
import unittest
import uuid

from tests.conftest import (
    BaseKeyFlintTestCase,
    TEST_STRIPE_WEBHOOK_SECRET,
    generate_stripe_signature,
)


class TestStripeRefundRevocation(BaseKeyFlintTestCase):

    def _post(self, event_type: str, obj: dict, event_id: str | None = None, secret: str = TEST_STRIPE_WEBHOOK_SECRET):
        raw = json.dumps({
            "id": event_id or f"evt_{uuid.uuid4().hex}",
            "type": event_type,
            "data": {"object": obj},
        }).encode("utf-8")
        headers = {
            "Stripe-Signature": generate_stripe_signature(raw, secret),
            "Content-Type": "application/json",
        }
        return self.client.post("/api/v1/webhooks/stripe", content=raw, headers=headers)

    def _buy(self, email: str | None = None, mode: str = "payment"):
        email = email or f"buyer_{uuid.uuid4().hex[:6]}@acme.ai"
        pi = f"pi_{uuid.uuid4().hex[:12]}"
        cus = f"cus_{uuid.uuid4().hex[:10]}"
        obj = {
            "id": f"cs_{uuid.uuid4().hex[:12]}",
            "customer_email": email,
            "customer": cus,
            "metadata": {"tier": "pro"},
            "payment_status": "paid",
            "mode": mode,
        }
        if mode == "payment":
            obj["payment_intent"] = pi
        else:
            obj["subscription"] = f"sub_{uuid.uuid4().hex[:10]}"
        res = self._post("checkout.session.completed", obj)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["data"]["license_key"], pi, cus, email

    def _status(self, key: str) -> str:
        res = self.client.get(f"/api/v1/billing/status?license_key={key}")
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["data"]["status"]

    def _charge(self, pi: str, amount: int = 2900, refunded: int = 2900, **extra) -> dict:
        obj = {
            "id": f"ch_{uuid.uuid4().hex[:12]}",
            "object": "charge",
            "payment_intent": pi,
            "amount": amount,
            "amount_refunded": refunded,
            "refunded": refunded >= amount,
        }
        obj.update(extra)
        return obj

    def test_full_refund_revokes_by_payment_intent(self):
        self.require_app()
        key, pi, _, _ = self._buy()
        self.assertEqual(self._status(key), "active")
        res = self._post("charge.refunded", self._charge(pi))
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()["data"]
        self.assertEqual(data["license_status"], "revoked")
        self.assertEqual(data["reversal"]["matched_by"], pi)
        self.assertEqual(self._status(key), "revoked")

    def test_refund_is_idempotent(self):
        self.require_app()
        key, pi, _, _ = self._buy()
        evt = f"evt_{uuid.uuid4().hex}"
        first = self._post("charge.refunded", self._charge(pi), event_id=evt)
        second = self._post("charge.refunded", self._charge(pi), event_id=evt)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["data"].get("already_processed"))
        # A distinct event for an already-revoked license is also harmless.
        third = self._post("charge.refunded", self._charge(pi))
        self.assertEqual(third.status_code, 200, third.text)
        self.assertEqual(third.json()["data"]["license_status"], "revoked")
        self.assertEqual(self._status(key), "revoked")

    def test_partial_refund_keeps_license_active(self):
        self.require_app()
        key, pi, _, _ = self._buy()
        res = self._post("charge.refunded", self._charge(pi, amount=2900, refunded=1000))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["data"]["reversal"]["action"], "partial_refund_ignored")
        self.assertEqual(self._status(key), "active")
        # Second partial refund completing the total revokes.
        res2 = self._post("charge.refunded", self._charge(pi, amount=2900, refunded=2900))
        self.assertEqual(res2.json()["data"]["license_status"], "revoked")

    def test_invalid_signature_rejected(self):
        self.require_app()
        key, pi, _, _ = self._buy()
        res = self._post("charge.refunded", self._charge(pi), secret="whsec_wrong")
        self.assertIn(res.status_code, (400, 401, 403))
        self.assertEqual(self._status(key), "active")

    def test_subscription_refund_matches_by_customer(self):
        self.require_app()
        key, _, cus, _ = self._buy(mode="subscription")
        # Renewal charge: unknown payment_intent, same Stripe customer.
        res = self._post("charge.refunded", self._charge(f"pi_{uuid.uuid4().hex[:12]}", customer=cus))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["data"]["reversal"]["matched_by"], cus)
        self.assertEqual(self._status(key), "revoked")

    def test_refund_falls_back_to_billing_email(self):
        self.require_app()
        email = f"legacy_{uuid.uuid4().hex[:6]}@acme.ai"
        key, _, _, _ = self._buy(email=email)
        res = self._post(
            "charge.refunded",
            self._charge(f"pi_{uuid.uuid4().hex[:12]}", billing_details={"email": email}),
        )
        self.assertEqual(res.json()["data"]["reversal"]["matched_by"], "email")
        self.assertEqual(self._status(key), "revoked")

    def test_unmatched_refund_is_acknowledged(self):
        self.require_app()
        key, _, _, _ = self._buy()
        res = self._post("charge.refunded", self._charge(f"pi_{uuid.uuid4().hex[:12]}"))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["data"]["reversal"]["action"], "no_matching_license")
        self.assertEqual(self._status(key), "active")

    def test_dispute_suspends_then_won_reinstates(self):
        self.require_app()
        key, pi, _, _ = self._buy()
        dispute = {"id": f"dp_{uuid.uuid4().hex[:10]}", "charge": "ch_x", "payment_intent": pi, "status": "needs_response"}
        res = self._post("charge.dispute.created", dispute)
        self.assertEqual(res.json()["data"]["license_status"], "suspended")
        self.assertEqual(self._status(key), "suspended")
        res2 = self._post("charge.dispute.closed", {**dispute, "status": "won"})
        self.assertEqual(res2.json()["data"]["license_status"], "active")
        self.assertEqual(self._status(key), "active")

    def test_dispute_lost_revokes(self):
        self.require_app()
        key, pi, _, _ = self._buy()
        dispute = {"id": f"dp_{uuid.uuid4().hex[:10]}", "payment_intent": pi, "status": "needs_response"}
        self._post("charge.dispute.created", dispute)
        res = self._post("charge.dispute.closed", {**dispute, "status": "lost"})
        self.assertEqual(res.json()["data"]["license_status"], "revoked")
        self.assertEqual(self._status(key), "revoked")


if __name__ == "__main__":
    unittest.main()
