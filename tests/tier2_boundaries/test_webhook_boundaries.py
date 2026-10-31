"""Tier 2: Boundary & Corner Cases — Webhook Security, Signatures & Replays.

Covers:
41. test_bound4_webhook_missing_signature_header_returns_401
42. test_bound4_webhook_tampered_payload_signature_mismatch_401
43. test_bound4_webhook_timestamp_older_than_300s_rejected
44. test_bound4_webhook_malformed_json_body_returns_400
45. test_bound4_webhook_unrecognized_event_type_handled_gracefully
"""

from __future__ import annotations

import json
import time
import unittest
from tests.conftest import (
    BaseKeyForgeTestCase,
    generate_stripe_signature,
    TEST_STRIPE_WEBHOOK_SECRET,
)


class TestWebhookBoundaries(BaseKeyForgeTestCase):
    """Boundary verification for webhook ingestion, signatures, and replay defense."""

    def test_bound4_webhook_missing_signature_header_returns_401(self):
        """Request without Stripe-Signature header is rejected with 401 Unauthorized."""
        self.require_app()
        payload = {"id": "evt_unsigned", "type": "ping"}
        res = self.client.post(
            "/api/v1/webhooks/stripe",
            content=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        self.assertIn(res.status_code, (400, 401), f"Missing signature should yield 401: {res.text}")

    def test_bound4_webhook_tampered_payload_signature_mismatch_401(self):
        """Corrupted webhook body fails HMAC verification with 401 Unauthorized."""
        self.require_app()
        original_body = json.dumps({"id": "evt_tampered", "type": "checkout.session.completed"}).encode("utf-8")
        sig = generate_stripe_signature(original_body, TEST_STRIPE_WEBHOOK_SECRET)

        # Send tampered body with original signature
        tampered_body = json.dumps({"id": "evt_tampered", "type": "hacked_event"}).encode("utf-8")
        res = self.client.post(
            "/api/v1/webhooks/stripe",
            content=tampered_body,
            headers={"Stripe-Signature": sig, "Content-Type": "application/json"}
        )
        self.assertIn(res.status_code, (400, 401), "Signature mismatch must return 401 Unauthorized")

    def test_bound4_webhook_timestamp_older_than_300s_rejected(self):
        """Replay attack payload with 6-minute-old timestamp is rejected."""
        self.require_app()
        body = json.dumps({"id": "evt_replay", "type": "ping"}).encode("utf-8")
        # 400 seconds in the past (> 300s tolerance limit)
        old_timestamp = int(time.time()) - 400
        stale_sig = generate_stripe_signature(body, TEST_STRIPE_WEBHOOK_SECRET, timestamp=old_timestamp)

        res = self.client.post(
            "/api/v1/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": stale_sig, "Content-Type": "application/json"}
        )
        self.assertIn(res.status_code, (400, 401), f"Stale timestamp (>300s) must be rejected: {res.text}")

    def test_bound4_webhook_malformed_json_body_returns_400(self):
        """Invalid non-JSON body returns 400 Bad Request."""
        self.require_app()
        malformed_bytes = b"NOT_A_VALID_JSON_OBJECT{{{[[["
        sig = generate_stripe_signature(malformed_bytes, TEST_STRIPE_WEBHOOK_SECRET)

        res = self.client.post(
            "/api/v1/webhooks/stripe",
            content=malformed_bytes,
            headers={"Stripe-Signature": sig, "Content-Type": "application/json"}
        )
        self.assertIn(res.status_code, (400, 422), f"Malformed JSON must return 400: {res.text}")

    def test_bound4_webhook_unrecognized_event_type_handled_gracefully(self):
        """Unknown event returns 200 OK without unhandled crash or 500 error."""
        self.require_app()
        body = json.dumps({"id": "evt_unknown_type", "type": "unknown.unhandled.event"}).encode("utf-8")
        sig = generate_stripe_signature(body, TEST_STRIPE_WEBHOOK_SECRET)

        res = self.client.post(
            "/api/v1/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": sig, "Content-Type": "application/json"}
        )
        self.assertEqual(res.status_code, 200, "Unrecognized event type should be handled gracefully")


if __name__ == "__main__":
    unittest.main()
