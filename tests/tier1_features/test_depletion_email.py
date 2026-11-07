"""Tier 1: one retention email when a trial / MCP-hub license runs out of credits."""

from __future__ import annotations

from unittest import mock

from app.application.services import depletion_notifier as dn
from app.config import get_settings
from tests.conftest import BaseKeyFlintTestCase

SVC = "app.infrastructure.email.transactional_email_service.TransactionalEmailService"


class TestDepletionEmail(BaseKeyFlintTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._inline = mock.patch.object(dn._EXECUTOR, "submit", side_effect=lambda fn: fn())
        self._inline.start()

    def tearDown(self) -> None:
        self._inline.stop()
        super().tearDown()

    def _issue(self, email: str, metadata: dict) -> str:
        res = self.client.post("/api/v1/licenses/issue",
                               json={"customer_email": email, "tier": "community", "metadata": metadata})
        self.assertIn(res.status_code, (200, 201), res.text)
        return res.json()["data"]["license_key"]

    def _deduct(self, key: str, credits: int):
        with mock.patch(f"{SVC}.send_credits_depleted", return_value=True) as send:
            res = self.deduct_quota_api(key, credits=credits)
        return res, send

    def test_trial_hits_zero_sends_once_with_topup_link(self):
        self.require_app()
        key = self._issue("t@acme.io", {"trial": True, "source": "mcp-hub"})
        res, send = self._deduct(key, 20)
        self.assertEqual(res.status_code, 200, res.text)
        send.assert_not_called()
        res, send = self._deduct(key, 5)
        self.assertEqual(res.status_code, 200, res.text)
        send.assert_called_once()
        args, kw = send.call_args
        self.assertEqual(args[0], "t@acme.io")
        self.assertTrue(kw["trial"])
        self.assertEqual((kw["topup_eur"], kw["topup_credits"]), (5, 100))
        self.assertIn("/saldo/#licencia=", kw["topup_url"])
        self.assertNotIn("?", kw["topup_url"].split("#")[0].rstrip("/").split("/")[-1])
        res, send = self._deduct(key, 1)  # refused: same episode, no second email
        self.assertEqual(res.status_code, 402, res.text)
        send.assert_not_called()

    def test_refused_deduct_with_leftover_credits_also_notifies(self):
        self.require_app()
        key = self._issue("left@acme.io", {"trial": True})
        res, send = self._deduct(key, 30)
        self.assertEqual(res.status_code, 402, res.text)
        send.assert_called_once()

    def test_new_episode_after_topup_sends_again(self):
        self.require_app()
        key = self._issue("again@acme.io", {"source": "mcp-hub"})
        _, send = self._deduct(key, 25)
        send.assert_called_once()
        self.assertFalse(send.call_args.kwargs["trial"])
        r = self.client.post("/api/v1/quota/replenish", json={"license_key": key, "credits": 10})
        self.assertEqual(r.status_code, 200, r.text)
        _, send = self._deduct(key, 10)
        send.assert_called_once()

    def test_out_of_scope_and_disabled(self):
        self.require_app()
        other = self._issue("sdk@acme.io", {})
        _, send = self._deduct(other, 25)
        send.assert_not_called()
        demo_lic = self._issue("demo@acme.io", {"source": "mcp-hub", "demo": True})
        _, send = self._deduct(demo_lic, 25)
        send.assert_not_called()
        pro_res = self.client.post("/api/v1/licenses/issue", json={"customer_email": "pro@acme.io", "tier": "pro"})
        pro_key = pro_res.json()["data"]["license_key"]
        _, send = self._deduct(pro_key, 1000)
        send.assert_called_once()
        get_settings().DEPLETION_EMAIL_ENABLED = False
        try:
            key = self._issue("off@acme.io", {"trial": True})
            _, send = self._deduct(key, 25)
            send.assert_not_called()
        finally:
            get_settings().DEPLETION_EMAIL_ENABLED = True

    def test_email_failure_never_breaks_metering(self):
        self.require_app()
        key = self._issue("boom@acme.io", {"trial": True})
        with mock.patch(f"{SVC}.send_credits_depleted", side_effect=RuntimeError("resend down")):
            with mock.patch.object(dn._EXECUTOR, "submit", side_effect=RuntimeError("pool gone")):
                res = self.deduct_quota_api(key, credits=25)
        self.assertEqual(res.status_code, 200, res.text)

    def test_render_is_escaped_and_has_link(self):
        from app.infrastructure.email.transactional_email_service import TransactionalEmailService
        svc = TransactionalEmailService(resend_api_key="x")
        with mock.patch.object(svc, "_dispatch", return_value=True) as d:
            svc.send_credits_depleted("a@b.io", "LIC-abc<def>", trial=True,
                                      topup_url="https://mcp.keyflint.dev/saldo/#licencia=LIC&importe=5",
                                      topup_eur=5, topup_credits=100)
        kw = d.call_args.kwargs
        self.assertIn("25 créditos", kw["subject"])
        self.assertIn("importe=5", kw["text_body"])
        self.assertIn("&amp;importe=5", kw["html_body"])
        self.assertNotIn("<def>", kw["html_body"])
