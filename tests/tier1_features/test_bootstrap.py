"""Tier 1: container entrypoint first-boot secret provisioning (app.bootstrap)."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from app.bootstrap import (
    GENERATORS,
    LITESTREAM_CONFIG,
    litestream_config,
    litestream_wrap,
    SECRETS_FILENAME,
    default_args,
    provision_secrets,
    read_secrets_file,
    resolve_data_dir,
)
from app.config import Settings
from app.infrastructure.security.ed25519_signer import Ed25519Signer


class TestBootstrap(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"
        self.logs: list[str] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, env: dict[str, str]) -> list[str]:
        return provision_secrets(env, self.data, self.logs.append)

    def test_first_boot_generates_all_and_passes_production_check(self) -> None:
        env = {"ENVIRONMENT": "production"}
        generated = self._run(env)
        self.assertEqual(generated, list(GENERATORS))
        path = self.data / SECRETS_FILENAME
        self.assertTrue(path.exists())
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        # The resulting environment must satisfy the existing production fail-fast check.
        Settings(_env_file=None, **{k: env[k] for k in GENERATORS}, ED25519_PUBLIC_KEY_HEX="", ENVIRONMENT="production").validate_production_secrets()
        signer = Ed25519Signer(private_key_hex=env["ED25519_PRIVATE_KEY_HEX"])
        self.assertTrue(any(signer.get_public_key_hex() in m for m in self.logs))
        self.assertTrue(any(env["ADMIN_API_KEY"] in m for m in self.logs))

    def test_second_boot_reuses_stored_secrets_and_is_silent(self) -> None:
        first: dict[str, str] = {}
        self._run(first)
        self.logs.clear()
        second: dict[str, str] = {}
        self.assertEqual(self._run(second), [])
        self.assertEqual(self.logs, [])
        for key in GENERATORS:
            self.assertEqual(first[key], second[key])

    def test_operator_env_wins_and_is_never_written(self) -> None:
        env = {"ADMIN_API_KEY": "kf_operator_supplied_admin_key_123", "SECRET_KEY": "  "}
        generated = self._run(env)
        self.assertNotIn("ADMIN_API_KEY", generated)
        self.assertIn("SECRET_KEY", generated)  # blank counts as unset
        self.assertEqual(env["ADMIN_API_KEY"], "kf_operator_supplied_admin_key_123")
        self.assertNotIn("ADMIN_API_KEY", read_secrets_file(self.data / SECRETS_FILENAME))

    def test_public_key_without_private_is_not_paired_with_random_key(self) -> None:
        env = {"ED25519_PUBLIC_KEY_HEX": "00" * 32}
        self.assertNotIn("ED25519_PRIVATE_KEY_HEX", self._run(env))
        self.assertNotIn("ED25519_PRIVATE_KEY_HEX", env)

    def test_secrets_file_ignores_unknown_keys_and_unsafe_values(self) -> None:
        self.data.mkdir(parents=True)
        (self.data / SECRETS_FILENAME).write_text(
            "PATH=/evil\nSECRET_KEY=abc def\nADMIN_API_KEY=kf_ok_value_1234567\n", encoding="utf-8"
        )
        stored = read_secrets_file(self.data / SECRETS_FILENAME)
        self.assertEqual(stored, {"ADMIN_API_KEY": "kf_ok_value_1234567"})

    def test_webhook_placeholders_reject_signatures(self) -> None:
        env: dict[str, str] = {}
        self._run(env)
        self.assertTrue(env["STRIPE_WEBHOOK_SECRET"].startswith("whsec_unconfigured_"))
        self.assertNotEqual(env["STRIPE_WEBHOOK_SECRET"], env["LEMONSQUEEZY_WEBHOOK_SECRET"])

    def test_resolve_data_dir(self) -> None:
        self.assertEqual(resolve_data_dir({"DATABASE_URL": "sqlite:////app/data/keyforge.db"}), Path("/app/data"))
        self.assertEqual(resolve_data_dir({"DATABASE_URL": "sqlite:///data/keyforge.db"}), Path("data"))
        self.assertEqual(resolve_data_dir({"DATABASE_URL": "sqlite:///:memory:"}), Path("/app/data"))
        self.assertEqual(resolve_data_dir({"KEYFORGE_DATA_DIR": "/srv/kf"}), Path("/srv/kf"))
        self.assertEqual(resolve_data_dir({}), Path("/app/data"))

    def test_default_args_follow_platform_port(self) -> None:
        self.assertEqual(default_args({"PORT": "10000"})[-1], "10000")
        self.assertEqual(default_args({})[-1], "8000")


class _Done:
    def __init__(self, code: int) -> None:
        self.returncode = code


class TestLitestreamWrap(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "data" / "keyforge.db"
        self.env = {"DATABASE_URL": f"sqlite:///{self.db}", "LITESTREAM_BUCKET": "kf-backups",
                    "LITESTREAM_ENDPOINT": "https://acct.r2.cloudflarestorage.com", "LITESTREAM_PATH": "acme"}
        self.calls: list[list[str]] = []
        import app.bootstrap as b
        self._which, b.shutil.which = b.shutil.which, lambda name: "/usr/local/bin/litestream"

    def tearDown(self) -> None:
        import app.bootstrap as b
        b.shutil.which = self._which
        self._tmp.cleanup()
        if os.path.exists(LITESTREAM_CONFIG):
            os.remove(LITESTREAM_CONFIG)

    def _run(self, code: int = 0):
        def fake(cmd, *a, **k):
            self.calls.append(cmd)
            return _Done(code)
        return fake

    def test_no_backup_config_execs_cli_directly(self) -> None:
        argv = litestream_wrap({"DATABASE_URL": f"sqlite:///{self.db}"}, ["serve"], lambda m: None, self._run())
        self.assertEqual(argv[1:4], ["-m", "app.cli", "serve"])
        self.assertEqual(self.calls, [])

    def test_non_serve_commands_are_never_wrapped(self) -> None:
        argv = litestream_wrap(self.env, ["issue", "--email", "a@b.c"], lambda m: None, self._run())
        self.assertEqual(argv[1:4], ["-m", "app.cli", "issue"])

    def test_missing_db_restores_then_replicates(self) -> None:
        argv = litestream_wrap(self.env, ["serve", "--port", "8000"], lambda m: None, self._run(0))
        self.assertEqual(self.calls[0][1], "restore")
        self.assertIn("-if-replica-exists", self.calls[0])
        self.assertEqual(argv[:2], ["/usr/local/bin/litestream", "replicate"])
        self.assertIn("app.cli serve --port 8000", argv[-1])

    def test_restore_failure_fails_closed(self) -> None:
        with self.assertRaises(SystemExit):
            litestream_wrap(self.env, ["serve"], lambda m: None, self._run(1))

    def test_existing_db_skips_restore(self) -> None:
        self.db.parent.mkdir(parents=True)
        self.db.write_bytes(b"")
        litestream_wrap(self.env, ["serve"], lambda m: None, self._run(0))
        self.assertEqual(self.calls, [])

    def test_config_has_no_credentials_and_quotes_values(self) -> None:
        env = {**self.env, "LITESTREAM_SECRET_ACCESS_KEY": "s3cr3t", "LITESTREAM_PATH": 'a"b'}
        cfg = litestream_config(env, self.db)
        self.assertNotIn("s3cr3t", cfg)
        self.assertIn('path: "a\\"b"', cfg)
        self.assertIn("force-path-style: true", cfg)
        self.assertIsNone(litestream_config({}, self.db))


if __name__ == "__main__":
    unittest.main()
