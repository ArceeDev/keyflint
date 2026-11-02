"""Tier 1: billing incidents that need a human email OPS_ALERT_EMAIL (and never break billing)."""

from __future__ import annotations

import json
import unittest
import uuid
from unittest import mock

from app.config import get_settings
from tests.conftest import BaseKeyFlintTestCase, TEST_STRIPE_WEBHOOK_SECRET, generate_stripe_signature

SVC = "app.infrastructure.email.transactional_email_service.TransactionalEmailService"
OPS = "ops@example.com"


class TestOpsAlerts(BaseKeyFlintTestCase):
    def setUp(self) -> None:
        super().setUp()
        settings = get_settings()
        self._prev = settings.OPS_ALERT_EMAIL
        settings.OPS_ALERT_EMAIL = OPS

    def tearDown(self) -> None:
        get_settings().OPS_ALERT_EMAIL = self._prev
        super().tearDown()

    def _post(self, event_type: str, obj: dict):
        body = json.dumps({"id": f"evt_{uuid.uuid4().hex}", "type": event_type, "data": {"object": obj}}).encode()
        return self.client.post(
            "/api/v1/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": generate_stripe_signature(body, TEST_STRIPE_WEBHOOK_SECRET)},
        )

    def _subjects(self, alert: mock.MagicMock) -> list[str]:
        return [c.args[1] for c in alert.call_args_list]

    def test_unresolved_tier_alerts(self):
        self.require_app()
        with mock.patch(f"{SVC}.send_ops_alert", return_value=True) as alert, mock.patch(f"{SVC}._dispatch", return_value=True):
            res = self._post("checkout.session.completed", {"customer_details": {"email": "x@example.com"}, "metadata": {"tier": "gold"}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(alert.call_args.args[0], OPS)
        self.assertIn("Tier sin resolver", self._subjects(alert)[0])
        self.assertIn("gold", alert.call_args.args[2])

    def test_missing_email_alerts_with_reserved_placeholder(self):
        self.require_app()
        with mock.patch(f"{SVC}.send_ops_alert", return_value=True) as alert:
            res = self._post("checkout.session.completed", {"metadata": {"tier": "indie"}})
        self.assertEqual(res.status_code, 200, res.text)
        key = res.json()["data"]["license_key"]
        self.assertTrue(any("Compra sin correo" in s for s in self._subjects(alert)))
        self.assertIn(key, alert.call_args.args[2])
        from app.infrastructure.database.connection import create_connection

        conn = create_connection()
        try:
            row = conn.execute(
                "SELECT c.email FROM licenses l JOIN customers c ON c.id = l.customer_id WHERE l.license_key = ?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
        self.assertRegex(row[0], r"^missing-email-[0-9a-f]{6}@keyflint\.invalid$")

    def test_processing_crash_alerts_and_still_fails(self):
        self.require_app()
        target = "app.application.services.billing_service.BillingService._process_webhook"
        with mock.patch(target, side_effect=RuntimeError("db locked")), \
                mock.patch(f"{SVC}.send_ops_alert", return_value=True) as alert:
            res = self._post("checkout.session.completed", {"metadata": {"tier": "indie"}})
        self.assertGreaterEqual(res.status_code, 500)
        self.assertIn("Webhook falló", self._subjects(alert)[0])
        self.assertIn("db locked", alert.call_args.args[2])

    def test_bad_signature_does_not_alert(self):
        self.require_app()
        with mock.patch(f"{SVC}.send_ops_alert", return_value=True) as alert:
            res = self.client.post("/api/v1/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "t=1,v1=bad"})
        self.assertGreaterEqual(res.status_code, 400)
        alert.assert_not_called()

    def test_alert_failure_never_breaks_billing_and_unset_is_silent(self):
        self.require_app()
        with mock.patch(f"{SVC}.send_ops_alert", side_effect=RuntimeError("resend down")):
            res = self._post("checkout.session.completed", {"customer_details": {"email": "y@example.com"}, "metadata": {"tier": "gold"}})
        self.assertEqual(res.status_code, 200, res.text)
        get_settings().OPS_ALERT_EMAIL = None
        with mock.patch(f"{SVC}.send_ops_alert", return_value=True) as alert:
            self._post("checkout.session.completed", {"customer_details": {"email": "z@example.com"}, "metadata": {"tier": "gold"}})
        alert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
