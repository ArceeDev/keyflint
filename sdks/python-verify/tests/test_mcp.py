"""Tests for keyforge_verify.mcp against a fake gateway and (if installed) the real mcp SDK."""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from keyforge_verify.mcp import (
    FEATURE_NOT_ENTITLED,
    LICENSE_INVALID,
    QUOTA_EXHAUSTED,
    KeyForge,
    LicenseError,
)

DATA = json.loads((Path(__file__).resolve().parents[1].parent / "vectors" / "vectors.json").read_text("utf-8"))
V = {v["name"]: v for v in DATA["vectors"]}
TOKEN = V["valid_perpetual"]["token"]  # never expires, so the tests do not age
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
        self.kf = KeyForge(license_key=TOKEN, public_keys=PK, gateway_url=self.gw.url,
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

    def test_invalid_license(self) -> None:
        kf = KeyForge(license_key=TOKEN, public_keys=DATA["keys"]["k2"])

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
        kf = KeyForge(license_key=TOKEN, public_keys=PK, gateway_url="http://127.0.0.1:9", timeout=0.5)

        @kf.metered()
        def tool() -> None: ...

        with self.assertRaises(LicenseError) as cm:
            tool()
        self.assertEqual(cm.exception.reason, "GATEWAY_UNREACHABLE")


try:
    from mcp.server.mcpserver import MCPServer  # type: ignore[import-not-found]
    from mcp.client.client import Client  # type: ignore[import-not-found]
    from mcp.shared.exceptions import MCPError  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    MCPServer = None  # type: ignore[assignment,misc]


@unittest.skipIf(MCPServer is None, "mcp>=2 not installed")
class TestMCPServerIntegration(unittest.TestCase):
    def test_tools_over_mcp(self) -> None:
        gw = FakeGateway(balance=5)
        try:
            kf = KeyForge(license_key=TOKEN, public_keys=PK, gateway_url=gw.url)
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
            self.assertEqual(LICENSE_INVALID, -32040)
        finally:
            gw.close()


if __name__ == "__main__":
    unittest.main()
