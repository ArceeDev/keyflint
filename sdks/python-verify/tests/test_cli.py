"""v1.2: `keyflint-verify activate` edits MCP client configs safely."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from keyflint_verify.cli import activate, ActivateError, config_path, main

DATA = json.loads((Path(__file__).resolve().parents[2] / "vectors" / "vectors.json").read_text(encoding="utf-8"))
TOKEN = next(v for v in DATA["vectors"] if v["name"] == "valid_perpetual")["token"]


class TestActivate(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "claude_desktop_config.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, obj) -> None:
        self.path.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")

    def test_single_server_gets_license_and_backup(self) -> None:
        self.write({"mcpServers": {"weather": {"command": "npx", "args": ["w"]}}, "other": 1})
        self.assertEqual(activate(TOKEN, self.path), ["weather"])
        cfg = json.loads(self.path.read_text())
        self.assertEqual(cfg["mcpServers"]["weather"]["env"], {"KEYFLINT_LICENSE": TOKEN})
        self.assertEqual(cfg["other"], 1)
        self.assertEqual(json.loads(self.path.with_name(self.path.name + ".bak").read_text())["mcpServers"]
                         ["weather"], {"command": "npx", "args": ["w"]})

    def test_prefers_servers_already_using_keyflint(self) -> None:
        self.write({"mcpServers": {"a": {"command": "x"},
                                   "b": {"command": "y", "env": {"KEYFLINT_PUBLIC_KEYS": "ab", "KEYFORGE_LICENSE": "old"}}}})
        self.assertEqual(activate(TOKEN, self.path), ["b"])
        env = json.loads(self.path.read_text())["mcpServers"]["b"]["env"]
        self.assertEqual(env, {"KEYFLINT_PUBLIC_KEYS": "ab", "KEYFLINT_LICENSE": TOKEN})

    def test_ambiguous_requires_server_flag(self) -> None:
        self.write({"mcpServers": {"a": {"command": "x"}, "b": {"command": "y"}}})
        with self.assertRaises(ActivateError) as cm:
            activate(TOKEN, self.path)
        self.assertIn("--server", str(cm.exception))
        self.assertEqual(activate(TOKEN, self.path, server="b"), ["b"])

    def test_invalid_json_is_never_touched(self) -> None:
        self.write('{"mcpServers": {"a": ,}}')
        with self.assertRaises(ActivateError):
            activate(TOKEN, self.path)
        self.assertEqual(self.path.read_text(), '{"mcpServers": {"a": ,}}')
        self.assertFalse(self.path.with_name(self.path.name + ".bak").exists())

    def test_dry_run_and_main(self) -> None:
        self.write({"mcpServers": {"a": {"command": "x"}}})
        self.assertEqual(main(["activate", TOKEN, "--config", str(self.path), "--dry-run"]), 0)
        self.assertNotIn("env", json.loads(self.path.read_text())["mcpServers"]["a"])
        self.assertEqual(main(["activate", "not-a-token", "--config", str(self.path)]), 2)
        self.assertEqual(main(["activate", TOKEN, "--config", str(self.path)]), 0)
        self.assertIn("env", json.loads(self.path.read_text())["mcpServers"]["a"])

    def test_paths(self) -> None:
        home = Path("/h")
        self.assertEqual(config_path("claude", "Darwin", home),
                         home / "Library/Application Support/Claude/claude_desktop_config.json")
        self.assertEqual(config_path("cursor", "Linux", home), home / ".cursor/mcp.json")
        self.assertEqual(config_path("windsurf", "Windows", home), home / ".codeium/windsurf/mcp_config.json")


if __name__ == "__main__":
    unittest.main()
