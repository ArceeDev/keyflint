"""Tier 1 tests for Automated Daily Growth Engine, Mobile Pulse & Real-Time Lead Alerts."""

from __future__ import annotations
import unittest

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.application.services.daily_growth import (
    collect_pulse_metrics,
    get_daily_post,
    run_daily_growth,
    send_owner_activity_alert,
)
from app.config import get_settings
from app.infrastructure.database.connection import create_connection
from app.infrastructure.database.migrations import init_db
from app.main import app


class _DummySender:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def _dispatch(self, recipient: str, subject: str, text_body: str, html_body: str) -> bool:
        self.calls.append(
            {
                "recipient": recipient,
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body,
            }
        )
        return True


def test_daily_post_generates_1tap_intents() -> None:
    now = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)
    post = get_daily_post(now)
    assert "x.com/intent/tweet?text=" in post["x_es_intent"]
    assert "x.com/intent/tweet?text=" in post["x_en_intent"]
    assert "linkedin.com/feed/?shareActive=true" in post["linkedin_intent"]
    assert "reddit.com/submit?title=" in post["reddit_intent"]


def test_run_daily_growth_idempotent_per_day(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "pulse.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("OPS_ALERT_EMAIL", "owner@keyflint.dev")
    monkeypatch.setenv("DAILY_PULSE_ENABLED", "true")
    monkeypatch.setenv("DAILY_PULSE_HOUR_UTC", "8")
    get_settings.cache_clear()
    init_db(db_file)

    conn = create_connection()
    sender = _DummySender()
    now = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)
    try:
        with patch("app.application.services.daily_growth.ping_indexnow", return_value={"ok": True}):
            res1 = run_daily_growth(conn, sender, force=False, now=now)
            assert res1["status"] == "sent"
            assert len(sender.calls) == 1
            assert "[KeyFlint Pulso]" in sender.calls[0]["subject"]

            # Second automatic run on the same UTC day must be skipped
            res2 = run_daily_growth(conn, sender, force=False, now=now)
            assert res2["status"] == "already_sent_today"
            assert len(sender.calls) == 1
    finally:
        conn.close()
        get_settings.cache_clear()


def test_owner_activity_alert_sends_mobile_card(monkeypatch) -> None:
    monkeypatch.setenv("OPS_ALERT_EMAIL", "owner@keyflint.dev")
    monkeypatch.setenv("LEAD_ALERT_ENABLED", "true")
    get_settings.cache_clear()
    sender = _DummySender()
    try:
        ok = send_owner_activity_alert(
            sender,
            "Solicitud",
            "Nueva prueba solicitada: cliente@despacho.es",
            correo="cliente@despacho.es",
            origen="lote",
        )
        assert ok is True
        assert len(sender.calls) == 1
        assert "cliente@despacho.es" in sender.calls[0]["html_body"]
    finally:
        get_settings.cache_clear()


def test_admin_pulse_endpoint_requires_admin_and_returns_metrics(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "admin_pulse.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_API_KEY", "test_super_admin_key_123456")
    get_settings.cache_clear()
    init_db(db_file)

    client = TestClient(app)
    try:
        r_unauth = client.get("/api/v1/licenses/admin-pulse")
        assert r_unauth.status_code in (401, 403)

        r_ok = client.get(
            "/api/v1/licenses/admin-pulse",
            headers={"X-Admin-Key": "test_super_admin_key_123456"},
        )
        assert r_ok.status_code == 200
        body = r_ok.json()
        assert body["success"] is True
        assert "customers_total" in body["data"]
        assert "daily_post" in body["data"]
    finally:
        get_settings.cache_clear()


class TestNtfyPrivacy(unittest.TestCase):
    def test_push_never_carries_customer_email(self):
        from unittest import mock

        from app.application.services import daily_growth

        settings = mock.Mock(LEAD_ALERT_ENABLED=True, OPS_ALERT_EMAIL="", NTFY_TOPIC="t")
        with mock.patch.object(daily_growth, "get_settings", return_value=settings), \
                mock.patch.object(daily_growth.httpx, "post") as post:
            post.return_value.status_code = 200
            daily_growth.send_owner_activity_alert(None, "Solicitud", "Nueva prueba solicitada", correo="cliente@despacho.es")
        sent = repr(post.call_args)
        self.assertNotIn("cliente@despacho.es", sent)
        self.assertIn("json", post.call_args.kwargs)
