"""Container entrypoint: first-boot secret provisioning + privilege drop + exec of the CLI.

Run as ``python -m app.bootstrap [cli args...]``. With no args it starts the gateway on
``$PORT`` (default 8000), which is what Render, Railway and Fly expect.

1. If started as root, the data directory is created/chowned to the ``keyforge`` user and
   privileges are dropped (platform volumes are usually mounted root-owned).
2. Secrets missing from the environment are loaded from ``<data_dir>/secrets.env`` or, on
   first boot, generated there (mode 0600). Values set in the environment always win.
   Set ``KEYFORGE_AUTO_SECRETS=0`` to disable this step.
3. If ``LITESTREAM_BUCKET`` (S3/R2) or ``LITESTREAM_FILE_PATH`` is set and the command is
   ``serve``: restore the database from the replica when it is missing (fails closed if the
   restore fails), then run the gateway under ``litestream replicate -exec`` for continuous
   backup. Credentials come from ``LITESTREAM_ACCESS_KEY_ID`` / ``LITESTREAM_SECRET_ACCESS_KEY``.
4. ``exec python -m app.cli <args>`` (or litestream wrapping it).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Mapping, MutableMapping, Optional

SECRETS_FILENAME = "secrets.env"
DEFAULT_DATA_DIR = "/app/data"
RUNTIME_USER = "keyforge"

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _gen_ed25519() -> str:
    from app.infrastructure.security.ed25519_signer import Ed25519Signer
    return Ed25519Signer.generate_keypair()[0]


# Order matters only for the file layout. Webhook placeholders pass the production check but
# match no real provider signature, so every webhook is rejected until the real whsec is set.
GENERATORS: dict[str, Callable[[], str]] = {
    "SECRET_KEY": lambda: secrets.token_hex(32),
    "ED25519_PRIVATE_KEY_HEX": _gen_ed25519,
    "ADMIN_API_KEY": lambda: "kf_admin_" + secrets.token_hex(24),
    "STRIPE_WEBHOOK_SECRET": lambda: "whsec_unconfigured_" + secrets.token_hex(16),
    "LEMONSQUEEZY_WEBHOOK_SECRET": lambda: "whsec_unconfigured_" + secrets.token_hex(16),
}


def resolve_data_dir(env: Mapping[str, str]) -> Path:
    explicit = (env.get("KEYFORGE_DATA_DIR") or "").strip()
    if explicit:
        return Path(explicit)
    url = (env.get("DATABASE_URL") or "").strip()
    if url and ":memory:" not in url:
        raw = url.split("sqlite:///", 1)[-1] if url.startswith("sqlite:///") else url.split("sqlite://", 1)[-1]
        return Path(raw).parent if raw else Path(DEFAULT_DATA_DIR)
    return Path(DEFAULT_DATA_DIR)


def read_secrets_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in GENERATORS and _VALUE_RE.match(value):
            out[key] = value
    return out


def write_secrets_file(path: Path, values: Mapping[str, str]) -> None:
    lines = [
        "# KeyForge secrets generated on first boot. Keep this volume persistent and backed up:",
        "# losing ED25519_PRIVATE_KEY_HEX invalidates every license already issued.",
    ]
    for key in GENERATORS:
        if key in values:
            if not _KEY_RE.match(key) or not _VALUE_RE.match(values[key]):
                raise ValueError(f"refusing to write unsafe value for {key}")
            lines.append(f"{key}={values[key]}")
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def provision_secrets(env: MutableMapping[str, str], data_dir: Path, log: Callable[[str], None]) -> list[str]:
    """Fills missing secrets into ``env``. Returns the names generated in this call."""
    path = data_dir / SECRETS_FILENAME
    stored = read_secrets_file(path)
    generated: list[str] = []

    for key, gen in GENERATORS.items():
        if (env.get(key) or "").strip():
            continue  # operator-provided value wins
        if key == "ED25519_PRIVATE_KEY_HEX" and (env.get("ED25519_PUBLIC_KEY_HEX") or "").strip():
            log("[keyforge] ED25519_PUBLIC_KEY_HEX is set without its private key: not generating one.")
            continue
        if key not in stored:
            stored[key] = gen()
            generated.append(key)
        env[key] = stored[key]

    if generated:
        data_dir.mkdir(parents=True, exist_ok=True)
        write_secrets_file(path, stored)
        _announce(env, generated, path, log)
    return generated


def _announce(env: Mapping[str, str], generated: list[str], path: Path, log: Callable[[str], None]) -> None:
    log(f"[keyforge] First boot: generated {', '.join(generated)} in {path}")
    if "ED25519_PRIVATE_KEY_HEX" in generated:
        from app.infrastructure.security.ed25519_signer import Ed25519Signer
        pub = Ed25519Signer(private_key_hex=env["ED25519_PRIVATE_KEY_HEX"]).get_public_key_hex()
        log(f"[keyforge] Ed25519 public key (embed in your app / SDK): {pub}")
        log("[keyforge] WARNING: this key lives on the data volume. If the volume is not persistent,")
        log("[keyforge]          a redeploy creates a new key and every issued license stops verifying.")
    if "ADMIN_API_KEY" in generated:
        log(f"[keyforge] Admin API key (shown once, also in {path}): {env['ADMIN_API_KEY']}")
    if any(k.endswith("WEBHOOK_SECRET") for k in generated):
        log("[keyforge] Webhook secrets are placeholders: set STRIPE_WEBHOOK_SECRET / "
            "LEMONSQUEEZY_WEBHOOK_SECRET to your provider's whsec before taking payments.")


def drop_privileges(data_dir: Path, user: str = RUNTIME_USER) -> None:
    """When running as root: own the data dir by ``user`` and switch to it. No-op otherwise."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    import pwd
    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        return  # no runtime user in this image: keep running as is
    data_dir.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(data_dir):
        for name in [root, *(os.path.join(root, d) for d in dirs), *(os.path.join(root, f) for f in files)]:
            os.lchown(name, pw.pw_uid, pw.pw_gid)
    os.setgroups([])
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
    os.environ["HOME"] = pw.pw_dir
    os.environ["USER"] = user


