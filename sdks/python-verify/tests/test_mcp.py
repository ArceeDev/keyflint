"""Tests for keyflint_verify.mcp against a fake gateway and (if installed) the real mcp SDK."""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import os
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from keyflint_verify.mcp import (
    FEATURE_NOT_ENTITLED,
    GATEWAY_ERROR,
    LICENSE_INVALID,
    QUOTA_EXHAUSTED,
    KeyFlint,
    LicenseError,
    _parse_keys_env,
)

DATA = json.loads((Path(__file__).resolve().parents[1].parent / "vectors" / "vectors.json").read_text("utf-8"))
V = {v["name"]: v for v in DATA["vectors"]}
TOKEN = V["valid_perpetual"]["token"]  # never expires, so the tests do not age
os.environ.setdefault("KEYFLINT_CLOCK_STATE", "off")  # tests must not write to ~/.keyflint
PK = DATA["keys"]["k1"]


class FakeGateway:
    def __init__(self, balance: int) -> None:
        self.balance = balance
        self.requests: list[tuple[dict, str]] = []
        self.deducts: dict[str, int] = {}
        self.refunds: list[dict] = []
        gw = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path.endswith("/quota/refund"):
                    gw.refunds.append(body)
                    gw.balance += gw.deducts.pop(body["idempotency_key"], 0)
                    status, out = 200, {"success": True, "data": {"remaining_balance": gw.balance}}
                    raw = json.dumps(out).encode()
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                gw.requests.append((body, self.headers.get("Idempotency-Key", "")))
                if body["credits"] > gw.balance:
                    status, out = 402, {"success": False, "error": {"code": "QUOTA_EXHAUSTED", "message": "0 left",
                                                                   "status_code": 402, "details": {}}}
                else:
                    gw.balance -= body["credits"]
                    gw.deducts[body["idempotency_key"]] = body["credits"]
                    status, out = 200, {"success": True, "data": {"remaining_balance": gw.balance}}
                raw = json.dumps(out).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class TestDecorators(unittest.TestCase):
    def setUp(self) -> None:
        self.gw = FakeGateway(balance=10)
        self.kf = KeyFlint(license_key=TOKEN, public_keys=PK, gateway_url=self.gw.url,
                           checkout_url="https://shop.example/upgrade")

    def tearDown(self) -> None:
        self.gw.close()

    def test_require_license_sync_and_async_offline(self) -> None:
        @self.kf.require_license
        def a(x: int) -> int:
            return x + 1

        @self.kf.require_license(features=["core"])
        async def b(x: int) -> int:
            return x * 2

        self.assertEqual(a(1), 2)
        self.assertEqual(asyncio.run(b(3)), 6)
        self.assertEqual(self.gw.requests, [])  # offline only
        self.assertEqual(list(inspect.signature(a).parameters), ["x"])
        self.assertTrue(inspect.iscoroutinefunction(b))

    def test_legacy_keyforge_env_vars(self) -> None:
        import os
        from unittest import mock

        env = {"KEYFORGE_LICENSE": "legacy-token", "KEYFORGE_URL": "http://legacy/", "KEYFLINT_DOMAIN": "new.example"}
        with mock.patch.dict(os.environ, env, clear=True):
            kf = KeyFlint()
        self.assertEqual(kf.license_key, "legacy-token")
        self.assertEqual(kf.gateway_url, "http://legacy")
        self.assertEqual(kf.domain, "new.example")
        with mock.patch.dict(os.environ, {"KEYFORGE_LICENSE": "old", "KEYFLINT_LICENSE": "new"}, clear=True):
            self.assertEqual(KeyFlint().license_key, "new")

    def test_invalid_license(self) -> None:
        kf = KeyFlint(license_key=TOKEN, public_keys=DATA["keys"]["k2"])

        @kf.require_license
        def t() -> None: ...

        with self.assertRaises(LicenseError) as cm:
            t()
        self.assertEqual(cm.exception.reason, "ERR_SIGNATURE_TAMPERED")
        self.assertEqual(cm.exception.details["reason"], "ERR_SIGNATURE_TAMPERED")

    def test_missing_feature(self) -> None:
        @self.kf.require_license(features=["studio_only"])
        def t() -> None: ...

        with self.assertRaises(LicenseError) as cm:
            t()
        self.assertEqual(cm.exception.reason, "FEATURE_NOT_ENTITLED")
        self.assertEqual(cm.exception.details["missing_features"], ["studio_only"])

    def test_metered_deducts_then_402(self) -> None:
        calls = []

        @self.kf.metered(credits=4)
        async def tool(q: str) -> str:
            calls.append(q)
            return q.upper()

        self.assertEqual(asyncio.run(tool("a")), "A")
        self.assertEqual(asyncio.run(tool("b")), "B")
        with self.assertRaises(LicenseError) as cm:
            asyncio.run(tool("c"))
        err = cm.exception
        self.assertEqual(err.reason, "QUOTA_EXHAUSTED")
        self.assertIn("https://shop.example/upgrade", str(err))
        self.assertEqual(calls, ["a", "b"])  # the tool never ran without credits
        bodies = [b for b, _ in self.gw.requests]
        self.assertEqual([b["credits"] for b in bodies], [4, 4, 4])
        self.assertEqual(bodies[0]["event_type"], "mcp:tool")
        keys = [b["idempotency_key"] for b in bodies]
        self.assertEqual(len(set(keys)), 3)
        self.assertEqual(keys, [h for _, h in self.gw.requests])  # header mirrors body

    def test_metered_sync(self) -> None:
        @self.kf.metered(credits=10)
        def tool() -> str:
            return "ok"

        self.assertEqual(tool(), "ok")
        self.assertEqual(self.gw.balance, 0)

    def test_metered_refunds_on_exception_and_error_result(self) -> None:
        @self.kf.metered(credits=3)
        async def boom() -> str:
            raise RuntimeError("upstream down")

        @self.kf.metered(credits=2)
        def soft() -> dict:
            return {"isError": True, "content": []}

        with self.assertRaises(RuntimeError):
            asyncio.run(boom())
        self.assertEqual(soft()["isError"], True)
        self.assertEqual(self.gw.balance, 10)
        keys = [b["idempotency_key"] for b, _ in self.gw.requests]
        self.assertEqual([r["idempotency_key"] for r in self.gw.refunds], keys)
        self.assertEqual([r["reason"] for r in self.gw.refunds], ["tool_error", "tool_error_result"])

    def test_metered_refund_disabled(self) -> None:
        @self.kf.metered(credits=3, refund_on_error=False)
        def boom() -> None:
            raise RuntimeError("x")

        with self.assertRaises(RuntimeError):
            boom()
        self.assertEqual(self.gw.balance, 7)
        self.assertEqual(self.gw.refunds, [])

    def test_gateway_unreachable(self) -> None:
        kf = KeyFlint(license_key=TOKEN, public_keys=PK, gateway_url="http://127.0.0.1:9", timeout=0.5)

        @kf.metered()
        def tool() -> None: ...

        with self.assertRaises(LicenseError) as cm:
            tool()
        self.assertEqual(cm.exception.reason, "GATEWAY_UNREACHABLE")

    def test_metered_idempotency_replays_first_result_after_client_timeout(self) -> None:
        calls = 0

        @self.kf.metered(credits=3, idempotency_key=lambda req_id, query: req_id)
        def tool(req_id: str, query: str) -> str:
            nonlocal calls
            calls += 1
            return f"{query}:{calls}"

        # Attempt 1 finishes the work, even if the caller timed out before reading it.
        first = tool("req-timeout-1", "alpha")
        # Attempt 2 retries with the same request ID: replays first result and skips the second charge.
        retry = tool("req-timeout-1", "alpha")
        self.assertEqual(first, "alpha:1")
        self.assertEqual(retry, "alpha:1")
        self.assertEqual(calls, 1)
        self.assertEqual(self.gw.balance, 7)
        self.assertEqual(len(self.gw.requests), 1)
        self.assertEqual(self.gw.requests[0][0]["idempotency_key"], "mcp:tool:req-timeout-1")

        # Distinct request IDs execute normally and charge again.
        second = tool("req-timeout-2", "alpha")
        self.assertEqual(second, "alpha:2")
        self.assertEqual(calls, 2)
        self.assertEqual(self.gw.balance, 4)
        self.assertEqual(len(self.gw.requests), 2)

    def test_metered_idempotency_coalesces_inflight_async_retries_and_skips_errors(self) -> None:
        calls = 0

        async def scenario() -> None:
            nonlocal calls
            started = asyncio.Event()
            release = asyncio.Event()

            @self.kf.metered(credits=4, idempotency_key=lambda req_id, fail=False: req_id)
            async def slow(req_id: str, fail: bool = False) -> dict:
                nonlocal calls
                calls += 1
                if calls == 1:
                    started.set()
                    await release.wait()
                if fail:
                    return {"isError": True, "calls": calls}
                return {"ok": True, "calls": calls}

            task1 = asyncio.create_task(slow("inflight-1"))
            await started.wait()
            # Retry arrives while attempt 1 is still running: must wait and share result + single charge.
            task2 = asyncio.create_task(slow("inflight-1"))
            await asyncio.sleep(0.02)
            release.set()
            r1, r2 = await asyncio.gather(task1, task2)
            self.assertEqual(r1, {"ok": True, "calls": 1})
            self.assertEqual(r2, {"ok": True, "calls": 1})
            self.assertEqual(calls, 1)
            self.assertEqual(len(self.gw.requests), 1)
            self.assertEqual(self.gw.balance, 6)

            # Errors / isError are refunded and never cached.
            err_res = await slow("err-1", fail=True)
            self.assertTrue(err_res["isError"])
            self.assertEqual(self.gw.balance, 6)
            self.assertEqual(len(self.gw.refunds), 1)

        asyncio.run(scenario())

    def test_metered_dedup_ttl_and_zero_disables_cache(self) -> None:
        from unittest import mock

        calls = 0

        @self.kf.metered(credits=2, idempotency_key=lambda req_id: req_id, dedup_ttl=10.0)
        def timed(req_id: str) -> int:
            nonlocal calls
            calls += 1
            return calls

        @self.kf.metered(credits=2, idempotency_key=lambda req_id: req_id, dedup_ttl=0)
        def uncached(req_id: str) -> int:
            nonlocal calls
            calls += 1
            return calls

        now = [100.0]
        with mock.patch("keyflint_verify.mcp.time.monotonic", side_effect=lambda: now[0]):
            self.assertEqual(timed("k"), 1)
            now[0] = 105.0
            self.assertEqual(timed("k"), 1)
            now[0] = 111.0
            self.assertEqual(timed("k"), 2)
        self.assertEqual(uncached("u"), 3)
        self.assertEqual(uncached("u"), 4)
        self.assertEqual(self.gw.requests[-1][0]["idempotency_key"], self.gw.requests[-2][0]["idempotency_key"])
        with self.assertRaises(ValueError):
            self.kf.metered(dedup_ttl=-1.0)


