"""Tier 1: hourly backup verification flags a stale or unrestorable replica and pings the heartbeat."""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

from app.infrastructure import backup_check


def _make_db(path: Path, licenses: int) -> None:
    conn = sqlite3.connect(path)
    for t in backup_check.TABLES:
        conn.execute(f"CREATE TABLE {t} (id INTEGER)")
    conn.executemany("INSERT INTO licenses VALUES (?)", [(i,) for i in range(licenses)])
    conn.commit()
    conn.close()


class TestBackupCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.live = self.tmp / "live.db"
        self.config = self.tmp / "litestream.yml"
        self.config.write_text("dbs: []\n")
        _make_db(self.live, licenses=3)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _restore_with(self, licenses: int, returncode: int = 0):
        def fake_run(argv, **kwargs):
            if returncode == 0:
                _make_db(Path(argv[argv.index("-o") + 1]), licenses)
            return subprocess.CompletedProcess(argv, returncode, "", "s3: access denied")
        return mock.patch("subprocess.run", side_effect=fake_run)

    def _verify(self):
        with mock.patch("httpx.get") as ping:
            result = backup_check.verify_once(
                self.live, self.config, "https://hc.example/abc", binary="litestream", slack_seconds=0
            )
        return dict(result), ping.call_args.args[0]

    def test_up_to_date_replica_pings_success(self):
        with self._restore_with(licenses=3):
            result, url = self._verify()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(url, "https://hc.example/abc")

    def test_stale_replica_pings_fail(self):
        with self._restore_with(licenses=2):
            result, url = self._verify()
        self.assertEqual(result["status"], "failed")
        self.assertIn("behind", result["error"])
        self.assertEqual(url, "https://hc.example/abc/fail")

    def test_restore_error_pings_fail(self):
        with self._restore_with(licenses=0, returncode=1):
            result, url = self._verify()
        self.assertEqual(result["status"], "failed")
        self.assertIn("access denied", result["error"])
        self.assertEqual(url, "https://hc.example/abc/fail")

    def test_loop_checks_one_minute_after_boot_then_every_interval(self):
        import asyncio
        from app import main

        delays: list[float] = []

        async def fake_sleep(seconds):
            delays.append(seconds)
            if len(delays) == 3:
                raise asyncio.CancelledError

        with mock.patch("asyncio.sleep", side_effect=fake_sleep), \
                mock.patch("app.infrastructure.backup_check.verify_once") as verify:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(main._backup_check_loop(3600, None))
        self.assertEqual(delays, [60, 3600, 3600])
        self.assertEqual(verify.call_count, 2)

    def test_unconfigured_instance_is_skipped(self):
        self.config.unlink()
        with mock.patch("subprocess.run") as run:
            backup_check.verify_once(self.live, self.config, binary="litestream", slack_seconds=0)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
