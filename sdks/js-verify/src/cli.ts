#!/usr/bin/env node
/**
 * `npx keyflint-verify activate <TOKEN> [--client claude|cursor|windsurf|all] [--server NAME]
 *  [--config PATH] [--dry-run]`
 *
 * Puts a KeyFlint license into an MCP client's config without hand-editing JSON: finds the file
 * for this OS, writes a `.bak` copy, sets `env.KEYFLINT_LICENSE` on the target server(s) and
 * re-reads the result. Targets: --server NAME; else servers already using KeyFlint variables;
 * else the only server. Same behaviour as `uvx keyflint-verify activate`.
 */

import { verifyLicense } from "./index.js";
import { parseKeysEnv } from "./mcp.js";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

const TOKEN_RE = /^LIC-[A-Za-z]+-[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
const KEYFLINT_VARS = ["KEYFLINT_LICENSE", "KEYFLINT_PUBLIC_KEYS", "KEYFLINT_PUBLIC_KEY", "KEYFLINT_URL", "KEYFORGE_LICENSE"];
export const CLIENTS = ["claude", "cursor", "windsurf"] as const;

const proc = (globalThis as Any).process;
const nodeImport = (name: string): Promise<Any> => import(name);

export class ActivateError extends Error {}

export function configPath(client: string, platform: string, home: string, env: Record<string, string | undefined>, join: (...p: string[]) => string): string {
  if (client === "claude") {
    if (platform === "darwin") return join(home, "Library", "Application Support", "Claude", "claude_desktop_config.json");
    if (platform === "win32") return join(env.APPDATA || join(home, "AppData", "Roaming"), "Claude", "claude_desktop_config.json");
    return join(env.XDG_CONFIG_HOME || join(home, ".config"), "Claude", "claude_desktop_config.json");
  }
  if (client === "cursor") return join(home, ".cursor", "mcp.json");
  if (client === "windsurf") return join(home, ".codeium", "windsurf", "mcp_config.json");
  throw new Error(`unknown client ${client}`);
}

export function pickServers(servers: Record<string, unknown>, wanted?: string): string[] {
  if (wanted) return wanted in servers ? [wanted] : [];
  const using = Object.entries(servers)
    .filter(([, c]) => c && typeof c === "object" && KEYFLINT_VARS.some((k) => k in (((c as Any).env ?? {}) as object)))
    .map(([n]) => n);
  if (using.length) return using;
  const names = Object.keys(servers);
  return names.length === 1 ? names : [];
}

/** Returns the updated server names. Throws ActivateError without touching the file on failure. */
export async function activate(token: string, path: string, opts: { server?: string; dryRun?: boolean } = {}): Promise<string[]> {
  const fs: Any = await nodeImport("node:fs");
  if (!fs.existsSync(path)) throw new ActivateError(`${path} not found. Add your MCP server to the client first, then run this again.`);
  const raw = String(fs.readFileSync(path, "utf8")).replace(/^﻿/, "");
  let config: Any;
  try {
    config = raw.trim() ? JSON.parse(raw) : {};
  } catch (e) {
    throw new ActivateError(`${path} is not valid JSON (${(e as Error).message}); nothing was changed.`);
  }
  if (!config || typeof config !== "object" || Array.isArray(config)) {
    throw new ActivateError(`${path} does not contain a JSON object; nothing was changed.`);
  }
  const servers = config.mcpServers;
  if (!servers || typeof servers !== "object" || !Object.keys(servers).length) {
    throw new ActivateError(`${path} has no "mcpServers". Add your MCP server first, then run this again.`);
  }
  const targets = pickServers(servers, opts.server);
  if (!targets.length) {
    const names = Object.keys(servers).sort().join(", ");
    const hint = opts.server ? `No server named '${opts.server}'.` : "Several MCP servers found.";
    throw new ActivateError(`${hint} Choose one with --server NAME (available: ${names}).`);
  }
  for (const name of targets) {
    const cfg = servers[name];
    if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) throw new ActivateError(`Server '${name}' is not a JSON object; nothing was changed.`);
    if (cfg.env !== undefined && (typeof cfg.env !== "object" || cfg.env === null || Array.isArray(cfg.env))) {
      throw new ActivateError(`Server '${name}' has a non-object "env"; nothing was changed.`);
    }
    const env = { ...(cfg.env ?? {}), KEYFLINT_LICENSE: token };
    delete env.KEYFORGE_LICENSE;
    cfg.env = env;
  }
  const out = JSON.stringify(config, null, 2) + "\n";
  JSON.parse(out);
  if (!opts.dryRun) {
    fs.copyFileSync(path, `${path}.bak`);
    const tmp = `${path}.keyflint-tmp`;
    fs.writeFileSync(tmp, out, "utf8");
    fs.renameSync(tmp, path);
    JSON.parse(fs.readFileSync(path, "utf8"));
  }
  return targets;
}

