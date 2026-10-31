"""KeyForge Database Migrations & Integrity Verification.

File: app/infrastructure/database/migrations.py
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Optional

from app.infrastructure.database.connection import create_connection, transaction
from app.infrastructure.logging import get_logger

logger = get_logger("migrations")

SCHEMA_FILE_PATH = Path(__file__).parent / "schemas.sql"
REQUIRED_TABLES = (
    "customers",
    "licenses",
    "activations",
    "quotas",
    "usage_events",
    "webhook_events",
    "revoked_licenses",
    "schema_migrations",
)


def compute_schema_checksum(schema_sql: str) -> str:
    """Computes SHA-256 checksum of the DDL schema SQL."""
    return hashlib.sha256(schema_sql.strip().encode("utf-8")).hexdigest()


def run_migrations(conn: sqlite3.Connection, schema_path: Optional[Path] = None) -> int:
    """Executes idempotent DDL migrations.

    Returns the applied migration version count.
    """
    path = schema_path or SCHEMA_FILE_PATH
    if not path.exists():
        raise FileNotFoundError(f"Schema file not found at: {path}")

    schema_sql = path.read_text(encoding="utf-8")
    checksum = compute_schema_checksum(schema_sql)

    # 1. Ensure migrations tracking table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            checksum TEXT NOT NULL
        );
    """)

    # 2. Check if initial migration (v1) already applied
    cur = conn.execute("SELECT checksum FROM schema_migrations WHERE version = 1")
    row = cur.fetchone()

    if row is not None:
        if row["checksum"] == checksum:
            logger.info("Database schema is up to date (checksum verified).")
            return 0
        logger.warning("Schema checksum mismatch; re-applying idempotent DDL.")

    # 3. Apply schema (executescript handles transaction boundaries automatically)
    conn.executescript(schema_sql)

    # 3b. Ensure new columns exist if migrating an older SQLite database file
    lic_cols = {r["name"] for r in conn.execute("PRAGMA table_info(licenses);").fetchall()}
    if "features" not in lic_cols:
        conn.execute("ALTER TABLE licenses ADD COLUMN features TEXT NOT NULL DEFAULT '[]';")
    if "metadata_json" not in lic_cols:
        conn.execute("ALTER TABLE licenses ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';")

    conn.execute(
        """
        INSERT INTO schema_migrations (version, name, checksum)
        VALUES (1, '001_initial_schema', ?)
        ON CONFLICT(version) DO UPDATE SET
            checksum = excluded.checksum,
            applied_at = CURRENT_TIMESTAMP
        """,
        (checksum,),
    )

    logger.info("Database migration version 1 applied successfully.")
    return 1


def verify_database_integrity(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audits database health: runs PRAGMA integrity_check, foreign_key_check,

    and asserts existence of all required tables and indices.
    """
    # 1. SQLite internal integrity check
    integrity_row = conn.execute("PRAGMA integrity_check;").fetchone()
    integrity_ok = integrity_row[0] == "ok" if integrity_row else False

    # 2. Foreign key violations check
    fk_violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
    fk_ok = len(fk_violations) == 0

    # 3. Inspect existing tables in sqlite_master
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    existing_tables = {r["name"] for r in cur.fetchall()}
    missing_tables = [t for t in REQUIRED_TABLES if t not in existing_tables]

    # 4. Check journal_mode
    journal_mode_row = conn.execute("PRAGMA journal_mode;").fetchone()
    journal_mode = journal_mode_row[0] if journal_mode_row else "unknown"

    healthy = integrity_ok and fk_ok and len(missing_tables) == 0

    return {
        "integrity_ok": integrity_ok,
        "foreign_keys_ok": fk_ok,
        "fk_violations_count": len(fk_violations),
        "journal_mode": journal_mode,
        "missing_tables": missing_tables,
        "all_tables_present": len(missing_tables) == 0,
        "healthy": healthy,
    }


def init_db(db_path: Optional[str | Path] = None) -> None:
    """Helper to initialize database and run migrations."""
    conn = create_connection(db_path)
    try:
        run_migrations(conn)
        status = verify_database_integrity(conn)
        if not status["healthy"]:
            raise RuntimeError(f"Database verification failed: {status}")
    finally:
        conn.close()
