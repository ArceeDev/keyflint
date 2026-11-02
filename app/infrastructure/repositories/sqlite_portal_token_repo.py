"""KeyFlint SQLite repository for single-use customer portal magic links.

File: app/infrastructure/repositories/sqlite_portal_token_repo.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import sqlite3
from typing import Optional

from app.infrastructure.database.connection import transaction


def hash_portal_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SqlitePortalTokenRepo:
    """Stores only token hashes; redemption is atomic so a link works exactly once."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def count_recent(self, customer_id: str, since: datetime) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM portal_login_tokens WHERE customer_id = ? AND created_at >= ?",
            (customer_id, since.isoformat()),
        ).fetchone()
        return int(row[0])

    def create(self, token: str, customer_id: str, ttl_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        with transaction(self._conn):
            # Housekeeping: drop links that expired more than a day ago.
            self._conn.execute(
                "DELETE FROM portal_login_tokens WHERE expires_at < ?",
                ((now - timedelta(days=1)).isoformat(),),
            )
            self._conn.execute(
                "INSERT INTO portal_login_tokens (token_hash, customer_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (
                    hash_portal_token(token),
                    customer_id,
                    now.isoformat(),
                    (now + timedelta(seconds=ttl_seconds)).isoformat(),
                ),
            )

    def redeem(self, token: str) -> Optional[str]:
        """Marks the link used and returns its customer_id, or None if unknown/expired/already used."""
        now = datetime.now(timezone.utc).isoformat()
        token_hash = hash_portal_token(token)
        with transaction(self._conn):
            cur = self._conn.execute(
                "UPDATE portal_login_tokens SET used_at = ? "
                "WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
                (now, token_hash, now),
            )
            if cur.rowcount != 1:
                return None
            row = self._conn.execute(
                "SELECT customer_id FROM portal_login_tokens WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        return str(row["customer_id"]) if row else None
