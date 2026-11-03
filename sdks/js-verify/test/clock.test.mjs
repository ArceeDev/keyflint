import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createKeyFlint, createClockGuard, stableMachineId } from "../dist/esm/mcp.js";

const { keys, vectors } = JSON.parse(readFileSync(new URL("../../vectors/vectors.json", import.meta.url), "utf8"));
const V = Object.fromEntries(vectors.map((v) => [v.name, v]));

test("clock guard is monotonic and shares the Python file format", async () => {
  const dir = mkdtempSync(join(tmpdir(), "kf-clock-"));
  try {
    const f = join(dir, "a", "clock_state");
    const g = createClockGuard(f);
    assert.equal(await g.lastSeen(), undefined);
    await g.record(2000);
    await g.record(1000);
    assert.equal(await g.lastSeen(), 2000);
    assert.deepEqual(JSON.parse(readFileSync(f, "utf8")), { v: 1, last_seen: 2000 });
    assert.equal(await createClockGuard(f).lastSeen(), 2000);
    const mem = createClockGuard(null);
    await mem.record(5);
    assert.equal(await mem.lastSeen(), 5);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("MCP check rejects a clock set back (expiring license only)", async () => {
  const dir = mkdtempSync(join(tmpdir(), "kf-clock-"));
  const realNow = Date.now;
  try {
    const f = join(dir, "clock_state");
    const exp = 1_800_003_600;
    Date.now = () => (exp - 100) * 1000;
    await createKeyFlint({ licenseKey: V.valid_basic.token, publicKeys: keys.k1, clockGuard: createClockGuard(f) }).check();
    Date.now = () => (exp - 10_000) * 1000;
    const kf = createKeyFlint({ licenseKey: V.valid_basic.token, publicKeys: keys.k1, clockGuard: createClockGuard(f) });
    await assert.rejects(kf.check(), (e) => e.code === -32060 && e.reason === "ERR_CLOCK_ROLLBACK_DETECTED");

    const pf = join(dir, "perpetual");
    await createKeyFlint({ licenseKey: V.valid_perpetual.token, publicKeys: keys.k1, clockGuard: createClockGuard(pf) }).check();
    assert.equal(existsSync(pf), false);
  } finally {
    Date.now = realNow;
    rmSync(dir, { recursive: true, force: true });
  }
});

test("stable machine id matches the Python formula", async () => {
  process.env.KEYFLINT_HOST_ID = "host-123";
  try {
    const { createHash } = await import("node:crypto");
    const expected = createHash("sha256").update("keyflint-stable:env:host-123").digest("hex");
    assert.equal(await stableMachineId(), expected);
  } finally {
    delete process.env.KEYFLINT_HOST_ID;
  }
});
