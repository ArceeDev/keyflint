#!/usr/bin/env node
import { init, newDevLicense, parseInitArgs, ttyAsk, UsageError } from "../src/init.js";
import { buildLinks, formatLinks, parseLinksArgs } from "../src/links.js";

const USAGE = `Usage: keyflint <command> [options]

Commands:
  init [dir]          Create a paid MCP server that works on the first run
      --lang python|node   (default python)
      --name NAME          package name (default: folder name)
      --description TEXT   one-line description
      --gateway URL        your KeyFlint gateway; its public key ring is trusted instead of a dev key
      --checkout URL       where buyers top up credits
      --github USER        used for the MCP Registry name io.github.USER/NAME
      -y, --yes            accept defaults, no questions
      --force              write into a non-empty folder
  dev-license         Print a new local development license (inside a project made by init)
      --days N             expire after N days (default: never)
      --features A,B       features to grant (default core)
  links               Print one-click install links and README badges for your server
      --name NAME          server name shown in the client (required)
      --url URL            remote MCP endpoint (streamable HTTP)
      --pypi PKG | --npm PKG   local package started with uvx / npx
      --header "Name: value"   extra header for the remote server (repeatable)
      --env NAME               env var the user must fill in, e.g. KEYFLINT_LICENSE (repeatable)
      --format text|markdown|json   (default text)

Docs: https://keyflint.dev  ·  Issues: https://github.com/ArceeDev/keyflint/issues
`;

const [cmd, ...rest] = process.argv.slice(2);
const out = (s) => process.stdout.write(s.endsWith("\n") ? s : s + "\n");
const err = (s) => process.stderr.write(s.endsWith("\n") ? s : s + "\n");

async function main() {
  if (!cmd || cmd === "help" || cmd === "--help" || cmd === "-h") {
    out(USAGE);
    return cmd ? 0 : 2;
  }
  if (cmd === "--version" || cmd === "-v") {
    const { createRequire } = await import("node:module");
    out(createRequire(import.meta.url)("../package.json").version);
    return 0;
  }
  if (cmd === "init") {
    const opts = parseInitArgs(rest);
    if (opts.help) { out(USAGE); return 0; }
    const ask = opts.yes ? undefined : ttyAsk();
    try {
      const r = await init(opts, { ask, log: err });
      const py = r.lang === "python";
      out(`\nCreated ${r.name} (${r.lang}) in ${r.target}`);
      out(r.keySource === "gateway"
        ? `Trusting the key ring of ${r.gatewayUrl}. Issue yourself a license there to test.`
        : "A development license is in .env (signed by .keyflint/dev-issuer.pem, git-ignored).");
      out(`\nNext:\n  cd ${JSON.stringify(r.target)}\n  ${py ? "uv sync && uv run pytest -q" : "npm install && npm test"}\n  ${py ? `uv run --env-file .env ${r.name}` : "npm start"}\n`);
      out("Then read README.md > Go live. Questions: https://github.com/ArceeDev/keyflint/discussions");
    } finally {
      ask?.close?.();
    }
    return 0;
  }
  if (cmd === "dev-license") {
    let days = 0;
    let features = ["core"];
    for (let i = 0; i < rest.length; i++) {
      if (rest[i] === "--days") days = Number(rest[++i]);
      else if (rest[i] === "--features") features = String(rest[++i] ?? "").split(",").map((s) => s.trim()).filter(Boolean);
      else throw new UsageError(`unknown option ${rest[i]}`);
    }
    if (!Number.isInteger(days) || days < 0) throw new UsageError("--days must be a whole number");
    out(newDevLicense(process.cwd(), { days, features }));
    return 0;
  }
  if (cmd === "links") {
    const opts = parseLinksArgs(rest);
    out(formatLinks(buildLinks(opts), opts.format));
    return 0;
  }
  throw new UsageError(`unknown command "${cmd}"`);
}

main().then(
  (code) => process.exit(code),
  (e) => {
    if (e instanceof UsageError || e?.name === "UsageError") {
      err(`keyflint: ${e.message}\n\n${USAGE}`);
      process.exit(2);
    }
    err(`keyflint: ${e?.stack || e}`);
    process.exit(1);
  },
);
