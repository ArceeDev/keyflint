"""v1.2: @metered(offline_grace_calls=N) — bounded unpaid calls while the gateway is down."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("KEYFLINT_CLOCK_STATE", "off")

from keyflint_verify.mcp import GATEWAY_ERROR, MAX_OFFLINE_GRACE_CALLS, KeyFlint, LicenseError  # noqa: E402
from test_mcp import PK, TOKEN, FakeGateway  # noqa: E402


class TestOfflineGrace(unittest.TestCase):
    def setUp(self) -> None:
        self.gw = FakeGateway(balance=100)
        self.kf = KeyFlint(license_key=TOKEN, public_keys=PK, gateway_url="http://127.0.0.1:9", timeout=0.3)

    def tearDown(self) -> None:
        self.gw.close()

    def test_default_is_fail_closed(self) -> None:
        @self.kf.metered(credits=2)
        def tool() -> str:
            return "ran"

        with self.assertRaises(LicenseError) as cm:
            tool()
        self.assertEqual((cm.exception.code, cm.exception.reason), (GATEWAY_ERROR, "GATEWAY_UNREACHABLE"))

    def test_grace_runs_n_calls_then_replays_debits_without_refunds(self) -> None:
        calls = []

        @self.kf.metered(credits=2, offline_grace_calls=3, timeout_ms=300)
        def tool() -> dict:
            calls.append(1)
            return {"isError": True}  # a failing tool on grace must not trigger a refund

        for _ in range(3):
            tool()
        self.assertEqual(self.kf.pending_debits, 3)
        with self.assertRaises(LicenseError):
            tool()  # 4th call: grace exhausted, fail closed
        self.assertEqual(len(calls), 3)

        self.kf.gateway_url = self.gw.url  # gateway is back
        tool()
        self.assertEqual(self.kf.pending_debits, 0)
        keys = [k for _, k in self.gw.requests]
        self.assertEqual(len(keys), 4)            # 3 replayed + the live call
        self.assertEqual(len(set(keys)), 4)
        self.assertEqual(self.gw.balance, 100 - 6)  # 3 grace debits kept, the live one refunded
        self.assertEqual(len(self.gw.refunds), 1)  # only the live call is refunded
        self.assertEqual(self.gw.refunds[0]["idempotency_key"], keys[-1])

    def test_refused_queued_debit_is_dropped(self) -> None:
        @self.kf.metered(credits=60, offline_grace_calls=2, refund_on_error=False)
        def tool() -> str:
            return "ok"

        tool()
        tool()
        self.kf.gateway_url = self.gw.url
        self.assertEqual(self.kf.flush_pending(), 2)  # second one gets 402 and is dropped
        self.assertEqual(self.kf.pending_debits, 0)
        self.assertEqual(self.gw.balance, 40)

    def test_cap(self) -> None:
        with self.assertRaises(ValueError):
            self.kf.metered(offline_grace_calls=MAX_OFFLINE_GRACE_CALLS + 1)


if __name__ == "__main__":
    unittest.main()
