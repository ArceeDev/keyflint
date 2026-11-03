import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { activate, ActivateError, configPath, main } from "../dist/esm/cli.js";

const { vectors } = JSON.parse(readFileSync(new URL("../../vectors/vectors.json", import.meta.url), "utf8"));
const TOKEN = vectors.find((v) => v.name === "valid_perpetual").token;

function withFile(obj, fn) {
  const dir = mkdtempSync(join(tmpdir(), "kf-cli-"));
  const f = join(dir, "claude_desktop_config.json");
  writeFileSync(f, typeof obj === "string" ? obj : JSON.stringify(obj));
  return Promise.resolve(fn(f)).finally(() => rmSync(dir, { recursive: true, force: true }));
}

test("single server gets the license, a .bak is kept", () =>
  withFile({ mcpServers: { weather: { command: "npx" } }, other: 1 }, async (f) => {
    assert.deepEqual(await activate(TOKEN, f), ["weather"]);
    const cfg = JSON.parse(readFileSync(f, "utf8"));
    assert.deepEqual(cfg.mcpServers.weather.env, { KEYFLINT_LICENSE: TOKEN });
    assert.equal(cfg.other, 1);
    assert.deepEqual(JSON.parse(readFileSync(`${f}.bak`, "utf8")).mcpServers.weather, { command: "npx" });
  }));

test("prefers servers already using KeyFlint; ambiguity needs --server", () =>
  withFile({ mcpServers: { a: { command: "x" }, b: { command: "y" } } }, async (f) => {
    await assert.rejects(activate(TOKEN, f), (e) => e instanceof ActivateError && /--server/.test(e.message));
    assert.deepEqual(await activate(TOKEN, f, { server: "b" }), ["b"]);
    assert.deepEqual(await activate(TOKEN, f), ["b"]); // now b uses KEYFLINT_LICENSE
  }));

test("invalid JSON is never touched", () =>
  withFile('{"mcpServers": {"a": ,}}', async (f) => {
    await assert.rejects(activate(TOKEN, f), ActivateError);
    assert.equal(readFileSync(f, "utf8"), '{"mcpServers": {"a": ,}}');
    assert.equal(existsSync(`${f}.bak`), false);
  }));

test("main: dry run, bad token, and the bin entry", () =>
  withFile({ mcpServers: { a: { command: "x" } } }, async (f) => {
    assert.equal(await main(["activate", TOKEN, "--config", f, "--dry-run"]), 0);
    assert.equal(JSON.parse(readFileSync(f, "utf8")).mcpServers.a.env, undefined);
    assert.equal(await main(["activate", "nope", "--config", f]), 2);
    const bin = fileURLToPath(new URL("../dist/esm/cli.js", import.meta.url));
    const out = execFileSync(process.execPath, [bin, "activate", TOKEN, "--config", f], { encoding: "utf8" });
    assert.match(out, /Updated custom/);
    assert.equal(JSON.parse(readFileSync(f, "utf8")).mcpServers.a.env.KEYFLINT_LICENSE, TOKEN);
  }));

test("config paths per OS", () => {
  const j = (...p) => p.join("/");
  assert.equal(configPath("claude", "darwin", "/h", {}, j), "/h/Library/Application Support/Claude/claude_desktop_config.json");
  assert.equal(configPath("claude", "win32", "/h", { APPDATA: "C:/A" }, j), "C:/A/Claude/claude_desktop_config.json");
  assert.equal(configPath("cursor", "linux", "/h", {}, j), "/h/.cursor/mcp.json");
  assert.equal(configPath("windsurf", "linux", "/h", {}, j), "/h/.codeium/windsurf/mcp_config.json");
});
