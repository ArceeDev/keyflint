"""Tier 1: the checkout success page can fetch the license bought in a Stripe Checkout session."""

from __future__ import annotations

import json
import unittest
import uuid
from unittest import mock

from tests.conftest import (
    BaseKeyFlintTestCase,
    TEST_STRIPE_WEBHOOK_SECRET,
    generate_stripe_signature,
)


class TestCheckoutLicenseReveal(BaseKeyFlintTestCase):

    def _post(self, event_type: str, obj: dict):
        raw = json.dumps({"id": f"evt_{uuid.uuid4().hex}", "type": event_type, "data": {"object": obj}}).encode("utf-8")
        headers = {"Stripe-Signature": generate_stripe_signature(raw, TEST_STRIPE_WEBHOOK_SECRET),
                   "Content-Type": "application/json"}
        return self.client.post("/api/v1/webhooks/stripe", content=raw, headers=headers)

    def _buy(self):
        cs, pi = f"cs_{uuid.uuid4().hex[:16]}", f"pi_{uuid.uuid4().hex[:12]}"
        res = self._post("checkout.session.completed", {
            "id": cs, "customer_email": "maria@acme.ai", "customer": f"cus_{uuid.uuid4().hex[:10]}",
            "metadata": {"tier": "pro"}, "payment_status": "paid", "mode": "payment", "payment_intent": pi,
        })
        self.assertEqual(res.status_code, 200, res.text)
        return cs, pi, res.json()["data"]["license_key"]

    def _reveal(self, cs: str):
        return self.client.get(f"/api/v1/billing/checkout/{cs}/license")

    def test_reveals_license_after_webhook(self):
        self.require_app()
        cs, _, key = self._buy()
        res = self._reveal(cs)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()["data"]
        self.assertEqual(data["license_key"], key)
        self.assertEqual(data["tier"], "pro")
        self.assertEqual(data["email_hint"], "m***@acme.ai")
        self.assertNotIn("maria", json.dumps(data))

    def test_unknown_session_is_pending(self):
        self.require_app()
        res = self._reveal(f"cs_{uuid.uuid4().hex[:16]}")
        self.assertEqual(res.status_code, 404, res.text)
        self.assertIn("CHECKOUT_PENDING", res.text)

    def test_malformed_session_id_rejected(self):
        self.require_app()
        for bad in ("pi_123456789012", "cs_short", "cs_" + "a" * 20 + "%27"):
            res = self._reveal(bad)
            self.assertIn(res.status_code, (400, 404), res.text)
            self.assertNotIn("license_key", res.text)
        res = self._reveal("sub_abcdefghijklmnop")
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("CHECKOUT_SESSION_INVALID", res.text)

    def test_expired_window(self):
        self.require_app()
        cs, _, _ = self._buy()
        from app.application.services import billing_service as bs
        real = bs.get_settings()
        fake = mock.Mock(wraps=real)
        fake.CHECKOUT_REVEAL_TTL_SECONDS = -1
        with mock.patch.object(bs, "get_settings", return_value=fake):
            res = self._reveal(cs)
        self.assertEqual(res.status_code, 410, res.text)
        self.assertIn("CHECKOUT_REVEAL_EXPIRED", res.text)

    def test_refunded_license_not_revealed(self):
        self.require_app()
        cs, pi, _ = self._buy()
        res = self._post("charge.refunded", {"id": f"ch_{uuid.uuid4().hex[:12]}", "object": "charge",
                                             "payment_intent": pi, "amount": 2900, "amount_refunded": 2900,
                                             "refunded": True})
        self.assertEqual(res.status_code, 200, res.text)
        res = self._reveal(cs)
        self.assertEqual(res.status_code, 410, res.text)
        self.assertIn("LICENSE_INACTIVE", res.text)


if __name__ == "__main__":
    unittest.main()
