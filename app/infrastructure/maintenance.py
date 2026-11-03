"""Periodic SQLite maintenance (v1.2).

Idempotency lives in ``usage_events`` (``UNIQUE(license_id, idempotency_key)``), which is also the
per-license usage history, so nothing is deleted unless the operator opts in with
``USAGE_EVENTS_RETENTION_DAYS`` (minimum 30 days, far beyond the refund window). Lookups stay
O(log n) on the B-tree; what grows is the file and the backup snapshots.

WAL checkpoints: when Litestream replicates the database it owns checkpointing (an external
TRUNCATE checkpoint can force it to start a new generation), so the job only checkpoints when
Litestream is not running.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from app.infrastructure.database.connection import transaction

logger = logging.getLogger("keyflint.maintenance")

MIN_RETENTION_DAYS = 30
DELETE_BATCH = 5000  # short write transactions so live deducts are never blocked for long


def effective_retention_days(days: int) -> int:
    if days <= 0:
        return 0
    if days < MIN_RETENTION_DAYS:
        logger.warning(f"USAGE_EVENTS_RETENTION_DAYS={days} raised to the minimum of {MIN_RETENTION_DAYS}.")
        return MIN_RETENTION_DAYS
    return days


def litestream_active(config_path: str | Path) -> bool:
    return shutil.which("litestream") is not None and Path(config_path).exists()


def run_maintenance(
    conn: sqlite3.Connection,
    retention_days: int = 0,
    checkpoint: bool = True,
) -> dict[str, Any]:
    """Purges usage events older than the retention (if enabled) and optionally checkpoints the WAL."""
    summary: dict[str, Any] = {"deleted_usage_events": 0, "checkpoint": None}
    days = effective_retention_days(retention_days)
    if days:
        cutoff = f"-{days} days"
        while True:
            with transaction(conn):
                cur = conn.execute(
                    """
                    DELETE FROM usage_events WHERE rowid IN (
                        SELECT rowid FROM usage_events
                        WHERE julianday(timestamp) < julianday('now', ?)
                        LIMIT ?
                    )
                    """,
                    (cutoff, DELETE_BATCH),
                )
                n = cur.rowcount
            summary["deleted_usage_events"] += n
            if n < DELETE_BATCH:
                break
    if checkpoint:
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        # (busy, wal_frames, checkpointed_frames); busy=1 means readers kept it from finishing.
        summary["checkpoint"] = {"busy": row[0], "log": row[1], "checkpointed": row[2]} if row else None
    return summary
