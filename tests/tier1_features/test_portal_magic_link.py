"""Tier 1: the self-service portal never returns licenses for an email alone.

An email gets a single-use, short-lived link sent to that inbox; a license key is its own proof.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from app.config import get_settings
from tests.conftest import BaseKeyFlintTestCase

SVC = "app.infrastructure.email.transactional_email_service.TransactionalEmailService"
BASE = "https://licenses.example.test/"


class TestPortalMagicLink(BaseKeyFlintTestCase):
    def setUp(self) -> None:
        super().setUp()
        settings = get_settings()
        self._prev = (settings.PORTAL_LINK_BASE_URL, settings.PORTAL_LINK_MAX_PER_WINDOW)
        settings.PORTAL_LINK_BASE_URL = BASE

    def tearDown(self) -> None:
        settings = get_settings()
        settings.PORTAL_LINK_BASE_URL, settings.PORTAL_LINK_MAX_PER_WINDOW = self._prev
        super().tearDown()

    def _lookup(self, query: str, **kw):
        return self.client.post("/api/v1/billing/portal/lookup", json={"query": query}, **kw)

    def _request_link(self, email: str, **kw) -> tuple[dict, mock.MagicMock]:
        with mock.patch(f"{SVC}.send_portal_magic_link", return_value=True) as send:
            res = self._lookup(email, **kw)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json(), send

    @staticmethod
    def _token(send: mock.MagicMock) -> str:
        link = send.call_args.args[1]
        return parse_qs(urlsplit(link).query)["portal_token"][0]

    def _redeem(self, token: str):
        return self.client.post("/api/v1/billing/portal/redeem", json={"token": token})

    def test_email_lookup_never_returns_license_data(self):
        self.require_app()
        lic = self.issue_license_api(customer_email="victim@acme.io", tier="pro")
        body, send = self._request_link("victim@acme.io")
        self.assertTrue(body["data"]["magic_link_sent"])
        self.assertNotIn(lic["license_key"], str(body))
        self.assertNotIn("licenses", body["data"])
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "victim@acme.io")

    def test_unknown_email_gets_identical_response_and_no_email(self):
        self.require_app()
        self.issue_license_api(customer_email="known@acme.io", tier="pro")
        known, _ = self._request_link("known@acme.io")
        unknown, send = self._request_link("nobody@acme.io")
        self.assertEqual(known["data"], unknown["data"])
        send.assert_not_called()

    def test_link_redeems_once_and_shows_all_licenses(self):
        self.require_app()
        a = self.issue_license_api(customer_email="buyer@acme.io", tier="pro")
        b = self.issue_license_api(customer_email="buyer@acme.io", tier="studio")
        _, send = self._request_link("buyer@acme.io")
        token = self._token(send)

        first = self._redeem(token)
        self.assertEqual(first.status_code, 200, first.text)
        keys = {l["license_key"] for l in first.json()["data"]["licenses"]}
        self.assertEqual(keys, {a["license_key"], b["license_key"]})
        self.assertEqual(first.json()["data"]["customer_email"], "buyer@acme.io")

        second = self._redeem(token)
        self.assertEqual(second.status_code, 401)
        self.assertNotIn(a["license_key"], second.text)

    def test_forged_and_expired_tokens_rejected(self):
        self.require_app()
        self.issue_license_api(customer_email="exp@acme.io", tier="pro")
        self.assertEqual(self._redeem("x" * 43).status_code, 401)

        _, send = self._request_link("exp@acme.io")
        token = self._token(send)
        from app.infrastructure.database.connection import create_connection

        conn = create_connection()
        conn.execute("UPDATE portal_login_tokens SET expires_at = '2000-01-01T00:00:00+00:00'")
        conn.commit()
        self.assertEqual(self._redeem(token).status_code, 401)

    def test_only_token_hash_is_stored(self):
        self.require_app()
        self.issue_license_api(customer_email="hash@acme.io", tier="pro")
        _, send = self._request_link("hash@acme.io")
        token = self._token(send)
        from app.infrastructure.database.connection import create_connection

        rows = create_connection().execute("SELECT token_hash FROM portal_login_tokens").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]["token_hash"], token)
        self.assertNotIn(token, rows[0]["token_hash"])

    def test_link_uses_configured_base_not_host_header(self):
        self.require_app()
        self.issue_license_api(customer_email="host@acme.io", tier="pro")
        _, send = self._request_link("host@acme.io", headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example"})
        link = send.call_args.args[1]
        self.assertTrue(link.startswith(BASE), link)
        self.assertNotIn("evil.example", link)

    def test_links_are_throttled_per_customer(self):
        self.require_app()
        get_settings().PORTAL_LINK_MAX_PER_WINDOW = 2
        self.issue_license_api(customer_email="spam@acme.io", tier="pro")
        sent = 0
        for _ in range(4):
            body, send = self._request_link("spam@acme.io")
            self.assertTrue(body["data"]["magic_link_sent"])
            sent += send.call_count
        self.assertEqual(sent, 2)

    def test_license_key_lookup_still_works(self):
        self.require_app()
        lic = self.issue_license_api(customer_email="key@acme.io", tier="pro")
        res = self._lookup(lic["license_key"])
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()["data"]
        self.assertEqual([l["license_key"] for l in data["licenses"]], [lic["license_key"]])
        self.assertIn(lic["license_key"], data["python_snippet"])
        self.assertEqual(self._lookup("LIC-PRO-doesnotexist").status_code, 404)

    def test_email_html_escapes_link(self):
        from app.infrastructure.email.transactional_email_service import TransactionalEmailService

        svc = TransactionalEmailService(resend_api_key="re_test", enabled=True)
        with mock.patch.object(svc, "_dispatch", return_value=True) as dispatch:
            self.assertTrue(svc.send_portal_magic_link("a@acme.io", 'https://x/?portal_token=a"b', 15))
        html_body = dispatch.call_args.kwargs["html_body"]
        self.assertIn("a&quot;b", html_body)
        self.assertIn("15 minutos", dispatch.call_args.kwargs["text_body"])


class TestBillingPortalNeedsProof(BaseKeyFlintTestCase):
    def test_mock_mode_accepts_license_key(self):
        self.require_app()
        lic = self.issue_license_api(customer_email="mock@acme.io", tier="pro")
        res = self.client.post("/api/v1/billing/portal", json={"license_key": lic["license_key"]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["data"]["customer_email"], "mock@acme.io")
        self.assertEqual(self.client.post("/api/v1/billing/portal", json={}).status_code, 422)

    def test_live_mode_rejects_email_only(self):
        self.require_app()
        prev = os.environ.get("BILLING_MODE")
        os.environ["BILLING_MODE"] = "live"
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"
        get_settings.cache_clear()
        try:
            with mock.patch("app.application.services.billing_service.httpx.get") as stripe_get:
                res = self.client.post("/api/v1/billing/portal", json={"customer_email": "victim@acme.io"})
                bad = self.client.post("/api/v1/billing/portal", json={"license_key": "LIC-PRO-unknown"})
            self.assertEqual(res.status_code, 401, res.text)
            self.assertEqual(bad.status_code, 404, bad.text)
            stripe_get.assert_not_called()
        finally:
            os.environ["BILLING_MODE"] = prev or "mock"
            os.environ.pop("STRIPE_SECRET_KEY", None)
            get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