try:
    from mcp.server.mcpserver import MCPServer  # type: ignore[import-not-found]
    from mcp.client.client import Client  # type: ignore[import-not-found]
    from mcp.shared.exceptions import MCPError  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    MCPServer = None  # type: ignore[assignment,misc]


class TestKeysEnvAndMessages(unittest.TestCase):
    def test_mixed_legacy_and_kid_entries(self) -> None:
        k1, k2 = DATA["keys"]["k1"], DATA["keys"]["k2"]
        self.assertEqual(_parse_keys_env(f"{k1}, k2={k2}"), {"legacy-0": k1, "k2": k2})
        self.assertEqual(_parse_keys_env(k1), k1)
        self.assertEqual(_parse_keys_env(f"{k1},{k2}"), [k1, k2])
        kf = KeyFlint(license_key=V["ring_kid_token_new_key"]["token"], public_keys=_parse_keys_env(f"{k1},k2={k2}"))
        self.assertTrue(kf.check().valid)

    def test_expired_message_is_actionable(self) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import base64
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
        body = json.dumps({"tier": "pro", "license_id": "x", "expires_at": 1_000_000_000}).encode()
        sig = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("11" * 32)).sign(body)  # vectors key k1
        token = f"LIC-PRO-{b64(body)}.{b64(sig)}"
        kf = KeyFlint(license_key=token, public_keys=PK, checkout_url="https://shop.example/renew")
        with self.assertRaises(LicenseError) as cm:
            kf.check()
        self.assertEqual(cm.exception.reason, "ERR_LICENSE_EXPIRED")
        self.assertRegex(str(cm.exception), r"^Your license expired on \d{4}-\d{2}-\d{2}\. Get or renew a license: https://shop\.example/renew$")


