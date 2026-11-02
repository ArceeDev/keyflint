"""Tier 1: `keyflint init` environment bootstrap."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli
from app.config import Settings
from app.infrastructure.security.ed25519_signer import Ed25519Signer

ROOT = Path(__file__).resolve().parents[2]


def _parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.split("  #", 1)[0].strip()
    return out


class TestCliInit(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.runner = CliRunner()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_production_env_passes_fail_fast_validation(self) -> None:
        out = self.dir / ".env"
        res = self.runner.invoke(cli, ["init", "--env", "production", "-o", str(out)])
        self.assertEqual(res.exit_code, 0, res.output)
        report = json.loads(res.output)
        env = _parse_env(out.read_text(encoding="utf-8"))

        self.assertEqual(env["ENVIRONMENT"], "production")
        self.assertNotIn(env["ED25519_PRIVATE_KEY_HEX"], res.output)
        self.assertNotIn(env["SECRET_KEY"], res.output)
        self.assertNotIn(env["ADMIN_API_KEY"], res.output)
        self.assertEqual(report["ED25519_PUBLIC_KEY_HEX"], env["ED25519_PUBLIC_KEY_HEX"])
        self.assertEqual(
            Ed25519Signer(private_key_hex=env["ED25519_PRIVATE_KEY_HEX"]).get_public_key_hex(),
            env["ED25519_PUBLIC_KEY_HEX"],
        )
        if (ROOT / ".env.production.example").is_file():
            self.assertIn("STRIPE_WEBHOOK_SECRET", report["fill_manually"])

        settings = Settings(
            ENVIRONMENT="production",
            SECRET_KEY=env["SECRET_KEY"],
            ED25519_PRIVATE_KEY_HEX=env["ED25519_PRIVATE_KEY_HEX"],
            ED25519_PUBLIC_KEY_HEX=env["ED25519_PUBLIC_KEY_HEX"],
            ADMIN_API_KEY=env["ADMIN_API_KEY"],
            STRIPE_WEBHOOK_SECRET="whsec_real_value_for_test",
            LEMONSQUEEZY_WEBHOOK_SECRET="ls_real_value_for_test",
        )
        settings.validate_production_secrets()

    def test_refuses_overwrite_without_force(self) -> None:
        out = self.dir / ".env"
        out.write_text("ED25519_PRIVATE_KEY_HEX=keep_me\n", encoding="utf-8")
        res = self.runner.invoke(cli, ["init", "-o", str(out)])
        self.assertEqual(res.exit_code, 1)
        self.assertIn("keep_me", out.read_text(encoding="utf-8"))

        res = self.runner.invoke(cli, ["init", "-o", str(out), "--force"])
        self.assertEqual(res.exit_code, 0, res.output)
        self.assertNotIn("keep_me", out.read_text(encoding="utf-8"))

    def test_each_run_generates_unique_keys_and_keeps_template_settings(self) -> None:
        tpl = self.dir / "tpl.env"
        tpl.write_text("# header\nPORT=9999\nSECRET_KEY=old\n", encoding="utf-8")
        a, b = self.dir / "a.env", self.dir / "b.env"
        for path in (a, b):
            res = self.runner.invoke(cli, ["init", "--template", str(tpl), "-o", str(path)])
            self.assertEqual(res.exit_code, 0, res.output)
        ea, eb = _parse_env(a.read_text(encoding="utf-8")), _parse_env(b.read_text(encoding="utf-8"))
        self.assertTrue(a.read_text(encoding="utf-8").startswith("# header\n"))
        self.assertEqual(ea["PORT"], "9999")
        self.assertEqual(ea["ENVIRONMENT"], "development")
        self.assertNotEqual(ea["ED25519_PRIVATE_KEY_HEX"], eb["ED25519_PRIVATE_KEY_HEX"])
        self.assertNotEqual(ea["SECRET_KEY"], "old")
        if os.name == "posix":
            self.assertEqual(a.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
