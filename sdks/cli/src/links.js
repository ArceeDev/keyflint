// `keyflint links`: one-click install links, README badges and copy-paste commands for every
// major MCP client. Formats follow each client's docs and the READMEs of widely used servers
// (Playwright, GitHub, Semgrep) as of late 2026; clients without a deeplink get a command.
import { UsageError } from "./init.js";

const enc = encodeURIComponent;
const b64 = (obj) => Buffer.from(JSON.stringify(obj), "utf8").toString("base64");
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const ENV_RE = /^[A-Z_][A-Z0-9_]*$/;
const shellQuote = (s) => (/^[\w@%+=:,./-]+$/.test(s) ? s : `'${String(s).replace(/'/g, `'\\''`)}'`);

export function parseLinksArgs(argv) {
  const o = { headers: {}, env: [], format: "text" };
  const take = (i, flag) => {
    const v = argv[i + 1];
    if (v === undefined || v.startsWith("--")) throw new UsageError(`${flag} needs a value`);
    return v;
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case "--name": o.name = take(i++, a); break;
      case "--url": o.url = take(i++, a); break;
      case "--pypi": o.pypi = take(i++, a); break;
      case "--npm": o.npm = take(i++, a); break;
      case "--title": o.title = take(i++, a); break;
      case "--description": o.description = take(i++, a); break;
      case "--format": o.format = take(i++, a); break;
      case "--env": o.env.push(take(i++, a)); break;
      case "--header": {
        const h = take(i++, a);
        const at = h.indexOf(":");
        if (at < 1) throw new UsageError(`--header must look like "Name: value", got "${h}"`);
        o.headers[h.slice(0, at).trim()] = h.slice(at + 1).trim();
        break;
      }
      default: throw new UsageError(`unknown option ${a}`);
    }
  }
  return o;
}

/** Returns [{ id, client, href?, badge?, command?, config?, note? }] for a remote URL or a local package. */
export function buildLinks({ name, url, pypi, npm, headers = {}, env = [], title, description } = {}) {
  if (!name || !NAME_RE.test(name)) throw new UsageError("--name is required (letters, digits, . _ -)");
  if ([url, pypi, npm].filter(Boolean).length !== 1) throw new UsageError("give exactly one of --url, --pypi or --npm");
  if (url && !/^https:\/\/[^\s]+$/.test(url) && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(url)) {
    throw new UsageError("--url must be https:// (or http://localhost for testing)");
  }
  for (const v of env) if (!ENV_RE.test(v)) throw new UsageError(`--env expects a variable name like KEYFLINT_LICENSE, got "${v}"`);
  const label = title || name;
  const about = description || `${label} MCP server`;
  const hasHeaders = Object.keys(headers).length > 0;
  const placeholderEnv = Object.fromEntries(env.map((v) => [v, `<${v}>`]));

  // Inner server object shared by Cursor, LM Studio and Kiro (same shape as mcp.json).
  const local = pypi ? { command: "uvx", args: [pypi] } : npm ? { command: "npx", args: ["-y", npm] } : null;
  const server = url
    ? { url, ...(hasHeaders ? { headers } : {}) }
    : { ...local, ...(env.length ? { env: placeholderEnv } : {}) };
  const vscodeServer = url
    ? { name, type: "http", url, ...(hasHeaders ? { headers } : {}) }
    : { name, type: "stdio", ...local, ...(env.length ? { env: placeholderEnv } : {}) };

  const vsInstall = (scheme) => `${scheme}:mcp/install?${enc(JSON.stringify(vscodeServer))}`;
  const out = [];
  const cursorCfg = enc(b64(server));
  out.push({
    id: "cursor", client: "Cursor",
    href: `cursor://anysphere.cursor-deeplink/mcp/install?name=${enc(name)}&config=${cursorCfg}`,
    web: `https://cursor.com/en/install-mcp?name=${enc(name)}&config=${cursorCfg}`,
    badge: "https://cursor.com/deeplink/mcp-install-dark.svg",
  });
  out.push({
    id: "vscode", client: "VS Code",
    href: vsInstall("vscode"),
    web: `https://insiders.vscode.dev/redirect?url=${enc(vsInstall("vscode"))}`,
    badge: "https://img.shields.io/badge/VS_Code-Install_Server-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white",
  });
  out.push({
    id: "vscode-insiders", client: "VS Code Insiders",
    href: vsInstall("vscode-insiders"),
    web: `https://insiders.vscode.dev/redirect?url=${enc(vsInstall("vscode-insiders"))}`,
    badge: "https://img.shields.io/badge/VS_Code_Insiders-Install_Server-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white",
  });
  out.push({
    id: "kiro", client: "Kiro",
    href: `https://kiro.dev/launch/mcp/add?name=${enc(name)}&config=${enc(JSON.stringify(server))}`,
    badge: "https://kiro.dev/images/add-to-kiro.svg",
  });
  out.push({
    id: "lmstudio", client: "LM Studio",
    href: `lmstudio://add_mcp?name=${enc(name)}&config=${enc(b64(server))}`,
    web: `https://lmstudio.ai/install-mcp?name=${enc(name)}&config=${enc(b64(server))}`,
    badge: "https://files.lmstudio.ai/deeplink/mcp-install-light.svg",
  });
  const gooseCommon = `id=${enc(name)}&name=${enc(label)}&description=${enc(about)}`;
  out.push({
    id: "goose", client: "Goose",
    href: url
      ? `goose://extension?url=${enc(url)}&type=streamable_http&${gooseCommon}`
      : `goose://extension?cmd=${enc(local.command)}&${local.args.map((a) => `arg=${enc(a)}`).join("&")}&${gooseCommon}`,
    note: env.length ? `Goose asks for ${env.join(", ")} after install.` : undefined,
  });

  const hdrFlags = (flag) => Object.entries(headers).map(([k, v]) => ` ${flag} ${shellQuote(`${k}: ${v}`)}`).join("");
  const envFlags = (flag) => env.map((v) => ` ${flag} ${v}=<${v}>`).join("");
  const cmdline = local ? [local.command, ...local.args].map(shellQuote).join(" ") : "";
  out.push({
    id: "claude-code", client: "Claude Code",
    command: url
      ? `claude mcp add --transport http --scope user ${name} ${shellQuote(url)}${hdrFlags("--header")}`
      : `claude mcp add --scope user${envFlags("-e")} ${name} -- ${cmdline}`,
  });
  out.push({
    id: "codex", client: "Codex (CLI, app and IDE)",
    command: url
      ? `codex mcp add ${name} --url ${shellQuote(url)}` + (hasHeaders ? "" : `\ncodex mcp login ${name}`)
      : `codex mcp add ${name}${envFlags("--env")} -- ${cmdline}`,
    note: url && hasHeaders ? "Codex sends static headers from ~/.codex/config.toml (http_headers)." : undefined,
  });
  out.push(url
    ? { id: "gemini", client: "Gemini CLI", command: `gemini mcp add --transport http --scope user${hdrFlags("--header")} ${name} ${shellQuote(url)}` }
    : { id: "gemini", client: "Gemini CLI", config: JSON.stringify({ mcpServers: { [name]: server } }, null, 2), note: "Paste into ~/.gemini/settings.json." });
  if (url) {
    out.push({
      id: "claude", client: "Claude (web, desktop, mobile)",
      href: "https://claude.ai/settings/connectors",
      note: `Add custom connector, paste ${url}${hasHeaders ? " and add the request headers" : ""}.`,
    });
    if (!hasHeaders) {
      out.push({
        id: "chatgpt", client: "ChatGPT",
        note: `Settings > Apps & Connectors > Advanced > developer mode, then create a connector with ${url} (OAuth).`,
      });
    }
  }
  out.push({
    id: "json", client: "Windsurf/Devin, Zed, Warp, Cline, JetBrains and others",
    config: JSON.stringify({ mcpServers: { [name]: server } }, null, 2),
    note: url
      ? "Some clients name the URL key differently: Windsurf/Devin and Antigravity use serverUrl, Gemini CLI httpUrl, Cline needs \"type\": \"streamableHttp\"."
      : undefined,
  });
  return out;
}

