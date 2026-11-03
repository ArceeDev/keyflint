"""v1.2: clock-rollback guard and stable machine ids."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keyflint_verify import ClockGuard, verify_license
from keyflint_verify.fingerprint import compute_machine_id
from keyflint_verify.mcp import LICENSE_INVALID, KeyFlint, LicenseError

DATA = json.loads((Path(__file__).resolve().parents[2] / "vectors" / "vectors.json").read_text(encoding="utf-8"))
V = {v["name"]: v for v in DATA["vectors"]}
PK = DATA["keys"]["k1"]


class TestClockGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "clock_state"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_monotonic_and_persisted(self) -> None:
        g = ClockGuard(self.path)
        self.assertIsNone(g.last_seen())
        g.record(2000)
        g.record(1000)  # never goes backwards
        self.assertEqual(g.last_seen(), 2000)
        self.assertEqual(ClockGuard(self.path).last_seen(), 2000)  # survives restarts

    def test_read_only_falls_back_to_memory(self) -> None:
        with mock.patch("tempfile.mkstemp", side_effect=OSError("read-only")):
            g = ClockGuard(self.path)
            g.record(1234)
            self.assertEqual(g.last_seen(), 1234)

    def test_corrupt_file_is_ignored_and_env_off(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not json")
        self.assertIsNone(ClockGuard(self.path).last_seen())
        with mock.patch.dict(os.environ, {"KEYFLINT_CLOCK_STATE": "off"}):
            self.assertIsNone(ClockGuard().path)

    def test_verify_with_last_seen(self) -> None:
        v = V["clock_rollback_detected"]
        r = verify_license(v["token"], PK, now=v["now"], last_seen=v["last_seen"])
        self.assertEqual(r.error, "ERR_CLOCK_ROLLBACK_DETECTED")
        self.assertTrue(verify_license(v["token"], PK, now=v["now"]).valid)  # no state = no check

    def test_mcp_rejects_rolled_back_clock(self) -> None:
        g = ClockGuard(self.path)
        token = V["valid_basic"]["token"]  # expires at 1_800_003_600
        exp = 1_800_003_600
        with mock.patch("time.time", return_value=exp - 100):
            kf = KeyFlint(license_key=token, public_keys=PK, clock_guard=g)
            kf.check()
        self.assertEqual(g.last_seen(), exp - 100)
        with mock.patch("time.time", return_value=exp - 10_000):
            kf = KeyFlint(license_key=token, public_keys=PK, clock_guard=g)
            with self.assertRaises(LicenseError) as ctx:
                kf.check()
        self.assertEqual((ctx.exception.code, ctx.exception.reason), (LICENSE_INVALID, "ERR_CLOCK_ROLLBACK_DETECTED"))

    def test_perpetual_license_never_touches_state(self) -> None:
        g = ClockGuard(self.path)
        KeyFlint(license_key=V["valid_perpetual"]["token"], public_keys=PK, clock_guard=g).check()
        self.assertFalse(self.path.exists())


class TestStableMachineId(unittest.TestCase):
    def test_env_host_id_is_stable_across_hostnames(self) -> None:
        with mock.patch.dict(os.environ, {"KEYFLINT_HOST_ID": "host-123"}):
            with mock.patch("socket.gethostname", return_value="container-a"):
                a = compute_machine_id(strategy="stable")
            with mock.patch("socket.gethostname", return_value="container-b"):
                b = compute_machine_id(strategy="stable")
                legacy = compute_machine_id()
        self.assertEqual(a, b)
        self.assertNotEqual(a, legacy)

    def test_falls_back_to_legacy_without_host_id(self) -> None:
        with mock.patch("keyflint_verify.fingerprint._host_id", return_value=None):
            self.assertEqual(compute_machine_id(strategy="stable"), compute_machine_id())


if __name__ == "__main__":
    unittest.main()
