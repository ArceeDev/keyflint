#!/usr/bin/env python3
"""KeyForge Managed: one isolated Fly.io instance per customer.

  python scripts/managed/kf_managed.py create  acme --region mad [--domain lic.acme.com] [--dry-run]
  python scripts/managed/kf_managed.py upgrade acme --image ghcr.io/arceedev/keyforge:1.2.0
  python scripts/managed/kf_managed.py upgrade --all --image ghcr.io/arceedev/keyforge:1.2.0
  python scripts/managed/kf_managed.py status  acme
  python scripts/managed/kf_managed.py list
  python scripts/managed/kf_managed.py destroy acme --confirm acme

`create` generates the customer's Ed25519 key, SECRET_KEY and admin key LOCALLY, keeps the master
copy in the vault (~/.keyforge-managed or $KF_VAULT_DIR, files 0600) and sets them as Fly secrets
via stdin (never on the command line). Secrets live outside the volume, so a lost volume is
recovered from the Litestream backup with the same signing key.

Backups (recommended): export before `create`
  KF_BACKUP_BUCKET, KF_BACKUP_ENDPOINT (R2: https://<account>.r2.cloudflarestorage.com),
  LITESTREAM_ACCESS_KEY_ID, LITESTREAM_SECRET_ACCESS_KEY
Each customer replicates to <bucket>/<slug>. Requires `fly` (flyctl) logged in.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DEFAULT_IMAGE = "ghcr.io/arceedev/keyforge:latest"
FLY_CONFIG = ROOT / "fly.toml"
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")
SECRET_NAMES = ("SECRET_KEY", "ED25519_PRIVATE_KEY_HEX", "ADMIN_API_KEY",
                "STRIPE_WEBHOOK_SECRET", "LEMONSQUEEZY_WEBHOOK_SECRET",
                "LITESTREAM_ACCESS_KEY_ID", "LITESTREAM_SECRET_ACCESS_KEY")

Runner = Callable[..., subprocess.CompletedProcess]


class Fly:
    """Thin flyctl wrapper. dry_run prints commands (stdin redacted) instead of running them."""

    def __init__(self, dry_run: bool = False, runner: Optional[Runner] = None, out=print) -> None:
        self.dry_run, self.out = dry_run, out
        self.runner = runner or subprocess.run
        self.log: list[list[str]] = []

    def __call__(self, *args: str, stdin: Optional[str] = None, check: bool = True,
                 capture: bool = False) -> subprocess.CompletedProcess:
        cmd = ["fly", *args]
        self.log.append(cmd)
        if self.dry_run:
            self.out("$ " + " ".join(cmd) + ("  <<< [secrets via stdin, redacted]" if stdin else ""))
            return subprocess.CompletedProcess(cmd, 0, "[]" if capture else "", "")
        res = self.runner(cmd, input=stdin, text=True, capture_output=capture)
        if check and res.returncode != 0:
            raise SystemExit(f"flyctl failed ({res.returncode}): {' '.join(cmd)}\n{getattr(res, 'stderr', '') or ''}")
        return res


def vault_dir() -> Path:
    d = Path(os.environ.get("KF_VAULT_DIR") or Path.home() / ".keyforge-managed")
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def app_name(slug: str) -> str:
    return f"kf-{slug}"


def validate_slug(slug: str) -> str:
    if not SLUG_RE.match(slug or ""):
        raise SystemExit("slug must be 3-40 chars: lowercase letters, digits and '-' (no leading/trailing '-')")
    return slug


def generate_secrets() -> dict[str, str]:
    from app.infrastructure.security.ed25519_signer import Ed25519Signer
    priv, _ = Ed25519Signer.generate_keypair()
    return {
        "SECRET_KEY": secrets.token_hex(32),
        "ED25519_PRIVATE_KEY_HEX": priv,
        "ADMIN_API_KEY": "kf_admin_" + secrets.token_hex(24),
        # Placeholders reject every webhook until the customer's real whsec is set.
        "STRIPE_WEBHOOK_SECRET": "whsec_unconfigured_" + secrets.token_hex(16),
        "LEMONSQUEEZY_WEBHOOK_SECRET": "whsec_unconfigured_" + secrets.token_hex(16),
    }


def backup_settings(slug: str, env: dict[str, str]) -> dict[str, str]:
    bucket = (env.get("KF_BACKUP_BUCKET") or "").strip()
    if not bucket:
        return {}
    missing = [k for k in ("LITESTREAM_ACCESS_KEY_ID", "LITESTREAM_SECRET_ACCESS_KEY") if not env.get(k)]
    if missing:
        raise SystemExit(f"KF_BACKUP_BUCKET is set but {', '.join(missing)} is missing")
    out = {"LITESTREAM_BUCKET": bucket, "LITESTREAM_PATH": slug,
           "LITESTREAM_ACCESS_KEY_ID": env["LITESTREAM_ACCESS_KEY_ID"],
           "LITESTREAM_SECRET_ACCESS_KEY": env["LITESTREAM_SECRET_ACCESS_KEY"]}
    if env.get("KF_BACKUP_ENDPOINT"):
        out["LITESTREAM_ENDPOINT"] = env["KF_BACKUP_ENDPOINT"]
    if env.get("KF_BACKUP_REGION"):
        out["LITESTREAM_REGION"] = env["KF_BACKUP_REGION"]
    return out


def cmd_create(fly: Fly, slug: str, region: str, image: str, domain: Optional[str],
               org: Optional[str], env: dict[str, str], require_backup: bool = True) -> dict:
    slug = validate_slug(slug)
    app = app_name(slug)
    vdir = vault_dir()
    env_file, meta_file = vdir / f"{slug}.env", vdir / f"{slug}.json"
    if env_file.exists() and not fly.dry_run:
        raise SystemExit(f"{env_file} already exists: customer '{slug}' was provisioned before")

    backup = backup_settings(slug, env)
    if not backup and require_backup:
        raise SystemExit("No backups configured (KF_BACKUP_BUCKET...). Pass --no-backup to accept the risk.")

    sec = generate_secrets()
    from app.infrastructure.security.ed25519_signer import Ed25519Signer
    pub = Ed25519Signer(private_key_hex=sec["ED25519_PRIVATE_KEY_HEX"]).get_public_key_hex()
    all_secrets = {**sec, **backup}
    url = f"https://{domain}" if domain else f"https://{app}.fly.dev"
    meta = {"slug": slug, "app": app, "region": region, "image": image, "url": url,
            "public_key_hex": pub, "backup": bool(backup), "created_at": int(time.time())}

    if not fly.dry_run:  # vault first: if anything below fails, the key is not lost
        _write_private(env_file, "".join(f"{k}={v}\n" for k, v in all_secrets.items()))
        _write_private(meta_file, json.dumps(meta, indent=2) + "\n")

    fly("apps", "create", app, *(["--org", org] if org else []))
    fly("volumes", "create", "keyforge_data", "--size", "1", "--region", region, "--app", app, "--yes")
    fly("secrets", "import", "--stage", "--app", app,
        stdin="".join(f"{k}={v}\n" for k, v in all_secrets.items()))
    fly("deploy", "--app", app, "--config", str(FLY_CONFIG), "--image", image,
        "--primary-region", region, "--ha=false")
    if domain:
        fly("certs", "add", domain, "--app", app)
    fly.out(f"\nCustomer '{slug}' ready at {url}")
    fly.out(f"  Public key (customer embeds it in their app): {pub}")
    fly.out(f"  Admin key: in {env_file} (send it to the customer over a secure channel)")
    if domain:
        fly.out(f"  DNS: CNAME {domain} -> {app}.fly.dev (see `fly certs show {domain} --app {app}`)")
    if not backup:
        fly.out("  WARNING: no backups configured for this instance.")
    return meta


def cmd_upgrade(fly: Fly, slugs: list[str], image: str) -> None:
    for slug in slugs:
        meta_file = vault_dir() / f"{slug}.json"
        region = json.loads(meta_file.read_text())["region"] if meta_file.exists() else None
        fly("deploy", "--app", app_name(validate_slug(slug)), "--config", str(FLY_CONFIG), "--image", image,
            "--ha=false", *(["--primary-region", region] if region else []))
        if meta_file.exists() and not fly.dry_run:
            meta = json.loads(meta_file.read_text())
            meta["image"] = image
            meta_file.write_text(json.dumps(meta, indent=2) + "\n")


def managed_slugs(fly: Fly) -> list[str]:
    res = fly("apps", "list", "--json", capture=True)
    apps = json.loads(res.stdout or "[]")
    names = [a.get("Name") or a.get("name") or "" for a in apps]
    return sorted(n[3:] for n in names if n.startswith("kf-"))


def cmd_destroy(fly: Fly, slug: str, confirm: Optional[str]) -> None:
    slug = validate_slug(slug)
    if confirm != slug:
        raise SystemExit(f"Refusing: pass --confirm {slug} to destroy {app_name(slug)} and its volume")
    fly("apps", "destroy", app_name(slug), "--yes")
    vdir = vault_dir()
    for f in (vdir / f"{slug}.env", vdir / f"{slug}.json"):
        if f.exists() and not fly.dry_run:
            f.rename(f.with_name(f.name + f".destroyed-{int(time.time())}"))
    fly.out(f"Destroyed {app_name(slug)}. Vault files kept as *.destroyed-* ; backups remain in "
            f"<bucket>/{slug} until retention expires (delete that prefix for a GDPR erasure).")


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print flyctl commands without running them")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("slug"); c.add_argument("--region", default="mad")
    c.add_argument("--image", default=DEFAULT_IMAGE); c.add_argument("--domain"); c.add_argument("--org")
    c.add_argument("--no-backup", action="store_true")
    u = sub.add_parser("upgrade"); u.add_argument("slug", nargs="?"); u.add_argument("--all", action="store_true")
    u.add_argument("--image", required=True)
    s = sub.add_parser("status"); s.add_argument("slug")
    sub.add_parser("list")
    d = sub.add_parser("destroy"); d.add_argument("slug"); d.add_argument("--confirm")
    a = ap.parse_args(argv)

    fly = Fly(dry_run=a.dry_run)
    if a.cmd == "create":
        cmd_create(fly, a.slug, a.region, a.image, a.domain, a.org, dict(os.environ), not a.no_backup)
    elif a.cmd == "upgrade":
        if bool(a.all) == bool(a.slug):
            raise SystemExit("pass either a slug or --all")
        cmd_upgrade(fly, managed_slugs(fly) if a.all else [a.slug], a.image)
    elif a.cmd == "status":
        fly("status", "--app", app_name(validate_slug(a.slug)))
    elif a.cmd == "list":
        for slug in managed_slugs(fly):
            print(slug)
    elif a.cmd == "destroy":
        cmd_destroy(fly, a.slug, a.confirm)


if __name__ == "__main__":
    main()
