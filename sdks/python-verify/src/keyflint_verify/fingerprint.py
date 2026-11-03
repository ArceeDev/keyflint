"""Hardware Machine ID Fingerprinting for Node-Locked Licenses.

Zero external dependencies. Operates deterministically across Windows, Linux, and macOS.
"""

from __future__ import annotations

import hashlib
import os
import platform
import socket
import subprocess
import uuid
from pathlib import Path
from typing import Optional


def _host_id() -> Optional[str]:
    """OS-level id that survives reboots and container/devcontainer rebuilds when exposed."""
    explicit = os.environ.get("KEYFLINT_HOST_ID", "").strip()
    if explicit:
        return "env:" + explicit
    system = platform.system().lower()
    if system == "windows":
        try:
            import winreg  # type: ignore[import-not-found]

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                return "win:" + str(winreg.QueryValueEx(k, "MachineGuid")[0]).strip().lower()
        except Exception:
            return None
    if system == "darwin":
        try:
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True,
                                 text=True, timeout=3).stdout
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return "mac:" + line.split("=")[-1].strip().strip('"').lower()
        except Exception:
            return None
        return None
    # Linux / WSL2: systemd machine-id (mount it read-only into containers: -v /etc/machine-id:/etc/machine-id:ro)
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(path).read_text(encoding="ascii").strip().lower()
        except OSError:
            continue
        if value and set(value) != {"0"}:
            return "linux:" + value
    codespace = os.environ.get("CODESPACE_NAME", "").strip()  # survives Codespaces rebuilds
    if codespace:
        return "codespace:" + codespace.lower()
    return None


def compute_machine_id(strategy: str = "legacy") -> str:
    """Computes a deterministic, cross-platform hardware fingerprint for node locking.

    Formula: sha256(hostname:cpu_info:mac_address)

    ``strategy="stable"`` (v1.2) uses a host-level id instead (Windows MachineGuid, macOS
    IOPlatformUUID, Linux/WSL ``/etc/machine-id``, ``CODESPACE_NAME`` or ``KEYFLINT_HOST_ID``),
    so rebuilding a container does not consume a new seat. It falls back to the legacy formula
    when no host id is visible. The default stays "legacy" because existing node-locked
    licenses embed legacy ids.
    """
    if strategy == "stable":
        host = _host_id()
        if host:
            return hashlib.sha256(f"keyflint-stable:{host}".encode("utf-8")).hexdigest()
    # 1. Hostname normalization
    hostname = socket.gethostname().strip().lower()

    # 2. Resilient CPU identification
    proc = platform.processor().strip().lower()
    mach = platform.machine().strip().lower()
    sys_name = platform.system().strip().lower()
    cpu_info = f"{proc}|{mach}|{sys_name}" if proc else f"{mach}|{sys_name}"

    # 3. MAC Address extraction
    mac_node = uuid.getnode()
    mac_address = f"{mac_node:012x}".lower()

    # 4. Canonical combination and SHA-256 digest
    raw_identifier = f"{hostname}:{cpu_info}:{mac_address}"
    return hashlib.sha256(raw_identifier.encode("utf-8")).hexdigest()
