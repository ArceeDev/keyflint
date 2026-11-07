"""Tier 1: pay-as-you-go top-ups add credits to the SAME license key, and reverse cleanly."""

from __future__ import annotations

import json
import unittest
import uuid

from tests.conftest import (
    BaseKeyFlintTestCase,
    TEST_STRIPE_WEBHOOK_SECRET,
    generate_stripe_signature,
)


class TestTopupPricing(unittest.TestCase):
    def test_credit_table(self):
        from app.application.services.topup_pricing import topup_credits, validate_topup_amount

        cases = {500: 100, 800: 160, 1900: 380, 2000: 440, 3700: 814, 4900: 1078,
                 5000: 1250, 9900: 2475, 10000: 2800, 50000: 14000, 499: 0}
        for cents, credits in cases.items():
            self.assertEqual(topup_credits(cents), credits, cents)
        self.assertEqual(validate_topup_amount(3700, "EUR"), (3700, "eur"))
        for bad in ((400, "eur"), (50100, "eur"), (550, "eur"), (1000, "gbp"), ("1000", "eur"), (True, "eur")):
            with self.assertRaises(ValueError):
                validate_topup_amount(*bad)


class TestTopupFlow(BaseKeyFlintTestCase):

    def _post(self, event_type: str, obj: dict, event_id: str | None = None):
        raw = json.dumps({"id": event_id or f"evt_{uuid.uuid4().hex}", "type": event_type,
                          "data": {"object": obj}}).encode("utf-8")
        headers = {"Stripe-Signature": generate_stripe_signature(raw, TEST_STRIPE_WEBHOOK_SECRET),
                   "Content-Type": "application/json"}
        res = self.client.post("/api/v1/webhooks/stripe", content=raw, headers=headers)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["data"]

    def _balance(self, key: str) -> int:
        return self.client.get(f"/api/v1/billing/status?license_key={key}").json()["data"]["credit_balance"]

    def _status(self, key: str) -> str:
        return self.client.get(f"/api/v1/billing/status?license_key={key}").json()["data"]["status"]

    def _license(self, tier: str = "community") -> str:
        return self.issue_license_api(customer_email=f"t_{uuid.uuid4().hex[:6]}@acme.ai", tier=tier)["license_key"]

    def _checkout(self, key: str, cents: int = 3700, currency: str = "eur", **extra):
        return self.client.post("/api/v1/billing/topup",
                                json={"license_key": key, "amount_cents": cents, "currency": currency, **extra})

    def _pay(self, key: str, cents: int = 3700, payment_status: str = "paid",
             event_type: str = "checkout.session.completed"):
        res = self._checkout(key, cents)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()["data"]
        session = {
            "id": "cs_" + uuid.uuid4().hex,
            "object": "checkout.session",
            "payment_status": payment_status,
            "payment_intent": "pi_" + uuid.uuid4().hex[:16],
            "currency": data["currency"],
            "amount_subtotal": cents,
            "amount_total": cents,
            "metadata": data["metadata"],
            "customer_details": {"email": "someone@else.ai"},
        }
        return session, self._post(event_type, session)

    def test_checkout_quotes_credits_and_validates(self):
        key = self._license()
        res = self._checkout(key, 3700)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()["data"]
        self.assertEqual((data["credits"], data["bonus_percent"]), (814, 10))
        self.assertNotIn(key, json.dumps(data["metadata"]))  # Stripe only sees the license id
        self.assertEqual(self._checkout(key, 400).status_code, 400)
        self.assertEqual(self._checkout(key, 1000, "gbp").status_code, 400)
        self.assertEqual(self._checkout(key, 1000, return_url="https://evil.example/saldo/").status_code, 400)
        self.assertEqual(self._checkout(key, 1000, return_url="https://mcp.keyflint.dev.evil.io/").status_code, 400)
        self.assertEqual(self._checkout(key, 1000, return_url="https://mcp.keyflint.dev/en/balance/").status_code, 200)
        self.assertEqual(self._checkout("LIC-" + "x" * 40, 1000).status_code, 404)

    def test_paid_topup_adds_credits_to_same_key_once(self):
        key = self._license()
        self.assertEqual(self._balance(key), 25)
        session, out = self._pay(key, 3700)
        self.assertEqual(out["topup"]["action"], "applied")
        self.assertEqual(out["license_key"], key)
        self.assertNotIn("email_delivered", out)
        self.assertEqual(self._balance(key), 25 + 814)
        # Same session again under a new event id (Stripe retry / async duplicate): no double credit.
        again = self._post("checkout.session.completed", session)
        self.assertEqual(again["topup"]["action"], "already_applied")
        self.assertEqual(self._balance(key), 25 + 814)
        st = self.client.get(f"/api/v1/billing/topup/{session['id']}").json()["data"]
        self.assertEqual((st["status"], st["credits"], st["credit_balance"]), ("applied", 814, 839))
        self.assertEqual(self.client.get("/api/v1/billing/topup/cs_" + "a" * 20).json()["data"]["status"], "pending")
        self.assertEqual(self.client.get("/api/v1/billing/topup/nope").status_code, 400)

    def test_async_payment_waits_for_success_event(self):
        key = self._license()
        session, out = self._pay(key, 500, payment_status="unpaid")
        self.assertEqual(out["topup"]["action"], "awaiting_payment")
        self.assertEqual(self._balance(key), 25)
        session["payment_status"] = "paid"
        out = self._post("checkout.session.async_payment_succeeded", session)
        self.assertEqual(out["topup"]["action"], "applied")
        self.assertEqual(self._balance(key), 125)

    def test_topup_session_never_provisions_a_license(self):
        """A 29 USD top-up must not be mistaken for a Pro purchase by the price fallback."""
        key = self._license()
        res = self._checkout(key, 2900, "usd")
        meta = res.json()["data"]["metadata"]
        out = self._post("checkout.session.completed", {
            "id": "cs_" + uuid.uuid4().hex, "payment_status": "paid", "currency": "usd",
            "amount_subtotal": 2900, "metadata": meta, "customer_email": "x@acme.ai"})
        self.assertEqual(out["license_key"], key)
        self.assertEqual(self._balance(key), 25 + 638)

    def test_full_refund_removes_only_topup_credits(self):
        key = self._license("pro")
        session, _ = self._pay(key, 500)
        self.assertEqual(self._balance(key), 1100)
        out = self._post("charge.refunded", {"id": "ch_" + uuid.uuid4().hex[:12], "object": "charge",
                                             "payment_intent": session["payment_intent"],
                                             "amount": 500, "amount_refunded": 500, "refunded": True})
        self.assertEqual(out["reversal"]["action"], "topup_refunded")
        self.assertEqual(self._balance(key), 1000)
        self.assertEqual(self._status(key), "active")  # the license itself is never revoked

    def test_partial_refund_is_proportional(self):
        key = self._license()
        session, _ = self._pay(key, 5000)  # 1250 credits
        self._post("charge.refunded", {"id": "ch_x1", "payment_intent": session["payment_intent"],
                                       "amount": 5000, "amount_refunded": 1000, "refunded": False})
        self.assertEqual(self._balance(key), 25 + 1250 - 250)
        self._post("charge.refunded", {"id": "ch_x1", "payment_intent": session["payment_intent"],
                                       "amount": 5000, "amount_refunded": 5000, "refunded": True})
        self.assertEqual(self._balance(key), 25)

    def test_refund_after_spending_suspends(self):
        key = self._license()
        session, _ = self._pay(key, 500)
        self.assertEqual(self.deduct_quota_api(key, credits=120).status_code, 200)
        out = self._post("charge.refunded", {"id": "ch_y", "payment_intent": session["payment_intent"],
                                             "amount": 500, "amount_refunded": 500, "refunded": True})
        self.assertEqual(out["license_status"], "suspended")
        self.assertEqual(self._balance(key), 0)

    def test_dispute_holds_then_restores(self):
        key = self._license()
        session, _ = self._pay(key, 2000)  # 440
        dispute = {"id": "dp_1", "object": "dispute", "charge": "ch_d", "payment_intent": session["payment_intent"]}
        self._post("charge.dispute.created", dispute)
        self.assertEqual(self._balance(key), 25)
        self._post("charge.dispute.closed", {**dispute, "status": "won"})
        self.assertEqual(self._balance(key), 465)
        self.assertEqual(self._status(key), "active")

    def test_pro_renewal_keeps_unspent_topup(self):
        key = self._license("pro")
        self._pay(key, 500)  # +100 -> 1100
        self.assertEqual(self.deduct_quota_api(key, credits=950).status_code, 200)  # 150 left: 100 topup + 50 plan
        email = self.client.get(f"/api/v1/billing/status?license_key={key}").json()["data"]["customer_email"]
        self._post("invoice.payment_succeeded", {"id": "in_r", "customer_email": email,
                                                 "billing_reason": "subscription_cycle"})
        self.assertEqual(self._balance(key), 1000 + 100)
        self.assertEqual(self.deduct_quota_api(key, credits=1050).status_code, 200)  # 50 left, all top-up
        self._post("invoice.payment_succeeded", {"id": "in_r2", "customer_email": email,
                                                 "billing_reason": "subscription_cycle"})
        self.assertEqual(self._balance(key), 1000 + 50)

    def test_daily_limit_per_license(self):
        key = self._license()
        for _ in range(3):
            self._pay(key, 500)
        res = self._checkout(key, 500)
        self.assertEqual(res.status_code, 429, res.text)

    def test_revoked_license_cannot_top_up(self):
        key = self._license()
        self.client.post("/api/v1/licenses/revoke", json={"license_key": key, "reason": "test"})
        self.assertEqual(self._checkout(key, 500).status_code, 409)

    def test_community_license_never_expires(self):
        from app.domain.entities.license import Tier
        self.assertIsNone(Tier.COMMUNITY.default_expires_in_days)
        self.assertEqual(Tier.PRO.default_allowance, 1000)


if __name__ == "__main__":
    unittest.main()
