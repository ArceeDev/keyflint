// `keyflint init`: scaffolds a monetized MCP server (Python or Node) that runs on the first try.
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline/promises";
import { devLicense, generateIssuer } from "./devkey.js";
import { projectFiles } from "./templates.js";

export class UsageError extends Error {}

const NAME_RE = /^[a-z][a-z0-9-]{1,62}[a-z0-9]$/;
const KEY_RE = /^[0-9a-f]{64}$/i;
export const ISSUER_FILE = ".keyflint/dev-issuer.pem";

const FLAGS = { lang: 1, name: 1, title: 1, description: 1, gateway: 1, checkout: 1, github: 1, author: 1, yes: 0, force: 0, help: 0 };

export function parseInitArgs(argv) {
  const opts = { dir: undefined };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-y") { opts.yes = true; continue; }
    if (a === "-h") { opts.help = true; continue; }
    if (!a.startsWith("--")) {
      if (opts.dir !== undefined) throw new UsageError(`unexpected argument: ${a}`);
      opts.dir = a;
      continue;
    }
    const [flag, inline] = a.slice(2).split(/=(.*)/s, 2);
    if (!(flag in FLAGS)) throw new UsageError(`unknown option --${flag}`);
    if (!FLAGS[flag]) { opts[flag] = true; continue; }
    const v = inline ?? argv[++i];
    if (v === undefined || v.startsWith("--")) throw new UsageError(`--${flag} needs a value`);
    opts[flag] = v;
  }
  return opts;
}

/** Parses a gateway key ring ("kid=hex,kid=hex" or a bare hex) into { kid: hex }. */
export function parseKeyring(raw) {
  const out = {};
  String(raw || "").split(",").map((s) => s.trim()).filter(Boolean).forEach((item, i) => {
    const eq = item.lastIndexOf("=");
    const kid = eq > 0 ? item.slice(0, eq).trim() : `k${i + 1}`;
    const hex = (eq > 0 ? item.slice(eq + 1) : item).trim();
    if (!KEY_RE.test(hex)) throw new UsageError(`invalid public key for "${kid}" (expected 64 hex characters)`);
    out[kid] = hex.toLowerCase();
  });
  return out;
}

async function fetchKeyring(gateway, fetchImpl = globalThis.fetch) {
  const url = gateway.replace(/\/+$/, "") + "/api/v1/licenses/public-key";
  const res = await fetchImpl(url, { signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`${url} answered HTTP ${res.status}`);
  const body = await res.json();
  return parseKeyring(body?.data?.keyring ?? body?.data?.public_key ?? "");
}

/** Resolves every answer, asking on a TTY for what flags did not give. */
export async function resolveAnswers(opts, { ask, cwd = process.cwd() } = {}) {
  const dirArg = opts.dir ?? (opts.name || (opts.yes || !ask ? "my-mcp-server" : await ask("Project folder", "my-mcp-server")));
  const target = resolve(cwd, dirArg);
  let name = opts.name ?? basename(target).toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
  if (!opts.name && ask && !opts.yes) name = await ask("Package name", name);
  if (!NAME_RE.test(name)) throw new UsageError(`invalid package name "${name}": use 3-64 lowercase letters, digits and hyphens`);
  let lang = opts.lang ?? (ask && !opts.yes ? await ask("Language (python/node)", "python") : "python");
  lang = { py: "python", python: "python", js: "node", ts: "node", node: "node", javascript: "node" }[String(lang).toLowerCase()];
  if (!lang) throw new UsageError("--lang must be python or node");
  const title = opts.title ?? name.split("-").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
  const description = opts.description ?? (ask && !opts.yes ? await ask("One-line description", `${title}: paid tools for AI agents.`) : `${title}: paid tools for AI agents.`);
  const gatewayUrl = (opts.gateway ?? "").replace(/\/+$/, "");
  if (gatewayUrl && !/^https?:\/\//.test(gatewayUrl)) throw new UsageError("--gateway must be an http(s) URL");
  return {
    target, name, lang, title, description,
    module: name.replace(/-/g, "_"),
    gatewayUrl,
    checkoutUrl: opts.checkout ?? "",
    githubUser: opts.github ?? "your-github-user",
    author: opts.author ?? opts.github ?? "Your Name",
  };
}

function writeTree(root, files) {
  for (const [rel, content] of Object.entries(files)) {
    const p = join(root, rel);
    mkdirSync(dirname(p), { recursive: true });
    writeFileSync(p, content, rel.endsWith(".pem") ? { mode: 0o600 } : undefined);
  }
}

/** Creates the project. Returns { target, files, devLicense, keySource }. */
export async function init(opts, { ask, log = () => {}, fetchImpl } = {}) {
  const c = await resolveAnswers(opts, { ask });
  if (existsSync(c.target) && readdirSync(c.target).length && !opts.force) {
    throw new UsageError(`${c.target} is not empty (use --force to write into it)`);
  }
  let keySource = "dev";
  let lic = "";
  const extra = {};
  if (c.gatewayUrl) {
    try {
      c.publicKeys = await fetchKeyring(c.gatewayUrl, fetchImpl);
      if (!Object.keys(c.publicKeys).length) throw new Error("empty key ring");
      keySource = "gateway";
    } catch (e) {
      log(`warning: could not read the gateway key ring (${e.message}); using a development key instead.`);
    }
  }
  if (keySource === "dev") {
    const issuer = generateIssuer();
    c.publicKeys = { dev: issuer.publicHex };
    lic = devLicense(issuer.privatePem, { subject: `dev@${c.name}` });
    extra[ISSUER_FILE] = issuer.privatePem;
  }
  const files = projectFiles(c);
  const env = files[".env.example"].replace(/^KEYFLINT_LICENSE=$/m, `KEYFLINT_LICENSE=${lic}`);
  writeTree(c.target, { ...files, ...extra, ".env": env });
  return { ...c, files: Object.keys(files), devLicense: lic, keySource };
}

/** Signs a fresh development license with the project's local issuer. */
export function newDevLicense(cwd = process.cwd(), { days = 0, features = ["core"] } = {}) {
  const pem = join(cwd, ISSUER_FILE);
  if (!existsSync(pem)) throw new UsageError(`no ${ISSUER_FILE} here: run this inside a project made by keyflint init`);
  return devLicense(readFileSync(pem, "utf8"), { days, features });
}

export function ttyAsk(input = process.stdin, output = process.stderr) {
  if (!input.isTTY) return undefined;
  const rl = createInterface({ input, output });
  const ask = async (q, def) => ((await rl.question(`${q}${def ? ` (${def})` : ""}: `)).trim() || def);
  ask.close = () => rl.close();
  return ask;
}
