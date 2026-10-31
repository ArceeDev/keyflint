"""Hardware Machine ID Fingerprinting for Node-Locked Licenses.

Zero external dependencies. Operates deterministically across Windows, Linux, and macOS.
"""

from __future__ import annotations

import hashlib
import platform
import socket
import uuid


def compute_machine_id() -> str:
    """Computes a deterministic, cross-platform hardware fingerprint for node locking.

    Formula: sha256(hostname:cpu_info:mac_address)
    """
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
