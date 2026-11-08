import { test } from "node:test";
import assert from "node:assert/strict";
import { buildLinks, formatLinks, parseLinksArgs } from "../src/links.js";
import { UsageError } from "../src/init.js";

const by = (links) => Object.fromEntries(links.map((l) => [l.id, l]));
const cursorCfg = (href) => JSON.parse(Buffer.from(decodeURIComponent(new URL(href).searchParams.get("config") ?? href.split("config=")[1]), "base64").toString());

test("remote server: deeplinks carry only the URL (OAuth on connect)", () => {
  const l = by(buildLinks({ name: "demo", url: "https://mcp.example.com/demo/mcp" }));
  assert.equal(l.cursor.href, "cursor://anysphere.cursor-deeplink/mcp/install?name=demo&config=eyJ1cmwiOiJodHRwczovL21jcC5leGFtcGxlLmNvbS9kZW1vL21jcCJ9");
  assert.deepEqual(cursorCfg(l.cursor.web), { url: "https://mcp.example.com/demo/mcp" });
  assert.equal(l.vscode.href, "vscode:mcp/install?" + encodeURIComponent('{"name":"demo","type":"http","url":"https://mcp.example.com/demo/mcp"}'));
  // https badge target: the vscode: link URL-encoded once more (double encoding of the JSON)
  assert.equal(new URL(l.vscode.web).searchParams.get("url"), l.vscode.href);
  assert.ok(l["vscode-insiders"].href.startsWith("vscode-insiders:mcp/install?"));
  assert.equal(new URL(l.kiro.href).searchParams.get("config"), '{"url":"https://mcp.example.com/demo/mcp"}');
  assert.deepEqual(cursorCfg(l.lmstudio.href.replace("lmstudio://add_mcp", "x://y")), { url: "https://mcp.example.com/demo/mcp" });
  assert.equal(l.goose.href, "goose://extension?url=https%3A%2F%2Fmcp.example.com%2Fdemo%2Fmcp&type=streamable_http&id=demo&name=demo&description=demo%20MCP%20server");
  assert.equal(l["claude-code"].command, "claude mcp add --transport http --scope user demo https://mcp.example.com/demo/mcp");
  assert.equal(l.codex.command, "codex mcp add demo --url https://mcp.example.com/demo/mcp\ncodex mcp login demo");
  assert.ok(l.chatgpt && l.claude);
});

test("remote server with a static header", () => {
  const l = by(buildLinks({ name: "demo", url: "https://x.dev/mcp", headers: { Authorization: "Bearer <KEY>" } }));
  assert.deepEqual(cursorCfg(l.cursor.web), { url: "https://x.dev/mcp", headers: { Authorization: "Bearer <KEY>" } });
  assert.equal(l["claude-code"].command, "claude mcp add --transport http --scope user demo https://x.dev/mcp --header 'Authorization: Bearer <KEY>'");
  assert.equal(l.chatgpt, undefined, "ChatGPT has no static headers");
  assert.ok(!l.codex.command.includes("login"));
});

test("local packages", () => {
  const py = by(buildLinks({ name: "acme", pypi: "acme-mcp", env: ["KEYFLINT_LICENSE"] }));
  assert.deepEqual(cursorCfg(py.cursor.web), { command: "uvx", args: ["acme-mcp"], env: { KEYFLINT_LICENSE: "<KEYFLINT_LICENSE>" } });
  assert.equal(py.goose.href, "goose://extension?cmd=uvx&arg=acme-mcp&id=acme&name=acme&description=acme%20MCP%20server");
  assert.equal(py["claude-code"].command, "claude mcp add --scope user -e KEYFLINT_LICENSE=<KEYFLINT_LICENSE> acme -- uvx acme-mcp");
  assert.equal(py.claude, undefined);
  const js = by(buildLinks({ name: "acme", npm: "@acme/mcp" }));
  assert.equal(js.goose.href, "goose://extension?cmd=npx&arg=-y&arg=%40acme%2Fmcp&id=acme&name=acme&description=acme%20MCP%20server");
  assert.match(js.gemini.config, /"npx"/);
});

test("validation", () => {
  assert.throws(() => buildLinks({ url: "https://x" }), UsageError);
  assert.throws(() => buildLinks({ name: "a", url: "https://x", pypi: "p" }), UsageError);
  assert.throws(() => buildLinks({ name: "a", url: "http://x.com/mcp" }), UsageError);
  assert.doesNotThrow(() => buildLinks({ name: "a", url: "http://localhost:8000/mcp" }));
  assert.throws(() => buildLinks({ name: "a", pypi: "p", env: ["bad-name"] }), UsageError);
  assert.throws(() => parseLinksArgs(["--header", "nocolon"]), UsageError);
  assert.deepEqual(parseLinksArgs(["--name", "a", "--url", "https://x", "--header", "X-Key: 1", "--format", "json"]),
    { headers: { "X-Key": "1" }, env: [], format: "json", name: "a", url: "https://x" });
});

test("formats", () => {
  const links = buildLinks({ name: "demo", url: "https://x.dev/mcp" });
  const md = formatLinks(links, "markdown");
  assert.match(md, /\[!\[Add to Cursor\]\(https:\/\/cursor\.com\/deeplink\/mcp-install-dark\.svg\)\]\(https:\/\/cursor\.com\/en\/install-mcp\?/);
  assert.match(md, /```bash\nclaude mcp add/);
  assert.equal(JSON.parse(formatLinks(links, "json")).length, links.length);
  assert.match(formatLinks(links), /^Cursor:\n  cursor:\/\//);
  assert.throws(() => formatLinks(links, "xml"), UsageError);
});
