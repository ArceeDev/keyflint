import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { createKeyFlint, KeyFlintMcpError, QUOTA_EXHAUSTED, FEATURE_NOT_ENTITLED, LICENSE_INVALID } from "../dist/esm/mcp.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { z } from "zod";
process.env.KEYFLINT_CLOCK_STATE = "off"; // tests must not write to ~/.keyflint

const { keys, vectors } = JSON.parse(readFileSync(new URL("../../vectors/vectors.json", import.meta.url), "utf8"));
const TOKEN = vectors.find((v) => v.name === "valid_perpetual").token;

async function fakeGateway(balance) {
  const requests = [];
  const refunds = [];
  const deducts = new Map();
  const server = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      const body = JSON.parse(raw);
      if (req.url.endsWith("/quota/refund")) {
        refunds.push(body);
        balance += deducts.get(body.idempotency_key) ?? 0;
        deducts.delete(body.idempotency_key);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ success: true, data: { remaining_balance: balance } }));
        return;
      }
      requests.push({ body, header: req.headers["idempotency-key"] });
      const ok = body.credits <= balance;
      if (ok) { balance -= body.credits; deducts.set(body.idempotency_key, body.credits); }
      res.writeHead(ok ? 200 : 402, { "Content-Type": "application/json" });
      res.end(JSON.stringify(ok ? { success: true, data: { remaining_balance: balance } }
        : { success: false, error: { code: "QUOTA_EXHAUSTED", message: "0 left", status_code: 402, details: {} } }));
    });
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  return { url: `http://127.0.0.1:${server.address().port}`, requests, refunds, balance: () => balance, close: () => server.close() };
}

test("requireLicense is offline and keeps arguments", async () => {
  const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k1, fetch: () => assert.fail("no network") });
  const tool = kf.requireLicense(async (a, b) => a + b, { features: ["core"] });
  assert.equal(await tool(2, 3), 5);
});

test("invalid license and missing feature throw McpError-shaped errors", async () => {
  const bad = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k2 });
  await assert.rejects(bad.requireLicense(() => 1)(), (e) =>
    e instanceof KeyFlintMcpError && e.code === LICENSE_INVALID && e.reason === "ERR_SIGNATURE_TAMPERED");
  const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k1, checkoutUrl: "https://shop/x" });
  await assert.rejects(kf.requireLicense(() => 1, { features: ["studio_only"] })(), (e) =>
    e.code === FEATURE_NOT_ENTITLED && e.data.missingFeatures[0] === "studio_only" && e.data.checkoutUrl === "https://shop/x");
});

test("metered deducts with idempotency key, then 402 before the handler runs", async () => {
  const gw = await fakeGateway(8);
  try {
    const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k1, gatewayUrl: gw.url, checkoutUrl: "https://shop/up" });
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
  const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k1, gatewayUrl: "http://127.0.0.1:9", timeoutMs: 500 });
  await assert.rejects(kf.metered(1, () => 1)(), (e) => e.reason === "GATEWAY_UNREACHABLE");
});

test("works inside @modelcontextprotocol/sdk McpServer", async () => {
  const gw = await fakeGateway(5);
  try {
    const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: { legacy: keys.k1 }, gatewayUrl: gw.url });
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
  const m = createRequire(import.meta.url)("keyflint-verify/mcp");
  assert.equal(typeof m.createKeyFlint, "function");
  assert.deepEqual([m.LICENSE_INVALID, m.FEATURE_NOT_ENTITLED, m.QUOTA_EXHAUSTED, m.GATEWAY_ERROR], [-32060, -32061, -32062, -32063]);
  assert.deepEqual(m.parseKeysEnv("aa, k2=bb"), { "legacy-0": "aa", k2: "bb" });
  assert.equal(m.parseKeysEnv("aa"), "aa");
  assert.deepEqual(m.parseKeysEnv("aa,bb"), ["aa", "bb"]);
});

test("metered refunds credits when the handler throws or returns isError", async () => {
  const gw = await fakeGateway(10);
  try {
    const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k1, gatewayUrl: gw.url });
    await assert.rejects(kf.metered(3, async () => { throw new Error("upstream down"); })(), /upstream down/);
    const soft = await kf.metered(2, async () => ({ isError: true, content: [] }))();
    assert.equal(soft.isError, true);
    assert.equal(gw.balance(), 10);
    assert.deepEqual(gw.refunds.map((r) => r.idempotency_key), gw.requests.map((r) => r.body.idempotency_key));
    assert.deepEqual(gw.refunds.map((r) => r.reason), ["tool_error", "tool_error_result"]);
    await assert.rejects(kf.metered(4, async () => { throw new Error("x"); }, { refundOnError: false })(), /x/);
    assert.equal(gw.balance(), 6);
  } finally {
    gw.close();
  }
});