const color = (t: string, c: string): string => (proc?.stdout?.isTTY && !proc?.env?.NO_COLOR ? `\u001b[${c}m${t}\u001b[0m` : t);

const USAGE = `Usage: keyflint-verify activate <LIC-...> [--client claude|cursor|windsurf|all] [--server NAME] [--config PATH] [--dry-run]`;

export async function main(argv: string[]): Promise<number> {
  const [cmd, ...rest] = argv;
  if (cmd === "--version" || cmd === "-v") {
    console.log("keyflint-verify 1.1.0");
    return 0;
  }
  if (cmd !== "activate") {
    console.error(USAGE);
    return cmd === undefined || cmd === "--help" || cmd === "-h" ? 0 : 2;
  }
  let token: string | undefined;
  let client = "all";
  let server: string | undefined;
  let config: string | undefined;
  let dryRun = false;
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i] as string;
    const val = (): string => {
      const v = rest[++i];
      if (v === undefined) throw new ActivateError(`${a} needs a value`);
      return v;
    };
    if (a === "--client") client = val();
    else if (a === "--server") server = val();
    else if (a === "--config") config = val();
    else if (a === "--dry-run") dryRun = true;
    else if (!a.startsWith("--") && token === undefined) token = a.trim();
    else {
      console.error(USAGE);
      return 2;
    }
  }
  if (!token || !TOKEN_RE.test(token)) {
    console.error(color("✗ That does not look like a KeyFlint license (expected LIC-<TIER>-...).", "31"));
    return 2;
  }
  if (client !== "all" && !(CLIENTS as readonly string[]).includes(client)) {
    console.error(USAGE);
    return 2;
  }
  const fs: Any = await nodeImport("node:fs");
  const os: Any = await nodeImport("node:os");
  const path: Any = await nodeImport("node:path");
  let paths: [string, string][];
  if (config) paths = [["custom", config]];
  else {
    const list = client === "all" ? [...CLIENTS] : [client];
    paths = list.map((c) => [c, configPath(c, proc.platform, os.homedir(), proc.env, path.join)]);
    if (client === "all") {
      paths = paths.filter(([, p]) => fs.existsSync(p));
      if (!paths.length) {
        console.error(color("✗ No Claude Desktop, Cursor or Windsurf MCP config found. Use --client or --config.", "31"));
        return 1;
      }
    }
  }
  let updated = 0;
  const errors: string[] = [];
  for (const [name, p] of paths) {
    let servers: string[];
    try {
      servers = await activate(token, p, { ...(server ? { server } : {}), dryRun });
    } catch (e) {
      if (!(e instanceof ActivateError)) throw e;
      errors.push(`${name}: ${e.message}`);
      continue;
    }
    updated++;
    console.log(color(`✓ ${dryRun ? "Would update" : "Updated"} ${name} (${p}): ${servers.join(", ")}`, "32"));
    const cfg = JSON.parse(fs.readFileSync(p, "utf8")).mcpServers ?? {};
    for (const s of servers) {
      const keys = cfg[s]?.env?.KEYFLINT_PUBLIC_KEYS ?? cfg[s]?.env?.KEYFLINT_PUBLIC_KEY;
      if (typeof keys === "string" && keys.trim()) {
        const r = await verifyLicense(token, parseKeysEnv(keys));
        if (!r.valid && r.error !== "ERR_NODE_LOCK_VIOLATION" && r.error !== "ERR_DOMAIN_LOCK_VIOLATION") {
          console.log(color(`! Warning: this license does not verify against ${s}'s public key (${r.error})`, "33"));
        }
      }
    }
  }
  for (const e of errors) console.error(color(`✗ ${e}`, "31"));
  if (updated && !dryRun) console.log(color("Done. Restart the app so it picks up the license. A .bak copy of each file was kept.", "32"));
  return updated ? 0 : 1;
}

// Run when executed as a script (bin), not when imported by tests.
const argv1: string | undefined = proc?.argv?.[1];
if (argv1 && /keyflint-verify|cli\.js$/.test(argv1)) {
  main(proc.argv.slice(2)).then(
    (code) => proc.exit(code),
    (e: unknown) => {
      console.error(color(`✗ ${(e as Error).message ?? e}`, "31"));
      proc.exit(1);
    },
  );
}
