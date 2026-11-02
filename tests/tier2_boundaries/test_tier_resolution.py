"""Tier 2: an unknown or missing product tier never grants a paid tier."""

from __future__ import annotations

import json
import unittest
import uuid

from app.application.services.billing_service import _resolve_tier
from app.domain.entities.license import Tier
from tests.conftest import BaseKeyFlintTestCase, TEST_STRIPE_WEBHOOK_SECRET, generate_stripe_signature


class TestTierResolution(BaseKeyFlintTestCase):
    def test_aliases_and_product_names(self):
        cases = {
            "indie": Tier.INDIE, "Agency": Tier.AGENCY, "pro": Tier.PRO, "studio": Tier.STUDIO,
            "lifetime": Tier.LIFETIME, "Indie License": Tier.INDIE, "KeyFlint Agency (one-time)": Tier.AGENCY,
            None: None, "": None, "gold": None, "indie or studio": None, "independent": None,
        }
        for raw, expected in cases.items():
            self.assertIs(_resolve_tier(raw), expected, raw)

    def _checkout(self, email: str, metadata: dict, **amounts) -> dict:
        obj = {"customer_details": {"email": email}, "metadata": metadata, **amounts}
        body = json.dumps({
            "id": f"evt_{uuid.uuid4().hex}",
            "type": "checkout.session.completed",
            "data": {"object": obj},
        }).encode()
        res = self.client.post(
            "/api/v1/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": generate_stripe_signature(body, TEST_STRIPE_WEBHOOK_SECRET)},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["data"]

    def test_missing_tier_issues_community_and_flags(self):
        self.require_app()
        data = self._checkout("no.tier@example.com", {})
        self.assertTrue(data["license_key"].startswith("LIC-COMMUNITY-"))
        self.assertEqual(data["tier_unresolved"], "missing")

    def test_unknown_tier_does_not_downgrade_existing_license(self):
        self.require_app()
        first = self._checkout("has.pro@example.com", {"tier": "studio"})
        self.assertTrue(first["license_key"].startswith("LIC-STUDIO-"))
        second = self._checkout("has.pro@example.com", {"tier": "gold"})
        self.assertEqual(second["tier_unresolved"], "gold")
        self.assertNotEqual(first["license_key"], second["license_key"])
        status = self.client.get("/api/v1/billing/status", params={"license_key": first["license_key"]})
        self.assertEqual(status.status_code, 200, status.text)
        self.assertIn("studio", status.text.lower())

    def test_indie_metadata_grants_indie_without_flag(self):
        self.require_app()
        data = self._checkout("indie@example.com", {"tier": "indie"})
        self.assertTrue(data["license_key"].startswith("LIC-INDIE-"))
        self.assertNotIn("tier_unresolved", data)

    def test_price_inference_uses_exact_pretax_usd_subtotal(self):
        self.require_app()
        # Studio $89 + 21% VAT: amount_total would look like Indie; subtotal is exact.
        studio = self._checkout("vat@example.com", {}, amount_subtotal=8900, amount_total=10769, currency="usd")
        self.assertTrue(studio["license_key"].startswith("LIC-STUDIO-"))
        self.assertNotIn("tier_unresolved", studio)
        for email, amounts in {
            "one@example.com": {"amount_subtotal": 100, "amount_total": 100, "currency": "usd"},
            "eur@example.com": {"amount_subtotal": 14900, "amount_total": 14900, "currency": "eur"},
            "big@example.com": {"amount_total": 50000, "currency": "usd"},
        }.items():
            data = self._checkout(email, {}, **amounts)
            self.assertTrue(data["license_key"].startswith("LIC-COMMUNITY-"), email)
            self.assertEqual(data["tier_unresolved"], "missing", email)


if __name__ == "__main__":
    unittest.main()
