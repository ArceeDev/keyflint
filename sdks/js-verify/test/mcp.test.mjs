import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { createKeyForge, KeyForgeMcpError, QUOTA_EXHAUSTED, FEATURE_NOT_ENTITLED, LICENSE_INVALID } from "../dist/esm/mcp.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { z } from "zod";

const { keys, vectors } = JSON.parse(readFileSync(new URL("../../vectors/vectors.json", import.meta.url), "utf8"));
const TOKEN = vectors.find((v) => v.name === "valid_perpetual").token;

async function fakeGateway(balance) {
  const requests = [];
  const server = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      const body = JSON.parse(raw);
      requests.push({ body, header: req.headers["idempotency-key"] });
      const ok = body.credits <= balance;
      if (ok) balance -= body.credits;
      res.writeHead(ok ? 200 : 402, { "Content-Type": "application/json" });
      res.end(JSON.stringify(ok ? { success: true, data: { remaining_balance: balance } }
        : { success: false, error: { code: "QUOTA_EXHAUSTED", message: "0 left", status_code: 402, details: {} } }));
    });
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  return { url: `http://127.0.0.1:${server.address().port}`, requests, close: () => server.close() };
}

test("requireLicense is offline and keeps arguments", async () => {
  const kf = createKeyForge({ licenseKey: TOKEN, publicKeys: keys.k1, fetch: () => assert.fail("no network") });
  const tool = kf.requireLicense(async (a, b) => a + b, { features: ["core"] });
  assert.equal(await tool(2, 3), 5);
});

test("invalid license and missing feature throw McpError-shaped errors", async () => {
  const bad = createKeyForge({ licenseKey: TOKEN, publicKeys: keys.k2 });
  await assert.rejects(bad.requireLicense(() => 1)(), (e) =>
    e instanceof KeyForgeMcpError && e.code === LICENSE_INVALID && e.reason === "ERR_SIGNATURE_TAMPERED");
  const kf = createKeyForge({ licenseKey: TOKEN, publicKeys: keys.k1, checkoutUrl: "https://shop/x" });
  await assert.rejects(kf.requireLicense(() => 1, { features: ["studio_only"] })(), (e) =>
    e.code === FEATURE_NOT_ENTITLED && e.data.missingFeatures[0] === "studio_only" && e.data.checkoutUrl === "https://shop/x");
});

test("metered deducts with idempotency key, then 402 before the handler runs", async () => {
  const gw = await fakeGateway(8);
  try {
    const kf = createKeyForge({ licenseKey: TOKEN, publicKeys: keys.k1, gatewayUrl: gw.url, checkoutUrl: "https://shop/up" });
    const ran = [];
    const tool = kf.metered(4, async function summarize(q) { ran.push(q); return q.toUpperCase(); });
    assert.equal(await tool("a"), "A");
    assert.equal(await tool("b"), "B");
    await assert.rejects(tool("c"), (e) => e.code === QUOTA_EXHAUSTED && e.message.includes("https://shop/up"));
    assert.deepEqual(ran, ["a", "b"]);
    const ids = gw.requests.map((r) => r.body.idempotency_key);
    assert.equal(new Set(ids).size, 3);
    assert.deepEqual(ids, gw.requests.map((r) => r.header));
    assert.equal(gw.requests[0].body.event_type, "mcp:summarize");
  } finally { gw.close(); }
});

test("gateway unreachable", async () => {
  const kf = createKeyForge({ licenseKey: TOKEN, publicKeys: keys.k1, gatewayUrl: "http://127.0.0.1:9", timeoutMs: 500 });
  await assert.rejects(kf.metered(1, () => 1)(), (e) => e.reason === "GATEWAY_UNREACHABLE");
});

test("works inside @modelcontextprotocol/sdk McpServer", async () => {
  const gw = await fakeGateway(5);
  try {
    const kf = createKeyForge({ licenseKey: TOKEN, publicKeys: { legacy: keys.k1 }, gatewayUrl: gw.url });
    const server = new McpServer({ name: "demo", version: "1.0.0" });
    server.registerTool("summarize", { inputSchema: { text: z.string() } },
      kf.metered(5, async ({ text }) => ({ content: [{ type: "text", text: text.slice(0, 3) }] })));
    server.registerTool("gated", {}, kf.requireLicense(async () => ({ content: [{ type: "text", text: "x" }] }), { features: ["nope"] }));
    const [ct, st] = InMemoryTransport.createLinkedPair();
    const client = new Client({ name: "t", version: "1.0.0" });
    await Promise.all([server.connect(st), client.connect(ct)]);

    const ok = await client.callTool({ name: "summarize", arguments: { text: "hello" } });
    assert.equal(ok.isError ?? false, false);
    assert.equal(ok.content[0].text, "hel");
    const out = await client.callTool({ name: "summarize", arguments: { text: "x" } });
    assert.equal(out.isError, true);
    assert.match(out.content[0].text, /Credits exhausted/);
    const gated = await client.callTool({ name: "gated", arguments: {} });
    assert.equal(gated.isError, true);
    assert.match(gated.content[0].text, /nope/);
    await client.close();
  } finally { gw.close(); }
});

test("CommonJS subpath export", async () => {
  const { createRequire } = await import("node:module");
  const m = createRequire(import.meta.url)("keyforge-verify/mcp");
  assert.equal(typeof m.createKeyForge, "function");
  assert.equal(m.QUOTA_EXHAUSTED, -32042);
});
