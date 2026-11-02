"""Tier 2: the licenses CHECK rebuild (indie/agency) keeps every row and child row."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.infrastructure.database.connection import create_connection
from app.infrastructure.database.migrations import run_migrations

NEW_CHECK = "CHECK(tier IN ('community', 'indie', 'agency', 'pro', 'studio', 'lifetime'))"
LEGACY_CHECK = "CHECK(tier IN ('community', 'pro', 'studio', 'lifetime'))"
SCHEMA = Path(__file__).resolve().parents[2] / "app/infrastructure/database/schemas.sql"


class TestTierCheckMigration(unittest.TestCase):
    def test_rebuild_preserves_rows_and_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"
            legacy = sqlite3.connect(db, isolation_level=None)
            legacy.execute("PRAGMA foreign_keys = ON")
            legacy.executescript(SCHEMA.read_text().replace(NEW_CHECK, LEGACY_CHECK))
            legacy.execute("INSERT INTO customers(id, email) VALUES ('c1', 'a@example.com')")
            legacy.execute(
                "INSERT INTO licenses(id, customer_id, license_key, tier, status, signature, metadata_json) "
                "VALUES ('l1', 'c1', 'K1', 'pro', 'active', 's', '{\"payment_refs\": [\"pi_1\"]}')"
            )
            children = [
                r[0]
                for r in legacy.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%REFERENCES licenses%'"
                )
            ]
            self.assertTrue(children)
            for table in children:
                cols = legacy.execute(f"PRAGMA table_info({table})").fetchall()
                values = {}
                for _, name, typ, notnull, default, pk in cols:
                    if notnull and default is None and not pk:
                        values[name] = "l1" if name == "license_id" else (1 if "INT" in typ.upper() else f"v_{name}")
                    elif pk and "INT" not in typ.upper():
                        values[name] = f"{table}_1"
                legacy.execute(
                    f"INSERT INTO {table}({','.join(values)}) VALUES({','.join('?' * len(values))})",
                    list(values.values()),
                )
            before = {t: legacy.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in children + ["licenses"]}
            legacy.close()

            conn = create_connection(db)
            try:
                run_migrations(conn)
                run_migrations(conn)  # idempotent
                after = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in before}
                self.assertEqual(before, after)
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(
                    conn.execute("SELECT metadata_json FROM licenses WHERE id='l1'").fetchone()[0],
                    '{"payment_refs": ["pi_1"]}',
                )
                conn.execute(
                    "INSERT INTO licenses(id, customer_id, license_key, tier, status, signature) "
                    "VALUES ('l2', 'c1', 'K2', 'indie', 'active', 's')"
                )
                self.assertIsNone(
                    conn.execute("SELECT name FROM sqlite_master WHERE name='licenses_new'").fetchone()
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
