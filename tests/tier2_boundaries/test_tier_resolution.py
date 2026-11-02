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
            "indie": Tier.PRO, "Agency": Tier.STUDIO, "pro": Tier.PRO, "studio": Tier.STUDIO,
            "lifetime": Tier.LIFETIME, "Indie License": Tier.PRO, "KeyFlint Agency (one-time)": Tier.STUDIO,
            None: None, "": None, "gold": None, "indie or studio": None, "independent": None,
        }
        for raw, expected in cases.items():
            self.assertIs(_resolve_tier(raw), expected, raw)

    def _checkout(self, email: str, metadata: dict) -> dict:
        body = json.dumps({
            "id": f"evt_{uuid.uuid4().hex}",
            "type": "checkout.session.completed",
            "data": {"object": {"customer_details": {"email": email}, "metadata": metadata}},
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

    def test_indie_metadata_grants_pro_without_flag(self):
        self.require_app()
        data = self._checkout("indie@example.com", {"tier": "indie"})
        self.assertTrue(data["license_key"].startswith("LIC-PRO-"))
        self.assertNotIn("tier_unresolved", data)


if __name__ == "__main__":
    unittest.main()
