"""KeyFlint Persistence - SQLite WAL Connection Factory.

File: app/infrastructure/database/connection.py
"""

from __future__ import annotations

import atexit
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from app.config import get_settings


_SHARED_MEMORY_HOLDER: Optional[sqlite3.Connection] = None


def close_shared_memory_holder() -> None:
    """Closes the shared in-memory SQLite holder cleanly to avoid ResourceWarning on exit."""
    global _SHARED_MEMORY_HOLDER
    if _SHARED_MEMORY_HOLDER is not None:
        try:
            _SHARED_MEMORY_HOLDER.close()
        except Exception:
            pass
        _SHARED_MEMORY_HOLDER = None


atexit.register(close_shared_memory_holder)


def get_shared_memory_holder() -> sqlite3.Connection:
    """Keeps SQLite shared in-memory database alive across connection lifecycles."""
    global _SHARED_MEMORY_HOLDER
    if _SHARED_MEMORY_HOLDER is None:
        _SHARED_MEMORY_HOLDER = sqlite3.connect(
            "file:keyflint_shared_mem?mode=memory&cache=shared",
            uri=True,
            isolation_level=None,
            check_same_thread=False,
        )
        _SHARED_MEMORY_HOLDER.row_factory = sqlite3.Row
        from app.infrastructure.database.migrations import run_migrations
        run_migrations(_SHARED_MEMORY_HOLDER)
    return _SHARED_MEMORY_HOLDER


def reset_shared_memory_db() -> None:
    """Clears all mutable rows in the shared in-memory database for deterministic test isolation."""
    holder = get_shared_memory_holder()
    for table in (
        "usage_events",
        "quotas",
        "activations",
        "revoked_licenses",
        "licenses",
        "webhook_events",
        "customers",
    ):
        holder.execute(f"DELETE FROM {table};")


def create_connection(
    db_path: Optional[str | Path] = None,
    timeout: float = 10.0,
    check_same_thread: bool = False,
) -> sqlite3.Connection:
    """Creates and bootstraps a SQLite connection configured with high-performance WAL pragmas.

    Uses isolation_level=None (autocommit mode) so that transactions are explicitly
    managed using BEGIN IMMEDIATE / COMMIT / ROLLBACK, preventing premature lock escalation.
    """
    if db_path is None:
        settings = get_settings()
        db_path = settings.DATABASE_PATH

    db_str = str(db_path)
    if db_str == ":memory:":
        get_shared_memory_holder()
        conn = sqlite3.connect(
            "file:keyflint_shared_mem?mode=memory&cache=shared",
            uri=True,
            timeout=timeout,
            isolation_level=None,
            check_same_thread=check_same_thread,
        )
    else:
        target_path = Path(db_str)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            db_str,
            timeout=timeout,
            isolation_level=None,  # Explicit transaction control
            check_same_thread=check_same_thread,
        )
    conn.row_factory = sqlite3.Row

    # Performance & Concurrency Pragmas
    # WAL is supported on disk files; on :memory: SQLite silently keeps 'memory' mode
    if db_str != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -64000;")

    return conn


@contextmanager
def get_db(db_path: Optional[str | Path] = None) -> Iterator[sqlite3.Connection]:
    """FastAPI / worker context manager yielding a managed connection that closes on scope exit."""
    conn = create_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Context manager for atomic write operations.

    Executes 'BEGIN IMMEDIATE' to immediately lock the database for writes, preventing deadlocks.
    Supports nested transactions via SQLite SAVEPOINTS if a transaction is already open.
    Commits on clean exit, rolls back on exception.
    """
    if conn.in_transaction:
        sp_id = f"sp_{secrets.token_hex(4)}"
        conn.execute(f"SAVEPOINT {sp_id}")
        try:
            yield conn
            conn.execute(f"RELEASE SAVEPOINT {sp_id}")
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {sp_id}")
            conn.execute(f"RELEASE SAVEPOINT {sp_id}")
            raise
    else:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            try:
                conn.execute("COMMIT")
            except sqlite3.OperationalError as e:
                if "no transaction is active" not in str(e).lower():
                    raise
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass  # Transaction was already aborted or rolled back
            raise