test("license errors carry an actionable message", async () => {
  const expired = vectors.find((v) => v.name === "ring_kid_token_without_key");
  const kf = createKeyFlint({ licenseKey: expired.token, publicKeys: { legacy: keys.k1 }, checkoutUrl: "https://shop/renew" });
  await assert.rejects(kf.check(), (e) =>
    e.code === LICENSE_INVALID && e.data.reason === "ERR_UNKNOWN_KID" && /does not trust/.test(e.message) && !e.message.includes("https://shop/renew"));
  const kf2 = createKeyFlint({ licenseKey: "", publicKeys: keys.k1, checkoutUrl: "https://shop/renew" });
  await assert.rejects(kf2.check(), (e) => e.message === "No KeyFlint license is configured. Set KEYFLINT_LICENSE. Get or renew a license: https://shop/renew");
});

test("legacy KEYFORGE_* env vars are honoured, KEYFLINT_* wins", async () => {
  const saved = { ...process.env };
  try {
    for (const k of Object.keys(process.env)) if (/^KEY(FORGE|FLINT)_/.test(k)) delete process.env[k];
    process.env.KEYFORGE_PUBLIC_KEYS = keys.k1;
    process.env.KEYFORGE_CHECKOUT_URL = "https://legacy/renew";
    await assert.rejects(createKeyFlint().check(), (e) => e.message.endsWith("https://legacy/renew"));
    process.env.KEYFLINT_CHECKOUT_URL = "https://new/renew";
    await assert.rejects(createKeyFlint().check(), (e) => e.message.endsWith("https://new/renew"));
  } finally {
    for (const k of Object.keys(process.env)) if (!(k in saved)) delete process.env[k];
    Object.assign(process.env, saved);
  }
});

test("metered idempotencyKey replays first result after timeout and coalesces concurrent retries", async () => {
  const gw = await fakeGateway(10);
  try {
    const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k1, gatewayUrl: gw.url });
    let calls = 0;
    let release;
    const gate = new Promise((r) => (release = r));
    const slow = kf.metered(
      3,
      async function slow(reqId, waitGate = false) {
        calls++;
        if (waitGate) await gate;
        return `res:${reqId}:${calls}`;
      },
      { idempotencyKey: (reqId) => reqId },
    );

    // Work done, caller timed out, caller retries: replays first answer and skips second charge.
    assert.equal(await slow("done-1"), "res:done-1:1");
    assert.equal(await slow("done-1"), "res:done-1:1");
    assert.equal(calls, 1);
    assert.equal(gw.requests.length, 1);
    assert.equal(gw.balance(), 7);
    assert.equal(gw.requests[0].body.idempotency_key, "mcp:slow:done-1");

    // Concurrent retry while attempt 1 is still running coalesces cleanly.
    const p1 = slow("inflight-1", true);
    const p2 = slow("inflight-1", true);
    release();
    const [a, b] = await Promise.all([p1, p2]);
    assert.equal(a, "res:inflight-1:2");
    assert.equal(b, "res:inflight-1:2");
    assert.equal(calls, 2);
    assert.equal(gw.requests.length, 2);
    assert.equal(gw.balance(), 4);

    // Distinct keys (or undefined key) execute and deduct normally.
    assert.equal(await slow(undefined), "res:undefined:3");
    assert.equal(gw.balance(), 1);
  } finally {
    gw.close();
  }
});

test("metered rejects negative dedupTtlMs and does not cache error results", async () => {
  const gw = await fakeGateway(10);
  try {
    const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k1, gatewayUrl: gw.url });
    assert.throws(() => kf.metered(1, async () => 1, { dedupTtlMs: -1 }), RangeError);
    let runs = 0;
    const flaky = kf.metered(2, async () => {
      runs++;
      return { isError: true, runs };
    }, { idempotencyKey: () => "err-key" });
    assert.equal((await flaky()).isError, true);
    assert.equal((await flaky()).runs, 2);
    assert.equal(gw.refunds.length, 2);
    assert.equal(gw.balance(), 10);
  } finally {
    gw.close();
  }
});
