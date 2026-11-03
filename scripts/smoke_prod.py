#!/usr/bin/env python3
"""Black-box production smoke test for KeyFlint (stdlib only; used by CI monitor + deploy).

    python scripts/smoke_prod.py                       # gateway + landing defaults
    python scripts/smoke_prod.py --retries 6 --delay 15  # after a deploy, wait for boot
    python scripts/smoke_prod.py --json                # machine-readable report

Exit code 0 = every check passed, 1 = at least one failed. It never sends credentials and
only calls public, read-only endpoints.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable

DEFAULT_GATEWAY = "https://licenses.keyflint.dev"
DEFAULT_SITE = "https://keyflint.dev"
USER_AGENT = "keyflint-smoke/1.0 (+https://github.com/ArceeDev/keyflint)"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    ms: int


Fetch = Callable[[str, float], "tuple[int, bytes]"]


def http_fetch(url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https URLs)
            return resp.status, resp.read(512_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(4096) if exc.fp else b""


def _json(body: bytes) -> dict:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def run_checks(gateway: str, site: str, *, fetch: Fetch = http_fetch, timeout: float = 10.0,
               slow_ms: int = 2500, require_backup: bool = True) -> list[Check]:
    gateway, site = gateway.rstrip("/"), site.rstrip("/")
    results: list[Check] = []

    def probe(name: str, url: str, judge: Callable[[int, bytes], "tuple[bool, str]"]) -> None:
        start = time.monotonic()
        try:
            code, body = fetch(url, timeout)
        except Exception as exc:  # network errors are a failed check, not a crash
            results.append(Check(name, False, f"{type(exc).__name__}: {exc}", int((time.monotonic() - start) * 1000)))
            return
        ms = int((time.monotonic() - start) * 1000)
        ok, detail = judge(code, body)
        if ok and ms > slow_ms:
            ok, detail = False, f"slow: {ms} ms > {slow_ms} ms"
        results.append(Check(name, ok, detail, ms))

    probe("gateway_ready", f"{gateway}/readyz",
          lambda c, b: (c == 200 and _json(b).get("ready") is True, f"HTTP {c}"))

    def health(c: int, b: bytes) -> tuple[bool, str]:
        data = _json(b)
        backup = (data.get("backup") or {}).get("status", "missing")
        if c != 200 or data.get("healthy") is not True:
            return False, f"HTTP {c}, healthy={data.get('healthy')}"
        if backup == "failed" or (require_backup and backup != "ok"):
            return False, f"backup={backup}"
        return True, f"backup={backup}, email={data.get('email_provider')}"

    probe("gateway_health", f"{gateway}/api/v1/health", health)
    probe("gateway_openapi", f"{gateway}/openapi.json",
          lambda c, b: (c == 200 and "paths" in _json(b), f"HTTP {c}"))
    probe("site_landing", f"{site}/",
          lambda c, b: (c == 200 and b"KeyFlint" in b and b"buy.stripe.com" in b, f"HTTP {c}"))
    probe("site_og_image", f"{site}/og.png",
          lambda c, b: (c == 200 and b[:8] == b"\x89PNG\r\n\x1a\n", f"HTTP {c}"))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gateway", default=DEFAULT_GATEWAY)
    ap.add_argument("--site", default=DEFAULT_SITE)
    ap.add_argument("--retries", type=int, default=1, help="attempts before reporting failure")
    ap.add_argument("--delay", type=float, default=20.0, help="seconds between attempts")
    ap.add_argument("--slow-ms", type=int, default=2500)
    ap.add_argument("--allow-backup-pending", action="store_true",
                    help="accept backup=disabled (first ~60 s after boot or self-host without R2)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    for attempt in range(1, max(1, args.retries) + 1):
        checks = run_checks(args.gateway, args.site, slow_ms=args.slow_ms,
                            require_backup=not args.allow_backup_pending)
        if all(c.ok for c in checks) or attempt >= args.retries:
            break
        time.sleep(args.delay)

    failed = [c for c in checks if not c.ok]
    if args.json:
        print(json.dumps({"ok": not failed, "checks": [asdict(c) for c in checks]}, indent=2))
    else:
        for c in checks:
            print(f"{'PASS' if c.ok else 'FAIL'}  {c.name:<16} {c.ms:>5} ms  {c.detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
