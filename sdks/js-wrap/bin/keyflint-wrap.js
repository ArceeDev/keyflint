#!/usr/bin/env node
import { parseArgs, wrap, UsageError } from "../src/wrap.js";

const USAGE = `Usage: keyflint-wrap [options] -- <command> [args...]

Gates every tools/call of a stdio MCP server with a KeyFlint license.

Options:
  --credits N         credits per tool call (default 1 with KEYFLINT_URL, else 0 = license check only)
  --tool NAME=N       credits for one tool (repeatable; 0 = license check only)
  --free A,B          tools that skip KeyFlint entirely
  --features A,B      features the license must include
  --offline-grace N   calls allowed while the gateway is unreachable (0-5, default 0)
  --event-type TYPE   event_type sent to the gateway (default mcp:<tool>)
  --idempotency-arg F argument field in tools/call to reuse as retry request id
  --dedup-ttl SEC     seconds to cache successful results per request id (default 300, 0 disables)

Environment: KEYFLINT_LICENSE, KEYFLINT_PUBLIC_KEYS, KEYFLINT_URL, KEYFLINT_CHECKOUT_URL,
KEYFLINT_MACHINE_ID, KEYFLINT_DOMAIN (same as keyflint-verify).
`;

const argv = process.argv.slice(2);
if (argv.length === 0 || argv[0] === "--help" || argv[0] === "-h") {
  process.stderr.write(USAGE);
  process.exit(argv.length === 0 ? 2 : 0);
}
let opts;
try {
  opts = parseArgs(argv);
} catch (e) {
  if (!(e instanceof UsageError)) throw e;
  process.stderr.write(`keyflint-wrap: ${e.message}\n\n${USAGE}`);
  process.exit(2);
}
const code = await wrap(opts, { forwardSignals: true });
// stdin may still be open when the server exits on its own; flush and leave with its code.
process.stdout.write("", () => process.exit(code));
