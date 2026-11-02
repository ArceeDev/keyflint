"""KeyFlint SQLite Quota Repository.

File: app/infrastructure/repositories/sqlite_quota_repo.py
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.domain.entities.quota import CreditDeductResult, QuotaBalance, QuotaLedger
from app.domain.entities.usage import UsageEvent
from app.domain.exceptions import (
    DomainError,
    IdempotencyConflictError,
    LicenseNotFoundError,
    QuotaExceededError,
)
from app.domain.interfaces.quota_repository import IQuotaRepository
from app.infrastructure.database.connection import transaction


class SqliteQuotaRepo(IQuotaRepository):
    """SQLite implementation of the Quota Repository port with atomic decrements."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, quota: QuotaLedger) -> None:
        reset_str = quota.last_reset_at.isoformat()
        updated_str = quota.updated_at.isoformat()
        self._conn.execute(
            """
            INSERT INTO quotas (id, license_id, total_allowance, balance, consumed, last_reset_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                total_allowance = excluded.total_allowance,
                balance = excluded.balance,
                consumed = excluded.consumed,
                last_reset_at = excluded.last_reset_at,
                updated_at = excluded.updated_at
            """,
            (
                quota.id,
                quota.license_id,
                quota.total_allowance,
                quota.balance,
                quota.consumed,
                reset_str,
                updated_str,
            ),
        )

    def get_by_license_id(self, license_id: str) -> Optional[QuotaLedger]:
        cur = self._conn.execute("SELECT * FROM quotas WHERE license_id = ?", (license_id,))
        row = cur.fetchone()
        return self._row_to_entity(row) if row else None

    def get_balance(self, license_id: str) -> QuotaBalance:
        cur = self._conn.execute(
            "SELECT balance, total_allowance, consumed, last_reset_at FROM quotas WHERE license_id = ?",
            (license_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise LicenseNotFoundError(f"Quota record for license '{license_id}' not found.")

        reset_at = (
            datetime.fromisoformat(row["last_reset_at"])
            if isinstance(row["last_reset_at"], str)
            else row["last_reset_at"]
        )
        if reset_at.tzinfo is None:
            reset_at = reset_at.replace(tzinfo=timezone.utc)

        return QuotaBalance(
            license_id=license_id,
            balance=row["balance"],
            total_allowance=row["total_allowance"],
            consumed=row["consumed"],
            last_reset_at=reset_at,
        )

    def atomic_deduct(
        self,
        license_id: str,
        credits: int,
        idempotency_key: str,
        event_type: str = "api_call",
        metadata: Optional[dict[str, Any]] = None,
    ) -> CreditDeductResult:
        """Atomically decrements usage credits with RETURNING balance and replay-protection idempotency.

        Zero race conditions across concurrent workers.
        """
        if credits <= 0:
            raise ValueError(f"Credits to deduct must be a positive integer; got {credits}")
        if not idempotency_key or not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty or whitespace")
        if idempotency_key.startswith("refund:"):
            raise ValueError("idempotency_key must not use the reserved 'refund:' prefix")

        import random
        import time

        max_attempts = 50
        for attempt in range(max_attempts):
            try:
                with transaction(self._conn):
                    # 1. Tenant-Scoped Idempotency Check & Conflict Detection
                    cur_idemp = self._conn.execute(
                        """
                        SELECT id, license_id, event_type, credits_consumed
                        FROM usage_events
                        WHERE license_id = ? AND idempotency_key = ?
                        """,
                        (license_id, idempotency_key),
                    )
                    existing_event = cur_idemp.fetchone()
                    if existing_event is not None:
                        # A refunded deduct must not be replayed as a free, already-paid success.
                        if self._conn.execute(
                            "SELECT 1 FROM usage_events WHERE license_id = ? AND idempotency_key = ?",
                            (license_id, f"refund:{idempotency_key}"),
                        ).fetchone() is not None:
                            raise IdempotencyConflictError(
                                f"Idempotency key '{idempotency_key}' was already refunded; use a new key.",
                                details={"idempotency_key": idempotency_key, "reason": "KEY_REFUNDED"},
                            )
                        if existing_event["credits_consumed"] != credits:
                            raise IdempotencyConflictError(
                                f"Idempotency key '{idempotency_key}' was previously used with conflicting parameters.",
                                details={
                                    "idempotency_key": idempotency_key,
                                    "requested_credits": credits,
                                    "cached_credits": existing_event["credits_consumed"],
                                },
                            )

                        # Replay hit: fetch current balance and return cached result
                        bal_cur = self._conn.execute(
                            "SELECT balance, consumed FROM quotas WHERE license_id = ?", (license_id,)
                        )
                        bal_row = bal_cur.fetchone()
                        if bal_row is None:
                            raise LicenseNotFoundError(f"Quota record for license '{license_id}' not found.")
                        current_bal = bal_row["balance"]
                        return CreditDeductResult(
                            success=True,
                            remaining_balance=current_bal,
                            consumed_credits=existing_event["credits_consumed"],
                            consumed_total=bal_row["consumed"],
                            is_cached=True,
                            event_id=existing_event["id"],
                            reason="idempotent_replay",
                        )

                    # 2. Atomic Decrement with RETURNING
                    cur = self._conn.execute(
                        """
                        UPDATE quotas
                        SET balance = balance - ?,
                            consumed = consumed + ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE license_id = ? AND balance >= ?
                        RETURNING balance, consumed
                        """,
                        (credits, credits, license_id, credits),
                    )
                    row = cur.fetchone()

                    if row is None:
                        # Deduction condition failed: check why (not found vs insufficient balance)
                        check_cur = self._conn.execute(
                            "SELECT balance FROM quotas WHERE license_id = ?", (license_id,)
                        )
                        check_row = check_cur.fetchone()
                        if check_row is None:
                            raise LicenseNotFoundError(f"Quota record for license '{license_id}' not found.")

                        avail = check_row["balance"]
                        raise QuotaExceededError(
                            f"Token quota exhausted. Remaining balance: {avail} credits.",
                            details={
                                "license_id": license_id,
                                "remaining_credits": avail,
                                "requested_credits": credits,
                            },
                        )

                    new_balance = row["balance"]
                    new_consumed = row["consumed"]

                    # 3. Append Usage Event Audit Record
                    event_id = str(uuid.uuid4())
                    meta_str = json.dumps(metadata) if metadata else None
                    self._conn.execute(
                        """
                        INSERT INTO usage_events (id, license_id, event_type, credits_consumed, idempotency_key, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (event_id, license_id, event_type, credits, idempotency_key, meta_str),
                    )

                    return CreditDeductResult(
                        success=True,
                        remaining_balance=new_balance,
                        consumed_credits=credits,
                        consumed_total=new_consumed,
                        is_cached=False,
                        event_id=event_id,
                    )
            except sqlite3.OperationalError as e:
                msg = str(e).lower()
                if ("locked" in msg or "busy" in msg) and attempt < max_attempts - 1:
                    time.sleep(random.uniform(0.005, 0.025))
                    continue
                raise

    def atomic_refund(
        self,
        license_id: str,
        idempotency_key: str,
        window_seconds: int,
        reason: Optional[str] = None,
    ) -> CreditDeductResult:
        """Compensates a previous deduct (same idempotency key) exactly once, within a time window.

        The refund is stored as a usage event (event_type ``refund``, key ``refund:<key>``, credits
        returned as a positive amount), so replays are idempotent and the audit trail stays append-only.
        """
        if not idempotency_key or not idempotency_key.strip() or idempotency_key.startswith("refund:"):
            raise ValueError("idempotency_key must reference an original deduct")
        refund_key = f"refund:{idempotency_key}"
        with transaction(self._conn):
            done = self._conn.execute(
                "SELECT id, credits_consumed FROM usage_events WHERE license_id = ? AND idempotency_key = ?",
                (license_id, refund_key),
            ).fetchone()
            if done is not None:
                bal = self._conn.execute(
                    "SELECT balance, consumed FROM quotas WHERE license_id = ?", (license_id,)
                ).fetchone()
                return CreditDeductResult(
                    success=True, remaining_balance=bal["balance"] if bal else 0,
                    consumed_credits=done["credits_consumed"], consumed_total=bal["consumed"] if bal else 0,
                    is_cached=True, event_id=done["id"], reason="idempotent_replay",
                )

            orig = self._conn.execute(
                """
                SELECT id, event_type, credits_consumed,
                       (julianday('now') - julianday(timestamp)) * 86400.0 AS age_s
                FROM usage_events WHERE license_id = ? AND idempotency_key = ?
                """,
                (license_id, idempotency_key),
            ).fetchone()
            if orig is None or orig["credits_consumed"] <= 0 or orig["event_type"] == "refund":
                raise DomainError("No deduction found for this idempotency key.",
                                  details={"idempotency_key": idempotency_key},
                                  status_code=404, code="DEDUCTION_NOT_FOUND")
            if window_seconds <= 0 or orig["age_s"] > window_seconds:
                raise DomainError("Refund window expired for this deduction.",
                                  details={"idempotency_key": idempotency_key, "window_seconds": window_seconds},
                                  status_code=409, code="REFUND_WINDOW_EXPIRED")

            credits = int(orig["credits_consumed"])
            row = self._conn.execute(
                """
                UPDATE quotas
                SET balance = MIN(balance + ?, total_allowance),
                    consumed = MAX(consumed - ?, 0),
                    updated_at = CURRENT_TIMESTAMP
                WHERE license_id = ?
                RETURNING balance, consumed
                """,
                (credits, credits, license_id),
            ).fetchone()
            if row is None:
                raise LicenseNotFoundError(f"Quota record for license '{license_id}' not found.")

            event_id = str(uuid.uuid4())
            meta = {"refund_of": orig["id"], "reason": reason} if reason else {"refund_of": orig["id"]}
            self._conn.execute(
                """
                INSERT INTO usage_events (id, license_id, event_type, credits_consumed, idempotency_key, metadata_json)
                VALUES (?, ?, 'refund', ?, ?, ?)
                """,
                (event_id, license_id, credits, refund_key, json.dumps(meta)),
            )
            return CreditDeductResult(
                success=True, remaining_balance=row["balance"], consumed_credits=credits,
                consumed_total=row["consumed"], is_cached=False, event_id=event_id, reason="refund",
            )

    def replenish(
        self, license_id: str, credits: int, reset_cycle: bool = False
    ) -> QuotaLedger:
        """Replenishes credits on a license quota ledger via domain invariants."""
        if credits <= 0:
            raise ValueError(f"Replenish credits must be a positive integer; got {credits}")

        with transaction(self._conn):
            cur = self._conn.execute(
                "SELECT * FROM quotas WHERE license_id = ?", (license_id,)
            )
            row = cur.fetchone()
            if row is None:
                raise LicenseNotFoundError(f"Quota record for license '{license_id}' not found.")

            ledger = self._row_to_entity(row)
            ledger.replenish(credits, reset_consumed=reset_cycle)
            self.save(ledger)
            return ledger

    def record_usage(self, event: UsageEvent) -> None:
        meta_str = json.dumps(event.metadata) if event.metadata else None
        ts_str = event.timestamp.isoformat()
        self._conn.execute(
            """
            INSERT INTO usage_events (id, license_id, event_type, credits_consumed, idempotency_key, metadata_json, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.license_id,
                event.event_type,
                event.credits_consumed,
                event.idempotency_key,
                meta_str,
                ts_str,
            ),
        )

    def get_usage_history(self, license_id: str, limit: int = 50) -> list[UsageEvent]:
        cur = self._conn.execute(
            "SELECT * FROM usage_events WHERE license_id = ? ORDER BY timestamp DESC LIMIT ?",
            (license_id, limit),
        )
        events = []
        for r in cur.fetchall():
            ts = (
                datetime.fromisoformat(r["timestamp"])
                if isinstance(r["timestamp"], str)
                else r["timestamp"]
            )
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
            events.append(
                UsageEvent(
                    id=r["id"],
                    license_id=r["license_id"],
                    event_type=r["event_type"],
                    credits_consumed=r["credits_consumed"],
                    idempotency_key=r["idempotency_key"],
                    metadata=meta,
                    timestamp=ts,
                )
            )
        return events

    def get_usage_by_idempotency(self, idempotency_key: str) -> Optional[UsageEvent]:
        cur = self._conn.execute(
            "SELECT * FROM usage_events WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        r = cur.fetchone()
        if not r:
            return None
        ts = (
            datetime.fromisoformat(r["timestamp"])
            if isinstance(r["timestamp"], str)
            else r["timestamp"]
        )
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
        return UsageEvent(
            id=r["id"],
            license_id=r["license_id"],
            event_type=r["event_type"],
            credits_consumed=r["credits_consumed"],
            idempotency_key=r["idempotency_key"],
            metadata=meta,
            timestamp=ts,
        )

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> QuotaLedger:
        reset_at = (
            datetime.fromisoformat(row["last_reset_at"])
            if isinstance(row["last_reset_at"], str)
            else row["last_reset_at"]
        )
        updated_at = (
            datetime.fromisoformat(row["updated_at"])
            if isinstance(row["updated_at"], str)
            else row["updated_at"]
        )
        if reset_at.tzinfo is None:
            reset_at = reset_at.replace(tzinfo=timezone.utc)
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        return QuotaLedger(
            id=row["id"],
            license_id=row["license_id"],
            total_allowance=row["total_allowance"],
            balance=row["balance"],
            consumed=row["consumed"],
            last_reset_at=reset_at,
            updated_at=updated_at,
        )
