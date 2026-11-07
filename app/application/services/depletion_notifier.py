"""Retention email when an MCP license runs out of credits.

Fires from QuotaService.deduct when a deduct leaves the balance at 0 or is refused for lack of
credits. Scope: trial licenses and licenses issued through the MCP hub (metadata.source == "mcp-hub");
other KeyFlint integrators' end users never get it. One email per depletion episode: a new one is
only sent after credits were added (balance + consumed grew) or after DEPLETION_EMAIL_COOLDOWN_DAYS.
The dedupe check runs inline (one indexed SELECT + INSERT); the email goes out on a worker thread
so the metered call never waits on Resend.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import threading
from typing import Any, Callable, Optional
from urllib.parse import quote

from app.application.services.topup_pricing import topup_credits
from app.config import get_settings

logger = logging.getLogger("keyflint.depletion")

EVENT_TYPE = "credits_depleted_email"
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kf-depletion")
_LOCK = threading.Lock()


def in_scope(metadata: dict[str, Any]) -> bool:
    return bool(metadata.get("trial")) or metadata.get("source") == "mcp-hub"


def topup_link(base: str, license_key: str, eur: int) -> str:
    # License goes in the fragment: never sent to the server, never in access logs.
    return f"{base.split('#')[0]}#licencia={quote(license_key, safe='')}&importe={eur}"


class DepletionNotifier:
    def __init__(self, conn: Any, customer_repo: Any, email_sender: Any,
                 submit: Optional[Callable[[Callable[[], Any]], Any]] = None) -> None:
        self._conn = conn
        self._customers = customer_repo
        self._email = email_sender
        self._submit = submit or _EXECUTOR.submit

    def __call__(self, license_entity: Any, balance: int, consumed: int) -> bool:
        """Returns True when an email was queued. Never raises."""
        try:
            return self._maybe_send(license_entity, balance, consumed)
        except Exception:  # a notification must never break metering
            logger.exception("depletion notice failed for %s", getattr(license_entity, "id", "?"))
            return False

    def _maybe_send(self, lic: Any, balance: int, consumed: int) -> bool:
        settings = get_settings()
        if not settings.DEPLETION_EMAIL_ENABLED or not in_scope(lic.metadata or {}):
            return False
        granted = int(balance) + int(consumed)
        with _LOCK:
            row = self._conn.execute(
                "SELECT details_json, created_at FROM license_events WHERE license_id = ? AND event_type = ? "
                "ORDER BY rowid DESC LIMIT 1", (lic.id, EVENT_TYPE),
            ).fetchone()
            if row is not None:
                last = json.loads(row["details_json"] or "{}")
                sent = datetime.fromisoformat(str(row["created_at"]).replace(" ", "T"))
                if sent.tzinfo is None:
                    sent = sent.replace(tzinfo=timezone.utc)
                fresh = datetime.now(timezone.utc) - sent < timedelta(days=settings.DEPLETION_EMAIL_COOLDOWN_DAYS)
                if fresh and int(last.get("granted", -1)) >= granted:
                    return False
            customer = self._customers.get_by_id(lic.customer_id)
            if customer is None or not customer.email:
                return False
            self._conn.execute(
                "INSERT INTO license_events (id, license_id, event_type, details_json) "
                "VALUES (lower(hex(randomblob(16))), ?, ?, ?)",
                (lic.id, EVENT_TYPE, json.dumps({"granted": granted, "balance": int(balance)})),
            )
        eur = max(5, int(settings.DEPLETION_EMAIL_TOPUP_EUR))
        url = topup_link(settings.TOPUP_DEFAULT_RETURN_URL, lic.license_key, eur)
        trial = bool((lic.metadata or {}).get("trial"))
        email, key = customer.email, lic.license_key
        sender = self._email
        self._submit(lambda: sender.send_credits_depleted(
            email, key, trial=trial, topup_url=url, topup_eur=eur, topup_credits=topup_credits(eur * 100)))
        logger.info("depletion email queued for license %s", lic.id)
        return True