export function formatLinks(links, format = "text") {
  if (format === "json") return JSON.stringify(links, null, 2);
  if (format === "markdown") {
    const badges = links
      .filter((l) => l.badge)
      .map((l) => `[![Add to ${l.client}](${l.badge})](${l.web || l.href})`)
      .join("\n");
    const rest = links
      .filter((l) => !l.badge)
      .map((l) => {
        const body = l.command ? "```bash\n" + l.command + "\n```" : l.config ? "```json\n" + l.config + "\n```" : "";
        const head = l.href ? `**[${l.client}](${l.href})**` : `**${l.client}**`;
        return [head, l.note, body].filter(Boolean).join("\n\n");
      })
      .join("\n\n");
    return `${badges}\n\n${rest}\n`;
  }
  if (format !== "text") throw new UsageError("--format must be text, markdown or json");
  return links
    .map((l) => {
      const lines = [`${l.client}:`];
      if (l.href) lines.push(`  ${l.href}`);
      if (l.web) lines.push(`  web: ${l.web}`);
      if (l.command) lines.push(...l.command.split("\n").map((s) => `  $ ${s}`));
      if (l.config) lines.push(...l.config.split("\n").map((s) => `  ${s}`));
      if (l.note) lines.push(`  (${l.note})`);
      return lines.join("\n");
    })
    .join("\n\n");
}
