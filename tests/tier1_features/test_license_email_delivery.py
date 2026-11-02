"""Tier 1: license email delivery is recorded, never faked, and recoverable (resend + retry)."""

from __future__ import annotations

import json
import unittest
from unittest import mock
import uuid

import httpx

from tests.conftest import (
    BaseKeyFlintTestCase,
    TEST_STRIPE_WEBHOOK_SECRET,
    generate_stripe_signature,
)

SVC = "app.infrastructure.email.transactional_email_service.TransactionalEmailService"


class TestLicenseEmailDelivery(BaseKeyFlintTestCase):
    def _checkout(self, email: str | None) -> dict:
        obj: dict = {"metadata": {"tier": "indie"}, "payment_status": "paid"}
        if email:
            obj["customer_details"] = {"email": email}  # Payment Links put the email here
        body = json.dumps(
            {"id": f"evt_{uuid.uuid4().hex}", "type": "checkout.session.completed", "data": {"object": obj}}
        ).encode()
        res = self.client.post(
            "/api/v1/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": generate_stripe_signature(body, TEST_STRIPE_WEBHOOK_SECRET)},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["data"]

    def _delivery(self, key: str) -> dict:
        from app.infrastructure.database.connection import create_connection
        from app.infrastructure.repositories.sqlite_license_repo import SqliteLicenseRepo

        conn = create_connection()
        try:
            return SqliteLicenseRepo(conn).get_by_key(key).metadata["email_delivery"]
        finally:
            conn.close()

    def test_unconfigured_provider_reports_failure_not_success(self):
        self.require_app()
        with mock.patch.dict("os.environ", {"RESEND_API_KEY": "", "SMTP_HOST": ""}):
            data = self._checkout("real.buyer@example.com")
        self.assertFalse(data["email_delivered"])
        info = self._delivery(data["license_key"])
        self.assertEqual(info["status"], "failed")
        self.assertEqual(info["error"], "no_email_provider_configured")
        self.assertEqual(info["recipient"], "real.buyer@example.com")

    def test_sent_via_provider_and_recorded(self):
        self.require_app()
        with mock.patch(f"{SVC}._dispatch", return_value=True) as dispatch:
            data = self._checkout("ok.buyer@example.com")
        self.assertTrue(data["email_delivered"])
        self.assertEqual(dispatch.call_args.kwargs["recipient"], "ok.buyer@example.com")
        self.assertIn(data["license_key"], dispatch.call_args.kwargs["text_body"])
        self.assertEqual(self._delivery(data["license_key"])["status"], "sent")

    def test_missing_email_is_flagged(self):
        self.require_app()
        data = self._checkout(None)
        self.assertFalse(data["email_delivered"])
        self.assertEqual(self._delivery(data["license_key"])["error"], "no_customer_email")

    def test_resend_endpoint_and_retry_pass(self):
        self.require_app()
        with mock.patch(f"{SVC}._dispatch", return_value=False):
            data = self._checkout("retry.buyer@example.com")
        key = data["license_key"]
        self.assertEqual(self._delivery(key)["status"], "failed")

        with mock.patch(f"{SVC}._dispatch", return_value=True):
            res = self.client.post("/api/v1/billing/retry-failed-license-emails")
        self.assertEqual(res.json()["data"], {"retried": 1, "sent": 1, "failed": 0})
        info = self._delivery(key)
        self.assertEqual((info["status"], info["attempts"]), ("sent", 2))

        with mock.patch(f"{SVC}._dispatch", return_value=True) as dispatch:
            res = self.client.post(
                "/api/v1/billing/resend-license-email",
                json={"license_key": key, "to": "other@example.com"},
            )
        self.assertTrue(res.json()["data"]["email_delivered"])
        self.assertEqual(dispatch.call_args.kwargs["recipient"], "other@example.com")

    def test_resend_unknown_license_404(self):
        self.require_app()
        res = self.client.post("/api/v1/billing/resend-license-email", json={"license_key": "LIC-PRO-nope1234"})
        self.assertEqual(res.status_code, 404)

    def test_resend_api_retries_transient_and_hints_on_403(self):
        from app.infrastructure.email.transactional_email_service import TransactionalEmailService

        svc = TransactionalEmailService(resend_api_key="re_test", from_address="KeyFlint <licenses@keyflint.dev>")
        responses = [httpx.Response(503, text="busy"), httpx.Response(200, json={"id": "x"})]
        with mock.patch("httpx.Client.post", side_effect=responses), mock.patch("time.sleep"):
            self.assertTrue(svc._dispatch("a@example.com", "s", "t", "h"))

        with mock.patch("httpx.Client.post", return_value=httpx.Response(403, text="domain not verified")) as post:
            with self.assertLogs("keyflint.email", "ERROR") as logs:
                self.assertFalse(svc._dispatch("a@example.com", "s", "t", "h"))
        self.assertEqual(post.call_count, 1)  # 4xx is not retried
        self.assertIn("SPF/DKIM", "".join(logs.output))
        self.assertTrue(svc.last_error.startswith("resend_403"))

    def test_quickstart_snippets_match_sdk_apis(self):
        from app.domain.interfaces.email_sender import LicenseEmailPayload
        from app.infrastructure.email.transactional_email_service import TransactionalEmailService

        p = LicenseEmailPayload("a@example.com", "indie", "LIC-INDIE-x.y", "LIC-INDIE-x.y", "ab" * 32, 3, 10_000)
        text = TransactionalEmailService(enabled=False)._render_license_text(p)
        self.assertNotIn("is_valid", text)
        self.assertNotIn("isValid", text)
        self.assertNotIn("VerifyLicense", text)
        self.assertIn("result.valid", text)
        self.assertIn("keyflint.Verify(", text)
        self.assertNotIn("\n\n\n", text)  # no double-spacing from CR line endings


if __name__ == "__main__":
    unittest.main()
