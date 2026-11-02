#!/usr/bin/env python3
"""End-to-end check of continuous backup + disaster recovery (Litestream) in the Docker image.

  1. Instance A (fixed secrets, as Managed provisioning sets them) issues L1 and L2, revokes L2.
  2. A is stopped and its volume DELETED (simulated host loss).
  3. Instance B boots on an EMPTY volume with the same backup config: it must restore the
     database, so L1 verifies valid and L2 is still revoked (only the DB knows that).
  4. Fail-closed: with an unreachable replica and no local DB, the container must refuse to start.

Replica: a local directory by default (no deps). Pass --s3-endpoint/--bucket to test an
S3-compatible store (R2, MinIO, moto) with LITESTREAM_ACCESS_KEY_ID/SECRET in your env.

Usage: python scripts/e2e_backup.py [--image keyflint:e2e] [--s3-endpoint URL --bucket NAME]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ADMIN = "kf_admin_e2e_backup_0123456789abcdef"
SECRETS = {
    "SECRET_KEY": "e2e" + "b" * 61,
    "ED25519_PRIVATE_KEY_HEX": "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
    "ADMIN_API_KEY": ADMIN,
    "STRIPE_WEBHOOK_SECRET": "whsec_e2e_backup_stripe",
    "LEMONSQUEEZY_WEBHOOK_SECRET": "whsec_e2e_backup_lemon",
}


def sh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    res = subprocess.run(args, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(args)}\n{res.stdout}\n{res.stderr}")
    return res


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method: str, url: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method=method,
                                 headers={"Content-Type": "application/json", "X-Admin-Key": ADMIN})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


class Runner:
    def __init__(self, image: str, backup_env: dict[str, str], mounts: list[str]) -> None:
        self.image, self.backup_env, self.mounts = image, backup_env, mounts

    def start(self, name: str, data_dir: Path, port: int, extra: dict[str, str] | None = None) -> None:
        sh("docker", "rm", "-f", name, check=False)
        env = {"ENVIRONMENT": "production", "PORT": str(port),
               "DATABASE_URL": "sqlite:////app/data/keyforge.db", **SECRETS, **self.backup_env, **(extra or {})}
        cmd = ["docker", "run", "-d", "--name", name, "--network", "host", "-v", f"{data_dir}:/app/data"]
        for m in self.mounts:
            cmd += ["-v", m]
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
        sh(*cmd, self.image)

    @staticmethod
    def wait_ready(name: str, port: int, timeout: float = 60) -> str:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if http("GET", f"{base}/readyz").get("ready"):
                    return base
            except Exception:
                time.sleep(0.5)
        logs = sh("docker", "logs", name, check=False)
        raise SystemExit(f"FAILED: {name} never became ready\n{logs.stdout}{logs.stderr}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="keyflint:e2e")
    ap.add_argument("--s3-endpoint")
    ap.add_argument("--bucket")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="kf-backup-"))
    backup_dir = tmp / "replica"
    backup_dir.mkdir(mode=0o777)
    os.chmod(backup_dir, 0o777)  # container user (uid 999) writes here in file mode
    if args.s3_endpoint:
        backup_env = {"LITESTREAM_BUCKET": args.bucket or "keyflint-e2e",
                      "LITESTREAM_ENDPOINT": args.s3_endpoint,
                      "LITESTREAM_PATH": f"e2e-{int(time.time())}",
                      "LITESTREAM_REGION": os.environ.get("LITESTREAM_REGION", "us-east-1"),
                      "LITESTREAM_ACCESS_KEY_ID": os.environ.get("LITESTREAM_ACCESS_KEY_ID", "test"),
                      "LITESTREAM_SECRET_ACCESS_KEY": os.environ.get("LITESTREAM_SECRET_ACCESS_KEY", "test")}
        mounts: list[str] = []
        mode = f"S3 {args.s3_endpoint}"
    else:
        backup_env = {"LITESTREAM_FILE_PATH": "/replica"}
        mounts = [f"{backup_dir}:/replica"]
        mode = "local directory"
    print(f"Replica: {mode}")
    r = Runner(args.image, backup_env, mounts)
    names = ["kf-backup-a", "kf-backup-b", "kf-backup-c"]
    try:
        data_a = tmp / "data-a"; data_a.mkdir()
        port = free_port()
        r.start(names[0], data_a, port)
        base = r.wait_ready(names[0], port)
        if "Continuous backup enabled" not in sh("docker", "logs", names[0]).stderr:
            raise SystemExit("FAILED: litestream did not start on instance A")
        l1 = http("POST", f"{base}/api/v1/licenses/issue", {"customer_email": "keep@example.com"})["data"]["license_key"]
        l2 = http("POST", f"{base}/api/v1/licenses/issue", {"customer_email": "gone@example.com"})["data"]["license_key"]
        http("POST", f"{base}/api/v1/licenses/revoke", {"license_key": l2, "reason": "e2e"})
        ok("instance A: continuous backup on; issued L1, issued+revoked L2")

        time.sleep(3)  # > sync-interval (1s)
        sh("docker", "stop", "-t", "20", names[0])
        sh("docker", "rm", "-f", names[0])
        sh("docker", "run", "--rm", "-v", f"{data_a}:/d", "--entrypoint", "sh", args.image, "-c", "find /d -mindepth 1 -delete")
        if any(data_a.iterdir()):
            raise SystemExit("FAILED: could not wipe instance A volume")
        ok("instance A destroyed and its volume wiped")

        data_b = tmp / "data-b"; data_b.mkdir()
        port = free_port()
        r.start(names[1], data_b, port)
        base = r.wait_ready(names[1], port)
        logs = sh("docker", "logs", names[1]).stderr
        if "restoring from backup" not in logs:
            raise SystemExit(f"FAILED: instance B did not attempt a restore\n{logs}")
        v1 = http("POST", f"{base}/api/v1/licenses/verify", {"license_key": l1})["data"]
        v2 = http("POST", f"{base}/api/v1/licenses/verify", {"license_key": l2})["data"]
        if not v1.get("valid"):
            raise SystemExit(f"FAILED: L1 not valid after restore: {v1}")
        if v2.get("valid") or v2.get("status") != "revoked":
            raise SystemExit(f"FAILED: L2 revocation lost in restore: {v2}")
        ok("instance B on an empty volume restored the DB: L1 valid, L2 still revoked")
        sh("docker", "rm", "-f", names[1])

        data_c = tmp / "data-c"; data_c.mkdir()
        port = free_port()
        broken = ({"LITESTREAM_ENDPOINT": "http://127.0.0.1:9"} if args.s3_endpoint
                  else {"LITESTREAM_BUCKET": "unreachable", "LITESTREAM_ENDPOINT": "http://127.0.0.1:9",
                        "LITESTREAM_ACCESS_KEY_ID": "x", "LITESTREAM_SECRET_ACCESS_KEY": "x"})
        r.start(names[2], data_c, port, broken)
        deadline = time.time() + 90
        state = ""
        while time.time() < deadline:
            state = sh("docker", "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", names[2]).stdout.strip()
            if state.startswith("exited"):
                break
            time.sleep(1)
        if not state.startswith("exited") or state.endswith(" 0"):
            raise SystemExit(f"FAILED: started despite an unreachable replica (state: {state})")
        if "refusing to start" not in sh("docker", "logs", names[2]).stderr:
            raise SystemExit("FAILED: missing fail-closed message")
        ok(f"unreachable replica + empty volume: refuses to start ({state})")

        print("\n[SUCCESS] Backup E2E: continuous replication and disaster recovery verified.")
    finally:
        for n in names:
            sh("docker", "rm", "-f", n, check=False)
        sh("docker", "run", "--rm", "-v", f"{tmp}:/d", "--entrypoint", "sh", args.image,
           "-c", "find /d -mindepth 1 -delete", check=False)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