LITESTREAM_CONFIG = str(Path(tempfile.gettempdir()) / "litestream.yml")


def resolve_db_path(env: Mapping[str, str]) -> Optional[Path]:
    url = (env.get("DATABASE_URL") or "sqlite:///data/keyforge.db").strip()
    if ":memory:" in url:
        return None
    raw = url.split("sqlite:///", 1)[-1] if url.startswith("sqlite:///") else url.split("sqlite://", 1)[-1]
    return Path(raw).resolve()


def _yaml_str(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid YAML scalar, safely quoted


def litestream_config(env: Mapping[str, str], db_path: Path) -> Optional[str]:
    """Builds a litestream.yml (no credentials inside), or None when backups are not configured."""
    bucket = (env.get("LITESTREAM_BUCKET") or "").strip()
    file_path = (env.get("LITESTREAM_FILE_PATH") or "").strip()
    if not bucket and not file_path:
        return None
    retention = (env.get("LITESTREAM_RETENTION") or "720h").strip()
    lines = ["dbs:", f"  - path: {_yaml_str(str(db_path))}", "    replicas:"]
    if bucket:
        lines += [
            "      - type: s3",
            f"        bucket: {_yaml_str(bucket)}",
            f"        path: {_yaml_str((env.get('LITESTREAM_PATH') or 'keyforge').strip())}",
            f"        region: {_yaml_str((env.get('LITESTREAM_REGION') or 'auto').strip())}",
        ]
        endpoint = (env.get("LITESTREAM_ENDPOINT") or "").strip()
        if endpoint:  # R2 / MinIO / other S3-compatible stores
            lines += [f"        endpoint: {_yaml_str(endpoint)}", "        force-path-style: true"]
    else:
        lines += ["      - type: file", f"        path: {_yaml_str(file_path)}"]
    lines += [
        f"        retention: {_yaml_str(retention)}",
        "        snapshot-interval: \"24h\"",
        "        sync-interval: \"1s\"",
    ]
    return "\n".join(lines) + "\n"


def litestream_wrap(env: Mapping[str, str], args: list[str], log: Callable[[str], None],
                    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run) -> list[str]:
    """Returns the argv to exec: the CLI itself, or litestream replicating around ``serve``."""
    cli = [sys.executable, "-m", "app.cli", *args]
    if not args or args[0] != "serve":
        return cli
    db_path = resolve_db_path(env)
    config = litestream_config(env, db_path) if db_path else None
    if config is None:
        return cli
    binary = shutil.which("litestream")
    if not binary:
        raise SystemExit("[keyforge] LITESTREAM_* is set but the litestream binary is not installed.")
    Path(LITESTREAM_CONFIG).write_text(config, encoding="utf-8")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        log(f"[keyforge] No database at {db_path}: restoring from backup replica if one exists...")
        res = run([binary, "restore", "-config", LITESTREAM_CONFIG, "-if-db-not-exists",
                   "-if-replica-exists", str(db_path)])
        if res.returncode != 0:
            # Fail closed: starting empty would issue licenses against a blank database.
            raise SystemExit(f"[keyforge] Backup restore failed (exit {res.returncode}); refusing to start.")
        log("[keyforge] Restore step done." if db_path.exists() else "[keyforge] No replica yet: starting fresh.")
    log("[keyforge] Continuous backup enabled (litestream).")
    return [binary, "replicate", "-config", LITESTREAM_CONFIG, "-exec", shlex.join(cli)]


def default_args(env: Mapping[str, str]) -> list[str]:
    port = (env.get("PORT") or "8000").strip() or "8000"
    return ["serve", "--host", "0.0.0.0", "--port", port]


def main(argv: Optional[list[str]] = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv) or default_args(os.environ)
    data_dir = resolve_data_dir(os.environ)
    drop_privileges(data_dir)
    if (os.environ.get("KEYFORGE_AUTO_SECRETS") or "1").strip() != "0":
        provision_secrets(os.environ, data_dir, lambda m: print(m, file=sys.stderr, flush=True))
    argv_exec = litestream_wrap(os.environ, args, lambda m: print(m, file=sys.stderr, flush=True))
    os.execvp(argv_exec[0], argv_exec)


if __name__ == "__main__":
    main()
