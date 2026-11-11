// Minimal stdio MCP server: tools "ok", "fail" (isError result), "boom" (JSON-RPC error), plus test helper "count".
import { createInterface } from "node:readline";

let count = 0;
const out = (m) => process.stdout.write(JSON.stringify(m) + "\n");
createInterface({ input: process.stdin }).on("line", async (line) => {
  const m = JSON.parse(line);
  if (Array.isArray(m)) return out(m.map((x) => ({ jsonrpc: "2.0", id: x.id, result: { batched: true } })));
  if (m.method === "initialize") return out({ jsonrpc: "2.0", id: m.id, result: { protocolVersion: "2025-06-18", capabilities: { tools: {} }, serverInfo: { name: "echo", version: "1" } } });
  if (m.method === "tools/list") return out({ jsonrpc: "2.0", id: m.id, result: { tools: [{ name: "ok" }, { name: "fail" }, { name: "boom" }] } });
  if (m.method === "tools/call") {
    const name = m.params.name;
    const delayMs = Number(m.params?.arguments?.delayMs ?? 0);
    if (delayMs > 0) await new Promise((r) => setTimeout(r, delayMs));
    if (name === "count") return out({ jsonrpc: "2.0", id: m.id, result: { content: [{ type: "text", text: `call:${++count}` }], isError: false } });
    if (name === "boom") return out({ jsonrpc: "2.0", id: m.id, error: { code: -32000, message: "boom" } });
    return out({ jsonrpc: "2.0", id: m.id, result: { content: [{ type: "text", text: `ran ${name}` }], isError: name === "fail" } });
  }
  if (m.method === "exit") process.exit(3);
  if ("id" in m) out({ jsonrpc: "2.0", id: m.id, result: {} });
});
