"""Clock-rollback guard for offline checks of expiring licenses (v1.2).

Offline verification trusts the local clock, so setting the clock back to a date between
``issued_at`` and ``expires_at`` would keep an expired license alive. ClockGuard remembers
the latest time this machine has seen in ``~/.keyflint/clock_state`` (or in memory when the
file system is read-only) and verification rejects a clock that is behind it by more than
300 s with ``ERR_CLOCK_ROLLBACK_DETECTED``.

Limits: this is a deterrent, not a guarantee. Whoever controls the machine can delete or
edit the state file, and a fresh container starts with no state. Only licenses with
``expires_at`` are affected; perpetual licenses never fail this check.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Union

ROLLBACK_LEEWAY_SECONDS = 300


def default_state_path() -> Optional[Path]:
    """``KEYFLINT_CLOCK_STATE`` overrides the path; ``off`` (or ``0``) disables persistence."""
    raw = os.environ.get("KEYFLINT_CLOCK_STATE")
    if raw is not None:
        return None if raw.strip().lower() in ("", "off", "0", "false") else Path(raw).expanduser()
    try:
        return Path.home() / ".keyflint" / "clock_state"
    except (RuntimeError, KeyError):  # no resolvable home directory
        return None


class ClockGuard:
    """Monotonic "latest time seen" store, persisted best-effort. Thread-safe."""

    def __init__(self, path: Union[str, Path, None, bool] = True) -> None:
        self.path: Optional[Path] = default_state_path() if path is True else (Path(path) if path else None)
        self._mem: Optional[int] = None
        self._lock = threading.Lock()

    def _read_file(self) -> Optional[int]:
        if self.path is None:
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")).get("last_seen")
        except (OSError, ValueError, AttributeError):
            return None
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def last_seen(self) -> Optional[int]:
        with self._lock:
            disk = self._read_file()
            values = [v for v in (self._mem, disk) if v is not None]
            return max(values) if values else None

    def record(self, now: Optional[int] = None) -> None:
        """Stores ``now`` if it is later than what is stored; never raises."""
        current = int(now if now is not None else time.time())
        with self._lock:
            if self._mem is not None and current <= self._mem:
                return
            disk = self._read_file()
            self._mem = max(current, disk or 0)
            if self.path is None or (disk is not None and disk >= current):
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".clock_state.")
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({"v": 1, "last_seen": current}, fh)
                os.replace(tmp, self.path)
            except OSError:
                pass  # read-only file system: keep the in-memory value
