"""Tier 1: trial follow-up emails (days 1, 3, 7): once per step, catch-up sends only the latest, opt-out stops all."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock
from urllib.parse import parse_qs, urlparse

from app.application.services.trial_nurture import run_trial_nurture
from app.config import get_settings
from app.infrastructure.database.connection import create_connection
from app.presentation.middlewares import rate_limiter
from tests.conftest import BaseKeyFlintTestCase

SVC = "app.infrastructure.email.transactional_email_service.TransactionalEmailService"


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send_trial_nurture(self, email, **kw):
        self.calls.append({"email": email, **kw})
        return True


class TestTrialNurture(BaseKeyFlintTestCase):
    def setUp(self) -> None:
        super().setUp()
        s = get_settings()
        self._prev = (s.TRIAL_ENABLED, s.TRIAL_DAILY_CAP, s.NURTURE_EMAIL_ENABLED)
        s.TRIAL_ENABLED, s.TRIAL_DAILY_CAP, s.NURTURE_EMAIL_ENABLED = True, 100, True
        rate_limiter.reset()

    def tearDown(self) -> None:
        s = get_settings()
        s.TRIAL_ENABLED, s.TRIAL_DAILY_CAP, s.NURTURE_EMAIL_ENABLED = self._prev
        super().tearDown()

    def _trial(self, email: str) -> str:
        with mock.patch(f"{SVC}.send_license_issued", return_value=True) as send:
            res = self.client.post("/api/v1/billing/trial", json={"email": email, "source": "mcp-hub"})
        self.assertEqual(res.status_code, 200, res.text)
        return send.call_args.args[0].license_key

    def _run(self, days: float, sender: FakeSender):
        conn = create_connection()
        try:
            return run_trial_nurture(conn, sender, now=datetime.now(timezone.utc) + timedelta(days=days))
        finally:
            conn.close()

    def test_steps_once_each_and_tailored_to_usage(self):
        self.require_app()
        self._trial("nurture@gestoria.es")
        s = FakeSender()
        self.assertEqual(self._run(0.5, s)["sent"], 0)
        self._run(1.1, s)
        self._run(1.2, s)  # same step: not repeated
        self.assertEqual([c["step"] for c in s.calls], [1])
        self.assertEqual(s.calls[0]["consumed"], 0)
        self._run(3.1, s)
        self._run(7.1, s)
        self._run(8.0, s)
        self.assertEqual([c["step"] for c in s.calls], [1, 3, 7])
        self.assertTrue(all("/api/v1/billing/unsubscribe?" in c["unsubscribe_url"] for c in s.calls))

    def test_catch_up_sends_only_latest_step(self):
        self.require_app()
        self._trial("late@gestoria.es")
        s = FakeSender()
        stats = self._run(7.5, s)
        self.assertEqual([c["step"] for c in s.calls], [7])
        self.assertEqual(stats["skipped"], 2)

    def test_unsubscribe_stops_everything_and_bad_token_fails(self):
        self.require_app()
        self._trial("baja@gestoria.es")
        s = FakeSender()
        self._run(1.1, s)
        url = urlparse(s.calls[0]["unsubscribe_url"])
        q = parse_qs(url.query)
        bad = self.client.get(f"{url.path}?l={q['l'][0]}&t=deadbeef")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.get(f"{url.path}?{url.query}")
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertIn("no te enviaremos", ok.text)
        self.assertEqual(self.client.get(f"{url.path}?{url.query}").status_code, 200)  # idempotent
        self._run(3.1, s)
        self._run(7.1, s)
        self.assertEqual(len(s.calls), 1)

    def test_disabled_and_real_template_renders(self):
        self.require_app()
        self._trial("off@gestoria.es")
        get_settings().NURTURE_EMAIL_ENABLED = False
        s = FakeSender()
        self._run(1.1, s)
        self.assertEqual(s.calls, [])
        from app.infrastructure.email.transactional_email_service import TransactionalEmailService
        svc = TransactionalEmailService()
        for step, consumed in ((1, 0), (1, 5), (3, 5), (7, 5)):
            with mock.patch.object(svc, "_dispatch", return_value=True) as d:
                self.assertTrue(svc.send_trial_nurture("x@y.es", step=step, consumed=consumed, balance=20,
                                                       unsubscribe_url="https://u/x?l=1&t=2"))
            kw = d.call_args.kwargs
            self.assertIn("Darme de baja", kw["html_body"])
            self.assertIn("https://u/x?l=1&t=2", kw["text_body"])
            self.assertIn("mcp.keyflint.dev", kw["text_body"])

    def test_english_trials_are_skipped(self):
        self.require_app()
        key = self._trial("en@company.com")
        conn = create_connection()
        try:
            conn.execute("UPDATE licenses SET metadata_json = json_set(metadata_json, '$.lang', 'en') WHERE license_key = ?", (key,))
            conn.commit()
        finally:
            conn.close()
        s = FakeSender()
        self._run(1.1, s)
        self.assertEqual(s.calls, [])