@unittest.skipIf(MCPServer is None, "mcp>=2 not installed")
class TestMCPServerIntegration(unittest.TestCase):
    def test_tools_over_mcp(self) -> None:
        gw = FakeGateway(balance=5)
        try:
            kf = KeyFlint(license_key=TOKEN, public_keys=PK, gateway_url=gw.url)
            server = MCPServer("demo")

            @server.tool()
            @kf.metered(credits=5)
            async def summarize(text: str) -> str:
                return text[:3]

            @server.tool()
            @kf.require_license(features=["missing"])
            def gated() -> str:
                return "never"

            async def run() -> None:
                async with Client(server) as client:
                    tools = {t.name: t for t in (await client.list_tools()).tools}
                    self.assertIn("text", tools["summarize"].input_schema["properties"])
                    ok = await client.call_tool("summarize", {"text": "hello"})
                    self.assertFalse(ok.is_error)
                    for name, args, code in (("summarize", {"text": "x"}, QUOTA_EXHAUSTED),
                                             ("gated", {}, FEATURE_NOT_ENTITLED)):
                        with self.assertRaises(MCPError) as cm:
                            await client.call_tool(name, args)
                        self.assertEqual(cm.exception.code, code)

            asyncio.run(run())
            self.assertEqual((LICENSE_INVALID, FEATURE_NOT_ENTITLED, QUOTA_EXHAUSTED, GATEWAY_ERROR), (-32060, -32061, -32062, -32063))
        finally:
            gw.close()


if __name__ == "__main__":
    unittest.main()
