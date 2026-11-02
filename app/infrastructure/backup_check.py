"""Periodic proof that the Litestream replica can rebuild the live database.

Replication errors only show up in logs, so nobody notices a broken backup until a restore
is needed. This restores the replica to a temp file, checks it is not behind the live DB, and
pings a dead-man heartbeat: if the pings stop (machine down, R2 credentials broken, replica
stale), the heartbeat service alerts.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger("keyflint.backup")

TABLES = ("licenses", "customers", "webhook_events")
SYNC_SLACK_SECONDS = 5  # replica syncs every 1s; rows newer than this may not be uploaded yet

# Last outcome, exposed by /api/v1/health.
status: dict[str, Any] = {"status": "disabled"}


def _counts(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        conn.close()


def verify_once(
    db_path: Path,
    config_path: Path,
    heartbeat_url: Optional[str] = None,
    binary: Optional[str] = None,
    slack_seconds: float = SYNC_SLACK_SECONDS,
) -> dict[str, Any]:
    """Restores the replica to a temp file; ok when every table has at least the live row count."""
    binary = binary or shutil.which("litestream")
    if not binary or not config_path.exists():
        return status  # backups not configured on this instance

    live = _counts(db_path)
    time.sleep(slack_seconds)
    error: Optional[str] = None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "verify.db"
        res = subprocess.run(
            [binary, "restore", "-config", str(config_path), "-o", str(out), str(db_path)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if res.returncode != 0:
            error = f"restore exit {res.returncode}: {res.stderr.strip()[-300:]}"
        else:
            restored = _counts(out)
            behind = {t: (restored[t], live[t]) for t in TABLES if restored[t] < live[t]}
            if behind:
                error = f"replica behind live db (restored, live): {behind}"

    status.clear()
    status.update(
        status="ok" if error is None else "failed",
        checked_at=datetime.now(timezone.utc).isoformat(),
        live_counts=live,
        **({"error": error} if error else {}),
    )
    if error:
        logger.error(f"BACKUP VERIFICATION FAILED: {error}")
    else:
        logger.info(f"Backup verified: replica restores with counts >= {live}")

    if heartbeat_url:
        try:
            httpx.get(heartbeat_url if error is None else heartbeat_url.rstrip("/") + "/fail", timeout=10.0)
        except Exception as exc:  # a heartbeat outage must not kill the loop
            logger.warning(f"Backup heartbeat ping failed: {exc}")
    return status
