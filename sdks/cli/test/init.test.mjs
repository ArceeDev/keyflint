import { test } from "node:test";
import assert from "node:assert/strict";
import { createPublicKey, verify } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { canonicalJson, devLicense, generateIssuer, publicHexFromPem, signLicense } from "../src/devkey.js";
import { init, newDevLicense, parseInitArgs, parseKeyring, UsageError } from "../src/init.js";

const tmp = () => mkdtempSync(join(tmpdir(), "kf-cli-"));
const decode = (token) => {
  const [head, sig] = token.split(".");
  const [, tier, body] = head.split(/-(.*)/s)[1].match(/^([^-]+)-(.*)$/s);
  return { tier, bytes: Buffer.from(body, "base64url"), sig: Buffer.from(sig, "base64url") };
};
const spki = (hex) =>
  createPublicKey({ key: Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), Buffer.from(hex, "hex")]), format: "der", type: "spki" });

test("canonicalJson matches Python json.dumps(sort_keys, compact, ensure_ascii)", () => {
  assert.equal(canonicalJson({ b: 1, a: [true, null, "x"] }), '{"a":[true,null,"x"],"b":1}');
  assert.equal(canonicalJson({ s: "año €" }), '{"s":"a\\u00f1o \\u20ac"}');
  assert.throws(() => canonicalJson({ f: 1.5 }), TypeError);
});

test("signed licenses verify with the issuer public key", () => {
  const { privatePem, publicHex } = generateIssuer();
  assert.match(publicHex, /^[0-9a-f]{64}$/);
  assert.equal(publicHexFromPem(privatePem), publicHex);
  const token = devLicense(privatePem, { now: 1_700_000_000_000 });
  assert.match(token, /^LIC-DEV-[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);
  const { tier, bytes, sig } = decode(token);
  assert.equal(tier, "DEV");
  const payload = JSON.parse(bytes);
  assert.equal(payload.tier, "dev");
  assert.equal(payload.kid, "dev");
  assert.equal(payload.issued_at, 1_700_000_000);
  assert.equal(payload.expires_at, undefined);
  assert.ok(verify(null, bytes, spki(publicHex), sig));
  assert.equal(bytes.toString(), canonicalJson(payload));
  assert.throws(() => signLicense(privatePem, { tier: "a-b" }), TypeError);
  const expiring = JSON.parse(decode(devLicense(privatePem, { days: 2, now: 0 })).bytes);
  assert.equal(expiring.expires_at, 2 * 86400);
});

test("parseInitArgs", () => {
  assert.deepEqual(parseInitArgs(["app", "--lang=node", "--name", "my-app", "-y"]), { dir: "app", lang: "node", name: "my-app", yes: true });
  assert.throws(() => parseInitArgs(["--nope"]), UsageError);
  assert.throws(() => parseInitArgs(["--lang"]), UsageError);
  assert.throws(() => parseInitArgs(["a", "b"]), UsageError);
});

test("parseKeyring", () => {
  const k = "ab".repeat(32);
  assert.deepEqual(parseKeyring(`k1=${k}, k2=${k.toUpperCase()}`), { k1: k, k2: k });
  assert.deepEqual(parseKeyring(k), { k1: k });
  assert.throws(() => parseKeyring("k1=xyz"), UsageError);
});

for (const lang of ["python", "node"]) {
  test(`init --lang ${lang} writes a runnable project with a dev license`, async () => {
    const cwd = tmp();
    const r = await init({ dir: join(cwd, "acme-tools"), lang, yes: true, github: "acme" });
    assert.equal(r.name, "acme-tools");
    assert.equal(r.keySource, "dev");
    const root = r.target;
    const env = readFileSync(join(root, ".env"), "utf8");
    assert.match(env, /^KEYFLINT_LICENSE=LIC-DEV-/m);
    assert.ok(readFileSync(join(root, ".gitignore"), "utf8").includes(".keyflint/"));
    const pem = join(root, ".keyflint/dev-issuer.pem");
    if (process.platform !== "win32") assert.equal(statSync(pem).mode & 0o777, 0o600);
    const lic = env.match(/^KEYFLINT_LICENSE=(.*)$/m)[1];
    const { bytes, sig } = decode(lic);
    const licensing = readFileSync(join(root, lang === "python" ? "src/acme_tools/licensing.py" : "src/licensing.js"), "utf8");
    const hex = licensing.match(/"dev":"([0-9a-f]{64})"/)[1];
    assert.ok(verify(null, bytes, spki(hex), sig), "dev license must verify with the compiled-in key");
    const server = JSON.parse(readFileSync(join(root, "server.json"), "utf8"));
    assert.equal(server.name, "io.github.acme/acme-tools");
    assert.equal(server.packages[0].registryType, lang === "python" ? "pypi" : "npm");
    const manifest = JSON.parse(readFileSync(join(root, "manifest.json"), "utf8"));
    assert.equal(manifest.server.mcp_config.env.KEYFLINT_LICENSE, "${user_config.license_key}");
    if (lang === "node") {
      const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
      assert.equal(pkg.bin["acme-tools"], "src/index.js");
      assert.equal(pkg.mcpName, server.name);
    } else {
      assert.ok(existsSync(join(root, "tests/test_server.py")));
    }
    assert.match(newDevLicense(root, { days: 1 }), /^LIC-DEV-/);
  });
}

test("init refuses a non-empty folder and bad names", async () => {
  const cwd = tmp();
  writeFileSync(join(cwd, "keep.txt"), "x");
  await assert.rejects(init({ dir: cwd, name: "ok-name", yes: true }), /not empty/);
  await assert.rejects(init({ dir: join(cwd, "x"), name: "Bad_Name", yes: true }), /invalid package name/);
  await assert.rejects(init({ dir: join(cwd, "yy-tools"), lang: "ruby", yes: true }), /--lang/);
});

test("init --gateway trusts the gateway key ring and writes no dev issuer", async () => {
  const cwd = tmp();
  const k = "cd".repeat(32);
  const fetchImpl = async (url) => {
    assert.equal(url, "https://gw.example.com/api/v1/licenses/public-key");
    return { ok: true, json: async () => ({ data: { keyring: `k7=${k}` } }) };
  };
  const r = await init({ dir: join(cwd, "gw-tools"), yes: true, gateway: "https://gw.example.com/" }, { fetchImpl });
  assert.equal(r.keySource, "gateway");
  assert.equal(r.devLicense, "");
  assert.ok(!existsSync(join(r.target, ".keyflint/dev-issuer.pem")));
  assert.match(readFileSync(join(r.target, "src/gw_tools/licensing.py"), "utf8"), new RegExp(`"k7":"${k}"`));
  assert.match(readFileSync(join(r.target, ".env"), "utf8"), /^KEYFLINT_URL=https:\/\/gw\.example\.com$/m);
});

test("init falls back to a dev key when the gateway is unreachable", async () => {
  const logs = [];
  const r = await init(
    { dir: join(tmp(), "fb"), name: "fb-tools", yes: true, gateway: "https://down.example.com" },
    { fetchImpl: async () => { throw new Error("offline"); }, log: (m) => logs.push(m) },
  );
  assert.equal(r.keySource, "dev");
  assert.match(logs.join(), /offline/);
});
