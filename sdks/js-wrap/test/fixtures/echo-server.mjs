// Minimal stdio MCP server: tools "ok", "fail" (isError result) and "boom" (JSON-RPC error).
import { createInterface } from "node:readline";

const out = (m) => process.stdout.write(JSON.stringify(m) + "\n");
createInterface({ input: process.stdin }).on("line", (line) => {
  const m = JSON.parse(line);
  if (Array.isArray(m)) return out(m.map((x) => ({ jsonrpc: "2.0", id: x.id, result: { batched: true } })));
  if (m.method === "initialize") return out({ jsonrpc: "2.0", id: m.id, result: { protocolVersion: "2025-06-18", capabilities: { tools: {} }, serverInfo: { name: "echo", version: "1" } } });
  if (m.method === "tools/list") return out({ jsonrpc: "2.0", id: m.id, result: { tools: [{ name: "ok" }, { name: "fail" }, { name: "boom" }] } });
  if (m.method === "tools/call") {
    const name = m.params.name;
    if (name === "boom") return out({ jsonrpc: "2.0", id: m.id, error: { code: -32000, message: "boom" } });
    return out({ jsonrpc: "2.0", id: m.id, result: { content: [{ type: "text", text: `ran ${name}` }], isError: name === "fail" } });
  }
  if (m.method === "exit") process.exit(3);
  if ("id" in m) out({ jsonrpc: "2.0", id: m.id, result: {} });
});
