"""Tier 1: Plan Despacho (49/99/149 €/mes) se emite con su tier, créditos y renovación mensual."""

from __future__ import annotations

import json
import unittest
import uuid

from tests.conftest import (
    BaseKeyFlintTestCase,
    TEST_STRIPE_WEBHOOK_SECRET,
    generate_stripe_signature,
)


class TestDespachoPlan(BaseKeyFlintTestCase):

    def _post(self, event_type: str, obj: dict):
        raw = json.dumps({
            "id": f"evt_{uuid.uuid4().hex}",
            "type": event_type,
            "data": {"object": obj},
        }).encode("utf-8")
        headers = {
            "Stripe-Signature": generate_stripe_signature(raw, TEST_STRIPE_WEBHOOK_SECRET),
            "Content-Type": "application/json",
        }
        return self.client.post("/api/v1/webhooks/stripe", content=raw, headers=headers)

    def _buy(self, metadata: dict, amount_total: int | None = None):
        email = f"despacho_{uuid.uuid4().hex[:6]}@gestoria.es"
        obj = {
            "id": f"cs_{uuid.uuid4().hex[:12]}",
            "customer_email": email,
            "customer": f"cus_{uuid.uuid4().hex[:10]}",
            "metadata": metadata,
            "payment_status": "paid",
            "mode": "subscription",
            "subscription": f"sub_{uuid.uuid4().hex[:10]}",
        }
        if amount_total is not None:
            obj["amount_subtotal"] = amount_total
            obj["currency"] = "eur"
        res = self._post("checkout.session.completed", obj)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["data"], obj

    def _status(self, key: str) -> dict:
        res = self.client.get(f"/api/v1/billing/status?license_key={key}")
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["data"]

    def test_each_despacho_tier_issues_paid_license(self):
        self.require_app()
        for tier, credits in (("despacho_basico", 2500), ("despacho_pro", 6000), ("despacho_empresa", 15000)):
            with self.subTest(tier=tier):
                data, _ = self._buy({"tier": tier, "source": "mcp-hub"})
                self.assertIn("license_key", data, data)
                st = self._status(data["license_key"])
                self.assertEqual(st["tier"], tier, st)
                self.assertEqual(st["status"], "active", st)
                self.assertEqual(st["credit_balance"], credits, st)

    def test_despacho_never_falls_back_to_community(self):
        self.require_app()
        data, _ = self._buy({"tier": "Despacho Pro"})
        st = self._status(data["license_key"])
        self.assertNotEqual(st["tier"], "community", st)
        self.assertEqual(st["tier"], "despacho_pro", st)

    def test_despacho_by_amount_without_metadata(self):
        self.require_app()
        data, _ = self._buy({}, amount_total=9900)
        st = self._status(data["license_key"])
        self.assertEqual(st["tier"], "despacho_pro", st)

    def test_monthly_renewal_refills_and_cancel_stops(self):
        self.require_app()
        data, obj = self._buy({"tier": "despacho_basico"})
        key = data["license_key"]
        cons = self.deduct_quota_api(key, 100)
        self.assertIn(cons.status_code, (200, 201), cons.text)
        self.assertEqual(self._status(key)["credit_balance"], 2400)
        inv = {"id": f"in_{uuid.uuid4().hex[:10]}", "subscription": obj["subscription"],
               "customer": obj["customer"], "customer_email": obj["customer_email"]}
        res = self._post("invoice.payment_succeeded", inv)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self._status(key)["credit_balance"], 2500)
        res = self._post("customer.subscription.deleted", {"id": obj["subscription"], "customer": obj["customer"],
                                                           "customer_email": obj["customer_email"]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotEqual(self._status(key)["status"], "active")

    def test_migration_widens_tier_check_on_existing_db(self):
        import pathlib
        import sqlite3

        from app.infrastructure.database.migrations import run_migrations

        schema = pathlib.Path("app/infrastructure/database/schemas.sql").read_text()
        old = schema.replace(", 'despacho_basico', 'despacho_pro', 'despacho_empresa'", "")
        conn = sqlite3.connect(":memory:", isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.executescript(old)
        conn.execute("INSERT INTO customers(id, email) VALUES ('c1', 'a@b.es')")
        conn.execute("INSERT INTO licenses(id, customer_id, license_key, tier, status, signature) "
                     "VALUES ('l1', 'c1', 'K1', 'pro', 'active', 's')")
        run_migrations(conn)
        conn.execute("INSERT INTO licenses(id, customer_id, license_key, tier, status, signature) "
                     "VALUES ('l2', 'c1', 'K2', 'despacho_pro', 'active', 's')")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM licenses").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
