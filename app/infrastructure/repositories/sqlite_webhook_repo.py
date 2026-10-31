"""KeyForge SQLite Webhook Repository.

File: app/infrastructure/repositories/sqlite_webhook_repo.py
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.domain.entities.webhook import WebhookRecord
from app.domain.interfaces.webhook_repository import IWebhookRepository
from app.infrastructure.database.connection import transaction


class SqliteWebhookRepo(IWebhookRepository):
    """SQLite implementation of Webhook Repository for idempotency and replay defense."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, record: WebhookRecord) -> None:
        processed_str = record.processed_at.isoformat()
        with transaction(self._conn):
            self._conn.execute(
                """
                INSERT INTO webhook_events (id, event_id, provider, event_type, payload_hash, status, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    status = excluded.status,
                    processed_at = excluded.processed_at
                """,
                (
                    record.id,
                    record.event_id,
                    record.provider,
                    record.event_type,
                    record.payload_hash,
                    record.status,
                    processed_str,
                ),
            )

    def get_by_event_id(self, event_id: str) -> Optional[WebhookRecord]:
        cur = self._conn.execute(
            """
            SELECT id, event_id, provider, event_type, payload_hash, status, processed_at
            FROM webhook_events
            WHERE event_id = ?
            """,
            (event_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        proc_at = row["processed_at"]
        if isinstance(proc_at, str):
            processed_at = datetime.fromisoformat(proc_at)
        else:
            processed_at = datetime.now(timezone.utc)

        return WebhookRecord(
            id=row["id"],
            event_id=row["event_id"],
            provider=row["provider"],
            event_type=row["event_type"],
            payload_hash=row["payload_hash"],
            status=row["status"],
            processed_at=processed_at,
        )

    def is_processed(self, event_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM webhook_events WHERE event_id = ? AND status = 'processed'",
            (event_id,),
        )
        return cur.fetchone() is not None
