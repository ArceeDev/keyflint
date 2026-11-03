import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { PassThrough } from "node:stream";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { createKeyFlint, LICENSE_INVALID, QUOTA_EXHAUSTED, FEATURE_NOT_ENTITLED } from "keyflint-verify/mcp";
import { parseArgs, wrap, UsageError } from "../src/wrap.js";
process.env.KEYFLINT_CLOCK_STATE = "off"; // tests must not write to ~/.keyflint

const { keys, vectors } = JSON.parse(readFileSync(new URL("../../vectors/vectors.json", import.meta.url), "utf8"));
const TOKEN = vectors.find((v) => v.name === "valid_perpetual").token;
const SERVER = fileURLToPath(new URL("./fixtures/echo-server.mjs", import.meta.url));
const BIN = fileURLToPath(new URL("../bin/keyflint-wrap.js", import.meta.url));

async function fakeGateway(balance) {
  const deducts = [];
  const refunds = [];
  const charged = new Map();
  const server = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      const body = JSON.parse(raw);
      res.setHeader("Content-Type", "application/json");
      if (req.url.endsWith("/quota/refund")) {
        refunds.push(body);
        balance += charged.get(body.idempotency_key) ?? 0;
        res.end(JSON.stringify({ success: true, data: { remaining_balance: balance } }));
        return;
      }
      deducts.push(body);
      const ok = body.credits <= balance;
      if (ok) { balance -= body.credits; charged.set(body.idempotency_key, body.credits); }
      res.writeHead(ok ? 200 : 402);
      res.end(JSON.stringify(ok ? { success: true, data: { remaining_balance: balance } }
        : { success: false, error: { code: "QUOTA_EXHAUSTED", message: "0 left", status_code: 402, details: {} } }));
    });
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  return { url: `http://127.0.0.1:${server.address().port}`, deducts, refunds, balance: () => balance, close: () => server.close() };
}

function session(argv, kfOptions) {
  const stdin = new PassThrough();
  const stdout = new PassThrough();
  const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys, ...kfOptions });
  const done = wrap(parseArgs([...argv, "--", process.execPath, SERVER], { KEYFLINT_URL: kfOptions?.gatewayUrl ?? "" }), { stdin, stdout, kf });
  const pending = new Map();
  createInterface({ input: stdout }).on("line", (l) => {
    const m = JSON.parse(l);
    const key = JSON.stringify(Array.isArray(m) ? "batch" : m.id);
    pending.get(key)?.(m);
    pending.delete(key);
  });
  let n = 0;
  const request = (method, params, id = ++n) => new Promise((resolve) => {
    pending.set(JSON.stringify(id), resolve);
    stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  });
  const batch = (msgs) => new Promise((resolve) => {
    pending.set(JSON.stringify("batch"), resolve);
    stdin.write(JSON.stringify(msgs) + "\n");
  });
  const call = (name) => request("tools/call", { name, arguments: {} });
  const close = () => { stdin.end(); return done; };
  return { request, call, batch, close };
}

test("parseArgs: flags, defaults and errors", () => {
  const o = parseArgs(["--tool", "a=5", "--tool", "b=0", "--free", "x,y", "--features", "pro", "--", "python", "s.py"], {});
  assert.equal(o.command, "python");
  assert.deepEqual(o.args, ["s.py"]);
  assert.equal(o.tools.get("a"), 5);
  assert.equal(o.tools.get("b"), 0);
  assert.deepEqual([...o.free], ["x", "y"]);
  assert.deepEqual(o.features, ["pro"]);
  assert.equal(o.defaultCredits, 0, "no gateway: license check only");
  assert.equal(parseArgs(["--", "x"], { KEYFLINT_URL: "https://g" }).defaultCredits, 1);
  assert.throws(() => parseArgs(["python"], {}), UsageError);
  assert.throws(() => parseArgs(["--tool", "a", "--", "x"], {}), UsageError);
  assert.throws(() => parseArgs(["--credits", "-1", "--", "x"], {}), UsageError);
  assert.throws(() => parseArgs(["--offline-grace", "6", "--", "x"], {}), UsageError);
  assert.throws(() => parseArgs(["--nope", "--", "x"], {}), UsageError);
});

test("non-tool traffic passes through untouched", async () => {
  const s = session([], {});
  const init = await s.request("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "t", version: "1" } });
  assert.equal(init.result.serverInfo.name, "echo");
  const list = await s.request("tools/list", {});
  assert.equal(list.result.tools.length, 3);
  assert.equal(await s.close(), 0);
});

test("license-only mode: valid license runs the tool, missing license is refused before the server", async () => {
  const ok = session([], {});
  assert.equal((await ok.call("ok")).result.content[0].text, "ran ok");
  await ok.close();

  const bad = session([], { licenseKey: "" });
  const r = await bad.call("ok");
  assert.equal(r.error.code, LICENSE_INVALID);
  assert.equal(r.error.data.reason, "ERR_EMPTY_TOKEN");
  await bad.close();
});

test("features are enforced", async () => {
  const s = session(["--features", "definitely_not_granted"], {});
  assert.equal((await s.call("ok")).error.code, FEATURE_NOT_ENTITLED);
  await s.close();
});

test("metered: deducts per tool, refunds failures, stops at zero balance", async () => {
  const gw = await fakeGateway(7);
  const s = session(["--credits", "1", "--tool", "ok=5", "--free", "free"], { gatewayUrl: gw.url });
  assert.equal((await s.call("ok")).result.isError, false);
  assert.equal(gw.balance(), 2);
  assert.equal(gw.deducts[0].credits, 5);
  assert.equal(gw.deducts[0].event_type, "mcp:ok");

  const failed = await s.call("fail");
  assert.equal(failed.result.isError, true, "server's isError result is relayed as-is");
  const boom = await s.call("boom");
  assert.equal(boom.error.message, "boom", "server's JSON-RPC error is relayed as-is");
  assert.equal(gw.refunds.length, 2);
  assert.equal(gw.balance(), 2, "both failed calls were refunded");

  const broke = await s.call("ok");
  assert.equal(broke.error.code, QUOTA_EXHAUSTED);
  assert.equal(gw.balance(), 2);

  const before = gw.deducts.length;
  assert.equal((await s.call("free")).result.content[0].text, "ran free");
  assert.equal(gw.deducts.length, before, "--free tools are never metered");
  await s.close();
  gw.close();
});

test("batched tools/call is refused, the rest of the batch is forwarded", async () => {
  const s = session([], {});
  const r = await s.batch([{ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "ok" } }, { jsonrpc: "2.0", id: 2, method: "ping" }]);
  assert.equal(r.length, 1);
  assert.equal(r[0].id, 1);
  assert.ok(r[0].error);
  await s.close();
});

test("CLI: usage errors exit 2 and the server's exit code is propagated", () => {
  assert.equal(spawnSync(process.execPath, [BIN, "python"]).status, 2);
  const r = spawnSync(process.execPath, [BIN, "--", process.execPath, SERVER], {
    input: JSON.stringify({ jsonrpc: "2.0", method: "exit" }) + "\n",
    env: { ...process.env, KEYFLINT_URL: "" },
  });
  assert.equal(r.status, 3);
});
