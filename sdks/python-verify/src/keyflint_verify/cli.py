"""``keyflint-verify activate <TOKEN>``: put a license into an MCP client's config, safely.

    uvx keyflint-verify activate LIC-PRO-... [--client claude|cursor|windsurf] [--server NAME]
    pipx run keyflint-verify activate LIC-PRO-...

Finds the client's config file for this OS, writes a ``.bak`` copy, sets
``env.KEYFLINT_LICENSE`` on the target MCP server(s) and re-reads the result to make sure it is
valid JSON. Targets: ``--server NAME``; else servers that already use KeyFlint variables; else the
only server in the file. Same behaviour as ``npx keyflint-verify activate``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from . import __version__, verify_license

TOKEN_RE = re.compile(r"^LIC-[A-Za-z]+-[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
KEYFLINT_VARS = ("KEYFLINT_LICENSE", "KEYFLINT_PUBLIC_KEYS", "KEYFLINT_PUBLIC_KEY", "KEYFLINT_URL", "KEYFORGE_LICENSE")
CLIENTS = ("claude", "cursor", "windsurf")


def config_path(client: str, system: Optional[str] = None, home: Optional[Path] = None) -> Path:
    system = (system or platform.system()).lower()
    home = home or Path.home()
    if client == "claude":
        if system == "darwin":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if system == "windows":
            appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
        return Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "Claude" / "claude_desktop_config.json"
    if client == "cursor":
        return home / ".cursor" / "mcp.json"
    if client == "windsurf":
        return home / ".codeium" / "windsurf" / "mcp_config.json"
    raise ValueError(f"unknown client {client!r}")


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else text


def _safe_print(text: str, file: Any = sys.stdout) -> None:
    try:
        print(text, file=file)
    except UnicodeEncodeError:
        repl = text.replace("✓", "+").replace("✗", "x")
        try:
            print(repl, file=file)
        except UnicodeEncodeError:
            encoding = getattr(file, "encoding", "ascii") or "ascii"
            print(repl.encode(encoding, errors="replace").decode(encoding), file=file)


def pick_servers(servers: dict[str, Any], wanted: Optional[str]) -> list[str]:
    if wanted:
        return [wanted] if wanted in servers else []
    using = [n for n, cfg in servers.items()
             if isinstance(cfg, dict) and any(k in (cfg.get("env") or {}) for k in KEYFLINT_VARS)]
    if using:
        return using
    return list(servers) if len(servers) == 1 else []


class ActivateError(Exception):
    pass


def activate(token: str, path: Path, server: Optional[str] = None, dry_run: bool = False) -> list[str]:
    """Returns the server names updated. Raises ActivateError without touching the file on failure."""
    if not path.is_file():
        raise ActivateError(f"{path} not found. Add your MCP server to the client first, then run this again.")
    raw = path.read_text(encoding="utf-8-sig")
    try:
        config = json.loads(raw) if raw.strip() else {}
    except ValueError as exc:
        raise ActivateError(f"{path} is not valid JSON ({exc}); nothing was changed.") from None
    if not isinstance(config, dict):
        raise ActivateError(f"{path} does not contain a JSON object; nothing was changed.")
    servers = config.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        raise ActivateError(f"{path} has no \"mcpServers\". Add your MCP server first, then run this again.")
    targets = pick_servers(servers, server)
    if not targets:
        names = ", ".join(sorted(servers))
        hint = f"No server named {server!r}." if server else "Several MCP servers found."
        raise ActivateError(f"{hint} Choose one with --server NAME (available: {names}).")
    for name in targets:
        cfg = servers[name]
        if not isinstance(cfg, dict):
            raise ActivateError(f"Server {name!r} is not a JSON object; nothing was changed.")
        env = cfg.get("env")
        if env is not None and not isinstance(env, dict):
            raise ActivateError(f"Server {name!r} has a non-object \"env\"; nothing was changed.")
        cfg["env"] = {**(env or {}), "KEYFLINT_LICENSE": token}
        cfg["env"].pop("KEYFORGE_LICENSE", None)
    out = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    json.loads(out)  # the file we write must parse
    if not dry_run:
        shutil.copy2(path, path.with_name(path.name + ".bak"))
        tmp = path.with_name(path.name + ".keyflint-tmp")
        tmp.write_text(out, encoding="utf-8")
        os.replace(tmp, path)
        json.loads(path.read_text(encoding="utf-8"))
    return targets


def _check_token(token: str, servers_env: list[dict[str, Any]]) -> Optional[str]:
    """Offline signature check when a server already has KEYFLINT_PUBLIC_KEYS; returns a warning."""
    for env in servers_env:
        keys = env.get("KEYFLINT_PUBLIC_KEYS") or env.get("KEYFLINT_PUBLIC_KEY")
        if isinstance(keys, str) and keys.strip():
            from .mcp import _parse_keys_env

            r = verify_license(token, _parse_keys_env(keys))
            if not r.valid and r.error not in ("ERR_NODE_LOCK_VIOLATION", "ERR_DOMAIN_LOCK_VIOLATION"):
                return f"this license does not verify against the server's public key ({r.error})"
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="keyflint-verify", description="KeyFlint license tools")
    parser.add_argument("--version", action="version", version=f"keyflint-verify {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    act = sub.add_parser("activate", help="Add your KeyFlint license to Claude Desktop, Cursor or Windsurf")
    act.add_argument("token", help="your license key (LIC-...)")
    act.add_argument("--client", choices=CLIENTS + ("all",), default="all",
                     help="which app to configure (default: every app installed)")
    act.add_argument("--server", help="MCP server name in the config (default: auto-detect)")
    act.add_argument("--config", type=Path, help="explicit config file path (overrides --client)")
    act.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    args = parser.parse_args(argv)

    token = args.token.strip()
    if not TOKEN_RE.match(token):
        _safe_print(_color("✗ That does not look like a KeyFlint license (expected LIC-<TIER>-...).", "31"), file=sys.stderr)
        return 2

    if args.config:
        paths = [("custom", args.config.expanduser())]
    else:
        clients = CLIENTS if args.client == "all" else (args.client,)
        paths = [(c, config_path(c)) for c in clients]
        if args.client == "all":
            paths = [(c, p) for c, p in paths if p.is_file()]
            if not paths:
                _safe_print(_color("✗ No Claude Desktop, Cursor or Windsurf MCP config found. "
                                   "Use --client or --config.", "31"), file=sys.stderr)
                return 1

    updated = 0
    errors: list[str] = []
    for client, path in paths:
        try:
            names = activate(token, path, server=args.server, dry_run=args.dry_run)
        except ActivateError as exc:
            errors.append(f"{client}: {exc}")
            continue
        updated += 1
        cfg = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
        warn = _check_token(token, [cfg.get(n, {}).get("env") or {} for n in names])
        verb = "Would update" if args.dry_run else "Updated"
        _safe_print(_color(f"✓ {verb} {client} ({path}): {', '.join(names)}", "32"))
        if warn:
            _safe_print(_color(f"! Warning: {warn}", "33"))
    for e in errors:
        _safe_print(_color(f"✗ {e}", "31"), file=sys.stderr)
    if updated and not args.dry_run:
        _safe_print(_color("Done. Restart the app so it picks up the license. A .bak copy of each file was kept.", "32"))
    return 0 if updated else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
