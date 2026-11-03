import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createKeyFlint, MAX_OFFLINE_GRACE_CALLS } from "../dist/esm/mcp.js";

process.env.KEYFLINT_CLOCK_STATE = "off";
const { keys, vectors } = JSON.parse(readFileSync(new URL("../../vectors/vectors.json", import.meta.url), "utf8"));
const TOKEN = vectors.find((v) => v.name === "valid_perpetual").token;

function gateway(balance) {
  const gw = { down: true, status502: false, balance, deducts: [], refunds: [] };
  gw.fetch = async (url, init) => {
    if (gw.down) throw new TypeError("fetch failed");
    if (gw.status502) return new Response("bad gateway", { status: 502 });
    const body = JSON.parse(init.body);
    if (url.endsWith("/quota/refund")) {
      gw.refunds.push(body.idempotency_key);
      return Response.json({ success: true, data: {} });
    }
    if (body.credits > gw.balance) {
      return Response.json({ success: false, error: { code: "QUOTA_EXHAUSTED", details: {} } }, { status: 402 });
    }
    gw.balance -= body.credits;
    gw.deducts.push(body.idempotency_key);
    return Response.json({ success: true, data: { remaining_balance: gw.balance } });
  };
  return gw;
}

test("offline grace is opt-in: default fails closed", async () => {
  const gw = gateway(100);
  const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k1, gatewayUrl: "http://gw", fetch: gw.fetch });
  const tool = kf.metered(2, async () => "ran");
  await assert.rejects(tool(), (e) => e.code === -32063 && e.reason === "GATEWAY_UNREACHABLE");
});

test("offline grace runs N calls, replays debits on recovery, never refunds them", async () => {
  const gw = gateway(100);
  const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k1, gatewayUrl: "http://gw", fetch: gw.fetch });
  let ran = 0;
  const tool = kf.metered(2, async () => { ran++; return { isError: true }; }, { offlineGraceCalls: 3, timeoutMs: 200 });
  for (let i = 0; i < 3; i++) await tool();
  assert.equal(kf.pendingDebits, 3);
  await assert.rejects(tool());
  assert.equal(ran, 3);

  gw.down = false;
  gw.status502 = true; // a 502 from the edge proxy is transient: queue kept, budget still exhausted
  await assert.rejects(tool(), (e) => e.data.status === 502);
  assert.equal(kf.pendingDebits, 3);
  gw.status502 = false;
  await tool();
  assert.equal(kf.pendingDebits, 0);
  assert.equal(gw.deducts.length, 4);
  assert.equal(new Set(gw.deducts).size, 4);
  assert.deepEqual(gw.refunds, [gw.deducts[3]]); // only the live call is refunded
});

test("refused queued debit is dropped; cap is enforced", async () => {
  const gw = gateway(100);
  const kf = createKeyFlint({ licenseKey: TOKEN, publicKeys: keys.k1, gatewayUrl: "http://gw", fetch: gw.fetch });
  const tool = kf.metered(60, async () => "ok", { offlineGraceCalls: 2, refundOnError: false });
  gw.status502 = true;
  await tool(); // 502 counts as transient too
  gw.status502 = false;
  await tool();
  gw.down = false;
  assert.equal(await kf.flushPending(), 2);
  assert.equal(kf.pendingDebits, 0);
  assert.equal(gw.balance, 40);
  assert.throws(() => kf.metered(1, async () => 0, { offlineGraceCalls: MAX_OFFLINE_GRACE_CALLS + 1 }), RangeError);
});
