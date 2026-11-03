"""Tier 1: v1.2 SQLite maintenance — opt-in usage-event retention, WAL checkpoint, index cleanup."""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path


class TestMaintenance(unittest.TestCase):
    def setUp(self):
        from app.infrastructure.database.connection import create_connection
        from app.infrastructure.database.migrations import run_migrations

        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "kf.db"
        self.conn = create_connection(self.path)
        run_migrations(self.conn)
        self.conn.execute("INSERT INTO customers (id, email) VALUES ('c1', 'a@b.c')")
        self.conn.execute(
            "INSERT INTO licenses (id, customer_id, license_key, tier, status, signature) "
            "VALUES ('l1', 'c1', 'LIC-PRO-x.y', 'pro', 'active', 'sig')"
        )
        for age_days in (400, 31, 29, 0):
            for _ in range(3):
                self.conn.execute(
                    "INSERT INTO usage_events (id, license_id, event_type, credits_consumed, idempotency_key, timestamp) "
                    "VALUES (?, 'l1', 'api_call', 1, ?, datetime('now', ?))",
                    (str(uuid.uuid4()), str(uuid.uuid4()), f"-{age_days} days"),
                )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _count(self):
        return self.conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]

    def test_default_keeps_everything(self):
        from app.infrastructure.maintenance import run_maintenance
        summary = run_maintenance(self.conn, retention_days=0, checkpoint=False)
        self.assertEqual((summary["deleted_usage_events"], self._count()), (0, 12))

    def test_retention_deletes_only_older_rows_and_enforces_minimum(self):
        from app.infrastructure import maintenance
        self.assertEqual(maintenance.run_maintenance(self.conn, retention_days=30, checkpoint=False)
                         ["deleted_usage_events"], 6)
        self.assertEqual(self._count(), 6)
        # 1 day is raised to the 30-day minimum: nothing newer than 30 days goes.
        self.assertEqual(maintenance.run_maintenance(self.conn, retention_days=1, checkpoint=False)
                         ["deleted_usage_events"], 0)

    def test_batched_delete(self):
        from app.infrastructure import maintenance
        orig = maintenance.DELETE_BATCH
        maintenance.DELETE_BATCH = 2
        try:
            self.assertEqual(maintenance.run_maintenance(self.conn, retention_days=30, checkpoint=False)
                             ["deleted_usage_events"], 6)
        finally:
            maintenance.DELETE_BATCH = orig

    def test_checkpoint_truncates_wal(self):
        from app.infrastructure.maintenance import run_maintenance
        summary = run_maintenance(self.conn, checkpoint=True)
        self.assertEqual(summary["checkpoint"]["busy"], 0)
        wal = Path(str(self.path) + "-wal")
        self.assertTrue(not wal.exists() or wal.stat().st_size == 0)

    def test_redundant_index_is_dropped(self):
        names = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertNotIn("idx_usage_idempotency", names)
        plan = " ".join(str(tuple(r)) for r in self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM usage_events WHERE license_id = 'l1' AND idempotency_key = 'k'"))
        self.assertIn("sqlite_autoindex_usage_events", plan)  # UNIQUE index still serves idempotency


if __name__ == "__main__":
    unittest.main()
