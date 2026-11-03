// Your existing MCP server goes here, unchanged. It knows nothing about KeyFlint:
// @keyflint/wrap (see manifest.json) checks the license and meters credits in front of it.
// This placeholder answers over stdio without dependencies so the template runs as-is.
import { createInterface } from "node:readline";

const out = (m) => process.stdout.write(JSON.stringify(m) + "\n");
const TOOLS = [
  { name: "hello", description: "Says hello.", inputSchema: { type: "object", properties: { name: { type: "string" } } } },
  { name: "summarize", description: "Pretends to summarize text.", inputSchema: { type: "object", properties: { text: { type: "string" } }, required: ["text"] } },
];

createInterface({ input: process.stdin }).on("line", (line) => {
  const m = JSON.parse(line);
  if (!("id" in m)) return; // notifications
  if (m.method === "initialize") {
    return out({ jsonrpc: "2.0", id: m.id, result: { protocolVersion: m.params?.protocolVersion ?? "2025-06-18", capabilities: { tools: {} }, serverInfo: { name: "my-paid-mcp-server", version: "1.0.0" } } });
  }
  if (m.method === "tools/list") return out({ jsonrpc: "2.0", id: m.id, result: { tools: TOOLS } });
  if (m.method === "tools/call") {
    const a = m.params?.arguments ?? {};
    const text = m.params?.name === "hello" ? `Hello, ${a.name ?? "world"}!` : `Summary: ${String(a.text ?? "").slice(0, 80)}`;
    return out({ jsonrpc: "2.0", id: m.id, result: { content: [{ type: "text", text }] } });
  }
  out({ jsonrpc: "2.0", id: m.id, error: { code: -32601, message: "Method not found" } });
});
