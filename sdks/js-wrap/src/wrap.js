/**
 * @keyflint/wrap — puts KeyFlint license checks and credit metering in front of any stdio MCP server.
 *
 *   npx @keyflint/wrap --tool summarize=5 -- python server.py
 *
 * The wrapper spawns the server, relays newline-delimited JSON-RPC in both directions, and gates
 * every `tools/call` request: offline license check, then POST /api/v1/quota/deduct for metered
 * tools. Failures are answered by the wrapper with the KeyFlint JSON-RPC errors (-32060..-32063)
 * and never reach the server. Calls the server answers with an error (or `isError: true`) are
 * refunded. Every other message passes through untouched.
 */

import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { createKeyFlint, KeyFlintMcpError } from "keyflint-verify/mcp";

const INTERNAL_ERROR = -32603;

/** Parses argv (without node and script) into wrapper options and the server command. */
export function parseArgs(argv, env = process.env) {
  const sep = argv.indexOf("--");
  if (sep === -1 || sep === argv.length - 1) throw new UsageError("missing server command after --");
  const flags = argv.slice(0, sep);
  const opts = {
    command: argv[sep + 1],
    args: argv.slice(sep + 2),
    defaultCredits: undefined,
    tools: new Map(),
    free: new Set(),
    features: [],
    offlineGraceCalls: 0,
    eventType: undefined,
  };
  const value = (i, name) => {
    if (i + 1 >= flags.length) throw new UsageError(`${name} needs a value`);
    return flags[i + 1];
  };
  for (let i = 0; i < flags.length; i++) {
    const f = flags[i];
    if (f === "--credits") opts.defaultCredits = credits(value(i++, f), f);
    else if (f === "--tool") {
      const raw = value(i++, f);
      const eq = raw.lastIndexOf("=");
      if (eq <= 0) throw new UsageError(`--tool expects name=credits, got "${raw}"`);
      opts.tools.set(raw.slice(0, eq), credits(raw.slice(eq + 1), f));
    } else if (f === "--free") for (const t of list(value(i++, f))) opts.free.add(t);
    else if (f === "--features") opts.features.push(...list(value(i++, f)));
    else if (f === "--offline-grace") {
      opts.offlineGraceCalls = credits(value(i++, f), f);
      if (opts.offlineGraceCalls > 5) throw new UsageError("--offline-grace is capped at 5");
    }
    else if (f === "--event-type") opts.eventType = value(i++, f);
    else throw new UsageError(`unknown option ${f}`);
  }
  // Without a gateway nothing can be deducted, so the default is a license-only check.
  if (opts.defaultCredits === undefined) opts.defaultCredits = gatewayConfigured(env) ? 1 : 0;
  return opts;
}

export class UsageError extends Error {}

function credits(raw, flag) {
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 0) throw new UsageError(`${flag}: "${raw}" is not a non-negative integer`);
  return n;
}

