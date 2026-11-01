"""Tier 1: KeyForge Managed provisioning script (scripts/managed/kf_managed.py) with a fake flyctl."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("kf_managed", ROOT / "scripts" / "managed" / "kf_managed.py")
kf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kf)

BACKUP_ENV = {"KF_BACKUP_BUCKET": "kf-backups", "KF_BACKUP_ENDPOINT": "https://acct.r2.cloudflarestorage.com",
              "LITESTREAM_ACCESS_KEY_ID": "AKIDEXAMPLE", "LITESTREAM_SECRET_ACCESS_KEY": "s3cr3t-backup-key"}


class FakeFly:
    def __init__(self, fail_on: str | None = None, apps: list[str] | None = None) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.fail_on, self.apps = fail_on, apps or []

    def __call__(self, cmd, input=None, text=True, capture_output=False):
        self.calls.append((cmd, input))
        if self.fail_on and self.fail_on in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        out = json.dumps([{"Name": n} for n in self.apps]) if "list" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, out, "")


class TestManagedProvision(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["KF_VAULT_DIR"] = self._tmp.name
        self.vault = Path(self._tmp.name)
        self.out: list[str] = []

    def tearDown(self) -> None:
        os.environ.pop("KF_VAULT_DIR", None)
        self._tmp.cleanup()

    def _fly(self, fake: FakeFly) -> "kf.Fly":
        return kf.Fly(runner=fake, out=self.out.append)

    def test_create_runs_expected_flyctl_sequence_and_keeps_secrets_off_argv(self) -> None:
        fake = FakeFly()
        meta = kf.cmd_create(self._fly(fake), "acme", "mad", "ghcr.io/arceedev/keyforge:1.2.0",
                             "lic.acme.com", None, dict(BACKUP_ENV))
        verbs = [c[0][1:3] for c in fake.calls]
        self.assertEqual(verbs, [["apps", "create"], ["volumes", "create"], ["secrets", "import"],
                                 ["deploy", "--app"], ["certs", "add"]])
        deploy = fake.calls[3][0]
        self.assertIn("--ha=false", deploy)  # SQLite: exactly one machine
        self.assertIn("kf-acme", deploy)
        stdin = fake.calls[2][1]
        env_file = (self.vault / "acme.env").read_text()
        for line in env_file.splitlines():
            self.assertIn(line, stdin)  # Fly gets exactly the vault copy
        argv_text = " ".join(" ".join(c[0]) for c in fake.calls)
        for secret in (BACKUP_ENV["LITESTREAM_SECRET_ACCESS_KEY"], env_file.split("ADMIN_API_KEY=")[1].split()[0]):
            self.assertNotIn(secret, argv_text)
        self.assertIn("LITESTREAM_PATH=acme", stdin)
        self.assertEqual(meta["url"], "https://lic.acme.com")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE((self.vault / "acme.env").stat().st_mode), 0o600)

    def test_generated_secrets_pass_production_check(self) -> None:
        kf.cmd_create(self._fly(FakeFly()), "beta", "mad", "img", None, None, dict(BACKUP_ENV))
        vals = dict(l.split("=", 1) for l in (self.vault / "beta.env").read_text().splitlines())
        Settings(_env_file=None, ENVIRONMENT="production", ED25519_PUBLIC_KEY_HEX="",
                 **{k: vals[k] for k in ("SECRET_KEY", "ED25519_PRIVATE_KEY_HEX", "ADMIN_API_KEY",
                                         "STRIPE_WEBHOOK_SECRET", "LEMONSQUEEZY_WEBHOOK_SECRET")}
                 ).validate_production_secrets()

    def test_vault_written_before_fly_so_a_failed_deploy_loses_nothing(self) -> None:
        with self.assertRaises(SystemExit):
            kf.cmd_create(self._fly(FakeFly(fail_on="deploy")), "gamma", "mad", "img", None, None, dict(BACKUP_ENV))
        self.assertTrue((self.vault / "gamma.env").exists())
        with self.assertRaises(SystemExit):  # and it refuses to overwrite an existing customer key
            kf.cmd_create(self._fly(FakeFly()), "gamma", "mad", "img", None, None, dict(BACKUP_ENV))

    def test_backup_required_unless_explicitly_skipped(self) -> None:
        with self.assertRaises(SystemExit):
            kf.cmd_create(self._fly(FakeFly()), "delta", "mad", "img", None, None, {})
        meta = kf.cmd_create(self._fly(FakeFly()), "delta", "mad", "img", None, None, {}, require_backup=False)
        self.assertFalse(meta["backup"])
        with self.assertRaises(SystemExit):
            kf.backup_settings("x", {"KF_BACKUP_BUCKET": "b"})  # bucket without credentials

    def test_slug_validation(self) -> None:
        for bad in ("A", "ab", "-acme", "acme-", "ac me", "acme;rm", "x" * 41):
            with self.assertRaises(SystemExit):
                kf.validate_slug(bad)
        self.assertEqual(kf.validate_slug("acme-01"), "acme-01")

    def test_destroy_requires_confirmation_and_archives_vault(self) -> None:
        kf.cmd_create(self._fly(FakeFly()), "omega", "mad", "img", None, None, dict(BACKUP_ENV))
        with self.assertRaises(SystemExit):
            kf.cmd_destroy(self._fly(FakeFly()), "omega", None)
        fake = FakeFly()
        kf.cmd_destroy(self._fly(fake), "omega", "omega")
        self.assertEqual(fake.calls[0][0], ["fly", "apps", "destroy", "kf-omega", "--yes"])
        self.assertFalse((self.vault / "omega.env").exists())
        self.assertTrue(any(p.name.startswith("omega.env.destroyed-") for p in self.vault.iterdir()))

    def test_upgrade_all_targets_only_managed_apps(self) -> None:
        fake = FakeFly(apps=["kf-acme", "other-app", "kf-beta"])
        fly = self._fly(fake)
        kf.cmd_upgrade(fly, kf.managed_slugs(fly), "ghcr.io/arceedev/keyforge:1.2.1")
        deployed = [c[0][3] for c in fake.calls if c[0][1] == "deploy"]
        self.assertEqual(deployed, ["kf-acme", "kf-beta"])

    def test_dry_run_runs_nothing_and_redacts_stdin(self) -> None:
        fake = FakeFly()
        fly = kf.Fly(dry_run=True, runner=fake, out=self.out.append)
        kf.cmd_create(fly, "zeta", "mad", "img", None, None, dict(BACKUP_ENV))
        self.assertEqual(fake.calls, [])
        self.assertFalse((self.vault / "zeta.env").exists())
        self.assertTrue(any("redacted" in line for line in self.out))
        self.assertFalse(any(BACKUP_ENV["LITESTREAM_SECRET_ACCESS_KEY"] in line for line in self.out))


if __name__ == "__main__":
    unittest.main()
