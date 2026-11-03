import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { verifyLicense, createVerifier, decodeLicense } from "../dist/esm/index.js";

const { keys, vectors } = JSON.parse(
  readFileSync(new URL("../../vectors/vectors.json", import.meta.url), "utf8"),
);

const opts = (v) => {
  const o = { now: v.now };
  if (v.machine_id !== null) o.machineId = v.machine_id;
  if (v.domain !== null) o.domain = v.domain;
  if (v.last_seen !== undefined) o.lastSeen = v.last_seen;
  return o;
};

for (const v of vectors) {
  test(`vector: ${v.name}`, async () => {
    const input = v.public_keys.length === 1 ? v.public_keys[0] : v.public_keys;
    const r = await verifyLicense(v.token, input, opts(v));
    assert.equal(r.valid, v.expected.valid, `valid (got error ${r.error})`);
    assert.equal(r.error, v.expected.error);
  });
}

const byName = Object.fromEntries(vectors.map((v) => [v.name, v]));

test("key map: legacy token without kid verifies against old key", async () => {
  const v = byName.ring_legacy_token_old_key;
  const r = await verifyLicense(v.token, { k2: keys.k2, legacy: keys.k1 }, { now: v.now });
  assert.equal(r.valid, true);
  assert.equal(r.keyId, "legacy");
});

test("key map: token with kid selects its key", async () => {
  const v = byName.ring_kid_token_new_key;
  const r = await verifyLicense(v.token, { legacy: keys.k1, k2: keys.k2 }, { now: v.now });
  assert.equal(r.valid, true);
  assert.equal(r.keyId, "k2");
  assert.equal(r.payload.kid, "k2");
});

test("key map: kid not trusted is rejected", async () => {
  const v = byName.ring_kid_token_new_key;
  const r = await verifyLicense(v.token, { legacy: keys.k1 }, { now: v.now });
  assert.equal(r.error, "ERR_UNKNOWN_KID");
});

test("key map: kid is bound to its key", async () => {
  const v = byName.kid_claim_signed_by_other_key;
  const r = await verifyLicense(v.token, { legacy: keys.k1, k2: keys.k2 }, { now: v.now });
  assert.equal(r.error, "ERR_SIGNATURE_TAMPERED");
  // Arrays carry no names, so every key is tried (v1.0 behaviour).
  assert.equal((await verifyLicense(v.token, [keys.k2, keys.k1], { now: v.now })).valid, true);
});

test("key map: structural error wins over unknown kid", async () => {
  const v = byName.ring_kid_token_new_key;
  const [head, sig] = v.token.split(".");
  const r = await verifyLicense(`${head}.${sig.slice(0, -4)}`, { legacy: keys.k1 }, { now: v.now });
  assert.equal(r.error, "ERR_INVALID_SIGNATURE_LENGTH");
});

test("empty key ring is ERR_INVALID_PUBLIC_KEY", async () => {
  const v = byName.valid_basic;
  for (const k of ["", [], {}]) {
    assert.equal((await verifyLicense(v.token, k, { now: v.now })).error, "ERR_INVALID_PUBLIC_KEY");
  }
});

test("createVerifier reuses keys and merges defaults", async () => {
  const v = byName.machine_ok_case_insensitive;
  const verifier = createVerifier([keys.k2, keys.k1], { machineId: v.machine_id });
  const r = await verifier.verify(v.token, { now: v.now });
  assert.equal(r.valid, true);
  assert.equal(r.keyId, "1");
});

test("decodeLicense returns unverified payload", () => {
  const d = decodeLicense(byName.valid_basic.token);
  assert.equal(d.tier, "PRO");
  assert.equal(d.payload.tier, "pro");
  assert.equal(d.signature.length, 64);
  assert.equal(decodeLicense("nope"), null);
});

test("CommonJS entry point works", async () => {
  const require = createRequire(import.meta.url);
  const cjs = require("../dist/cjs/index.js");
  const v = byName.valid_basic;
  assert.equal((await cjs.verifyLicense(v.token, v.public_keys[0], { now: v.now })).valid, true);
});
