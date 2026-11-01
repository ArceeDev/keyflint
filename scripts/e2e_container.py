#!/usr/bin/env python3
"""End-to-end check of the Docker image as a one-click platform would run it.

Builds the image, then on a root-owned bind mount (how Render/Railway/Fly mount volumes):
  1. boots with ENVIRONMENT=production and NO secrets, on a platform-style $PORT;
  2. checks the process dropped root, secrets.env is 0600, /readyz answers;
  3. issues a license with the admin key from the first-boot log and verifies it offline
     against the public key from the log and from /public-key;
  4. recreates the container on the same volume: same key, old license still valid, no
     secrets reprinted;
  5. checks CLI passthrough (`docker run IMAGE --help`).

Usage: python scripts/e2e_container.py [--image keyforge:e2e] [--no-build]
Stdlib only; needs a working `docker`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.infrastructure.security.offline_validator import validate_offline  # noqa: E402

CONTAINER_PORT = 10000  # Render's default $PORT, to prove the image follows $PORT


def sh(*args: str, check: bool = True) -> str:
    res = subprocess.run(args, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(args)}\n{res.stdout}\n{res.stderr}")
    return res.stdout + res.stderr


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method: str, url: str, body: dict | None = None, headers: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def wait_ready(base: str, name: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if http("GET", f"{base}/readyz").get("ready"):
                return
        except Exception:
            time.sleep(0.5)
    raise SystemExit(f"FAILED: /readyz never became ready\n{sh('docker', 'logs', name, check=False)}")


def run(image: str, name: str, data_dir: Path, host_port: int) -> str:
    sh("docker", "rm", "-f", name, check=False)
    sh("docker", "run", "-d", "--name", name,
       "-p", f"127.0.0.1:{host_port}:{CONTAINER_PORT}",
       "-e", "ENVIRONMENT=production",
       "-e", f"PORT={CONTAINER_PORT}",
       "-e", "DATABASE_URL=sqlite:////app/data/keyforge.db",
       "-v", f"{data_dir}:/app/data",
       image)
    base = f"http://127.0.0.1:{host_port}"
    wait_ready(base, name)
    return base


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="keyforge:e2e")
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args()
    image, name = args.image, "keyforge-e2e"

    if not args.no_build:
        print("Building image...")
        sh("docker", "build", "-t", image, str(ROOT))

    tmp = Path(tempfile.mkdtemp(prefix="kf-e2e-"))
    data_dir = tmp / "data"
    data_dir.mkdir(mode=0o755)  # owned by the invoking user (root in CI), like a platform disk
    host_port = free_port()
    try:
        base = run(image, name, data_dir, host_port)
        logs = sh("docker", "logs", name)

        pub_m = re.search(r"Ed25519 public key \(embed in your app / SDK\): ([0-9a-f]{64})", logs)
        adm_m = re.search(r"Admin API key \(shown once.*?\): (kf_admin_[0-9a-f]+)", logs)
        if not pub_m or not adm_m:
            raise SystemExit(f"FAILED: first-boot log lacks public/admin key\n{logs}")
        pub, admin = pub_m.group(1), adm_m.group(1)
        ok("first boot generated secrets with no configuration (production mode)")

        status = sh("docker", "exec", name, "cat", "/proc/1/status")
        uid = re.search(r"^Uid:\s+(\d+)", status, re.M).group(1)
        if uid == "0":
            raise SystemExit("FAILED: gateway process still runs as root")
        ok(f"gateway runs unprivileged (uid {uid}) on a root-owned volume")

        mode = sh("docker", "exec", name, "stat", "-c", "%a", "/app/data/secrets.env").strip()
        if mode != "600":
            raise SystemExit(f"FAILED: secrets.env mode is {mode}, expected 600")
        ok("secrets.env persisted on the volume with mode 600")

        served = http("GET", f"{base}/api/v1/licenses/public-key")["data"]["public_key_hex"]
        if served != pub:
            raise SystemExit("FAILED: /public-key differs from the key printed at first boot")
        ok(f"follows $PORT={CONTAINER_PORT}; /public-key matches the logged key")

        try:
            http("POST", f"{base}/api/v1/licenses/issue", {"customer_email": "e2e@example.com"})
            raise SystemExit("FAILED: /issue accepted a request without X-Admin-Key")
        except urllib.error.HTTPError as exc:
            if exc.code not in (401, 403):
                raise
        ok("admin routes reject requests without X-Admin-Key")

        token = http("POST", f"{base}/api/v1/licenses/issue",
                     {"customer_email": "e2e@example.com", "tier": "pro"},
                     {"X-Admin-Key": admin})["data"]["license_key"]
        valid, _, err = validate_offline(token, pub)
        if not valid:
            raise SystemExit(f"FAILED: issued license does not verify offline: {err}")
        ok("license issued with the generated admin key verifies offline")

        base = run(image, name, data_dir, host_port)  # redeploy on the same volume
        logs2 = sh("docker", "logs", name)
        if "First boot" in logs2 or admin in logs2:
            raise SystemExit("FAILED: secrets regenerated or reprinted after redeploy")
        if http("GET", f"{base}/api/v1/licenses/public-key")["data"]["public_key_hex"] != pub:
            raise SystemExit("FAILED: public key changed after redeploy")
        if not validate_offline(token, pub)[0]:
            raise SystemExit("FAILED: old license invalid after redeploy")
        http("POST", f"{base}/api/v1/licenses/issue", {"customer_email": "e2e2@example.com"},
             {"X-Admin-Key": admin})
        ok("redeploy keeps key + admin key; old license still valid; nothing reprinted")

        help_out = sh("docker", "run", "--rm", image, "--help")
        if "serve" not in help_out:
            raise SystemExit(f"FAILED: CLI passthrough broken\n{help_out}")
        ok("CLI passthrough (`docker run IMAGE --help`) still works")

        print("\n[SUCCESS] Container E2E: one-click deploy path verified.")
    finally:
        sh("docker", "rm", "-f", name, check=False)
        sh("docker", "run", "--rm", "-v", f"{data_dir}:/d", "--entrypoint", "sh", image,
           "-c", "find /d -mindepth 1 -delete", check=False)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
