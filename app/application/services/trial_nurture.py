"""Seguimiento de la licencia de prueba de Flint: correos en los días 1, 3 y 7 tras el alta.

Scope: Community licenses with metadata.trial (never demo, never upgraded: a purchase turns the
license into another tier and it leaves the query). One email per pass and license: if the gateway
was down, only the latest step due is sent and older ones are recorded as skipped. Every email
carries a one-click unsubscribe (LSSI art. 21.2); an opt-out stops every later step.
Runs from the hourly maintenance loop; NURTURE_EMAIL_ENABLED turns it off.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
from typing import Any, Optional
from urllib.parse import urlencode

from app.config import get_settings

logger = logging.getLogger("keyflint.nurture")

EVENT_SENT = "trial_nurture_email"
EVENT_OPT_OUT = "marketing_opt_out"
STEPS = (1, 3, 7)
_MAX_AGE_DAYS = STEPS[-1] + 2  # a step older than this is never sent late


def unsubscribe_token(license_id: str) -> str:
    key = get_settings().SECRET_KEY.encode()
    return hmac.new(key, f"unsubscribe:{license_id}".encode(), hashlib.sha256).hexdigest()[:32]


def unsubscribe_url(license_id: str) -> str:
    base = get_settings().NURTURE_UNSUBSCRIBE_BASE.rstrip("/")
    return f"{base}/api/v1/billing/unsubscribe?" + urlencode({"l": license_id, "t": unsubscribe_token(license_id)})


def verify_unsubscribe(license_id: str, token: str) -> bool:
    return bool(license_id) and hmac.compare_digest(unsubscribe_token(license_id), token or "")


def record_opt_out(conn: Any, license_id: str) -> bool:
    """Idempotent. Returns False when the license does not exist."""
    if conn.execute("SELECT 1 FROM licenses WHERE id = ?", (license_id,)).fetchone() is None:
        return False
    if conn.execute("SELECT 1 FROM license_events WHERE license_id = ? AND event_type = ?",
                    (license_id, EVENT_OPT_OUT)).fetchone() is None:
        conn.execute("INSERT INTO license_events (id, license_id, event_type, details_json) "
                     "VALUES (lower(hex(randomblob(16))), ?, ?, '{}')", (license_id, EVENT_OPT_OUT))
        conn.commit()
    return True


def _parse(ts: Any) -> datetime:
    d = datetime.fromisoformat(str(ts).replace(" ", "T").replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def run_trial_nurture(conn: Any, email_sender: Any, now: Optional[datetime] = None) -> dict[str, int]:
    """Sends the due step to each trial license. Returns counters. Never raises per license."""
    stats = {"sent": 0, "skipped": 0, "failed": 0}
    if not get_settings().NURTURE_EMAIL_ENABLED:
        return stats
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=_MAX_AGE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT l.id, l.license_key, l.metadata_json, l.created_at, c.email,
                  COALESCE(q.consumed, 0) AS consumed, COALESCE(q.balance, 0) AS balance
           FROM licenses l JOIN customers c ON c.id = l.customer_id
           LEFT JOIN quotas q ON q.license_id = l.id
           WHERE l.tier = 'community' AND l.status = 'active' AND l.created_at >= ?""",
        (since,),
    ).fetchall()
    for r in rows:
        try:
            meta = json.loads(r["metadata_json"] or "{}")
            if not meta.get("trial") or meta.get("demo") or meta.get("lang") == "en" or not r["email"]:  # emails are Spanish-only
                continue
            events = conn.execute(
                "SELECT event_type, details_json FROM license_events WHERE license_id = ? AND event_type IN (?, ?)",
                (r["id"], EVENT_SENT, EVENT_OPT_OUT),
            ).fetchall()
            if any(e["event_type"] == EVENT_OPT_OUT for e in events):
                continue
            done = {int(json.loads(e["details_json"] or "{}").get("step", 0)) for e in events}
            age = (now - _parse(r["created_at"])).total_seconds() / 86400
            due = [s for s in STEPS if s <= age and s not in done]
            if not due:
                continue
            step = due[-1]
            for s in due[:-1]:
                conn.execute("INSERT INTO license_events (id, license_id, event_type, details_json) "
                             "VALUES (lower(hex(randomblob(16))), ?, ?, ?)",
                             (r["id"], EVENT_SENT, json.dumps({"step": s, "skipped": True})))
                stats["skipped"] += 1
            # Record before sending: a crash never sends the same step twice.
            conn.execute("INSERT INTO license_events (id, license_id, event_type, details_json) "
                         "VALUES (lower(hex(randomblob(16))), ?, ?, ?)",
                         (r["id"], EVENT_SENT, json.dumps({"step": step, "consumed": int(r["consumed"])})))
            conn.commit()
            ok = email_sender.send_trial_nurture(
                r["email"], step=step, consumed=int(r["consumed"]), balance=int(r["balance"]),
                unsubscribe_url=unsubscribe_url(r["id"]),
            )
            stats["sent" if ok else "failed"] += 1
        except Exception:
            logger.exception("trial nurture failed for license %s", r["id"])
            stats["failed"] += 1
    return stats