function list(raw) {
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

function gatewayConfigured(env) {
  return Boolean((env.KEYFLINT_URL ?? env.KEYFORGE_URL ?? "").trim());
}

/**
 * Starts the server and relays messages. Resolves with the server's exit code.
 * `io` lets tests swap stdin/stdout; `kf` lets tests inject a configured KeyFlint instance.
 */
export function wrap(opts, io = {}) {
  const input = io.stdin ?? process.stdin;
  const output = io.stdout ?? process.stdout;
  const kf = io.kf ?? createKeyFlint();
  const child = spawn(opts.command, opts.args, {
    stdio: ["pipe", "pipe", "inherit"],
    env: io.env ?? process.env,
    shell: false,
  });

  const waiting = new Map(); // JSON-RPC id (as JSON) -> resolve(response)
  const gates = new Map(); // tool name -> gated forwarder
  let childGone = false;
  if (io.forwardSignals) {
    for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(sig, () => child.kill(sig));
  }

  const send = (msg) => output.write(JSON.stringify(msg) + "\n");
  const toChild = (line) => {
    if (!childGone) child.stdin.write(line + "\n");
  };

  function gateFor(name) {
    let gate = gates.get(name);
    if (gate) return gate;
    const forward = async (msg) => {
      const response = await new Promise((resolve, reject) => {
        if (childGone) return reject(new Error("MCP server exited"));
        waiting.set(JSON.stringify(msg.id), resolve);
        toChild(JSON.stringify(msg));
      });
      // Refund (metered) when the server reports a failure; the response is relayed as-is.
      return { isError: Boolean(response.error || response.result?.isError === true), response };
    };
    const n = opts.tools.get(name) ?? opts.defaultCredits;
    if (n === 0) gate = kf.requireLicense(forward, { features: opts.features });
    else {
      const m = { features: opts.features, offlineGraceCalls: opts.offlineGraceCalls };
      m.eventType = opts.eventType ?? `mcp:${name}`;
      gate = kf.metered(n, forward, m);
    }
    gates.set(name, gate);
    return gate;
  }

  async function handleToolCall(msg) {
    const name = typeof msg.params?.name === "string" ? msg.params.name : "";
    if (opts.free.has(name)) return toChild(JSON.stringify(msg));
    try {
      const { response } = await gateFor(name)(msg);
      output.write(response.__raw + "\n");
    } catch (e) {
      if (e instanceof KeyFlintMcpError || (e && typeof e.code === "number" && e.data)) {
        send({ jsonrpc: "2.0", id: msg.id, error: { code: e.code, message: e.message, data: e.data } });
      } else {
        send({ jsonrpc: "2.0", id: msg.id, error: { code: INTERNAL_ERROR, message: String(e?.message ?? e) } });
      }
    }
  }

  // client -> server
  const fromClient = createInterface({ input, crlfDelay: Infinity });
  fromClient.on("line", (line) => {
    if (!line.trim()) return;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return toChild(line); // not ours to judge; the server answers parse errors
    }
    if (Array.isArray(msg)) {
      // JSON-RPC batches (dropped in MCP 2025-06-18): never let a tools/call through ungated.
      const calls = msg.filter(isToolCall);
      const rest = msg.filter((m) => !isToolCall(m));
      if (calls.length) {
        send(calls.map((m) => ({ jsonrpc: "2.0", id: m.id, error: { code: INTERNAL_ERROR, message: "keyflint-wrap: batched tools/call is not supported" } })));
      }
      if (rest.length) toChild(JSON.stringify(rest));
      return;
    }
    if (isToolCall(msg)) handleToolCall(msg);
    else toChild(line);
  });
  fromClient.on("close", () => {
    if (!childGone) child.stdin.end();
  });

  // server -> client
  const fromServer = createInterface({ input: child.stdout, crlfDelay: Infinity });
  fromServer.on("line", (line) => {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return output.write(line + "\n");
    }
    const key = msg && !Array.isArray(msg) && "id" in msg && !("method" in msg) ? JSON.stringify(msg.id) : undefined;
    const resolve = key !== undefined ? waiting.get(key) : undefined;
    if (resolve) {
      waiting.delete(key);
      Object.defineProperty(msg, "__raw", { value: line, enumerable: false });
      resolve(msg);
    } else output.write(line + "\n");
  });

  return new Promise((resolve) => {
    const finish = (code) => {
      if (childGone) return;
      childGone = true;
      for (const [id, done] of waiting) {
        const msg = { jsonrpc: "2.0", id: JSON.parse(id), error: { code: INTERNAL_ERROR, message: "MCP server exited" } };
        done(Object.defineProperty(msg, "__raw", { value: JSON.stringify(msg) }));
      }
      waiting.clear();
      resolve(code);
    };
    child.on("error", (e) => {
      process.stderr.write(`keyflint-wrap: cannot start ${opts.command}: ${e.message}\n`);
      finish(127);
    });
    child.on("exit", (code, signal) => finish(code ?? (signal ? 128 : 1)));
  });
}

function isToolCall(m) {
  return m && typeof m === "object" && m.method === "tools/call" && "id" in m;
}
