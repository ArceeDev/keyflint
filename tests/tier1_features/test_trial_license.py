"""Tier 1: self-serve free trial. One Community license per email, only ever sent to that inbox."""

from __future__ import annotations

from unittest import mock

from app.config import get_settings
from app.presentation.middlewares import rate_limiter
from tests.conftest import BaseKeyFlintTestCase

SVC = "app.infrastructure.email.transactional_email_service.TransactionalEmailService"


class TestTrialLicense(BaseKeyFlintTestCase):
    def setUp(self) -> None:
        super().setUp()
        s = get_settings()
        self._prev = (s.TRIAL_ENABLED, s.TRIAL_DAILY_CAP)
        s.TRIAL_ENABLED, s.TRIAL_DAILY_CAP = True, 100
        rate_limiter.reset()

    def tearDown(self) -> None:
        s = get_settings()
        s.TRIAL_ENABLED, s.TRIAL_DAILY_CAP = self._prev
        rate_limiter.reset()
        super().tearDown()

    def _trial(self, email: str):
        with mock.patch(f"{SVC}.send_license_issued", return_value=True) as send:
            res = self.client.post("/api/v1/billing/trial", json={"email": email, "source": "mcp-hub"})
        return res, send

    def test_new_email_gets_community_license_by_email_only(self):
        self.require_app()
        res, send = self._trial("new@acme.io")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotIn("LIC-", res.text)
        send.assert_called_once()
        payload = send.call_args.args[0]
        self.assertEqual(payload.recipient_email, "new@acme.io")
        self.assertEqual(payload.tier, "community")
        self.assertEqual(payload.credits, 25)
        status = self.client.get("/api/v1/billing/status", params={"license_key": payload.license_key})
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["data"]["credit_balance"], 25)

    def test_second_request_and_existing_buyer_get_identical_answer_and_no_email(self):
        self.require_app()
        first, _ = self._trial("twice@acme.io")
        again, send = self._trial("twice@acme.io")
        self.assertEqual(first.json()["data"], again.json()["data"])
        send.assert_not_called()
        self.issue_license_api(customer_email="buyer@acme.io", tier="pro")
        buyer, send = self._trial("buyer@acme.io")
        self.assertEqual(first.json()["data"], buyer.json()["data"])
        send.assert_not_called()

    def test_daily_cap(self):
        self.require_app()
        get_settings().TRIAL_DAILY_CAP = 1
        self._trial("a@acme.io")
        res, send = self._trial("b@acme.io")
        self.assertEqual(res.status_code, 200)
        send.assert_not_called()

    def test_disabled_and_invalid(self):
        self.require_app()
        get_settings().TRIAL_ENABLED = False
        res, send = self._trial("off@acme.io")
        self.assertEqual(res.status_code, 503, res.text)
        send.assert_not_called()
        get_settings().TRIAL_ENABLED = True
        res, _ = self._trial("not-an-email")
        self.assertEqual(res.status_code, 422)
