# @keyflint/wrap

Sell access to an existing stdio MCP server without touching its code. `keyflint-wrap` starts your
server, relays JSON-RPC in both directions, and gates every `tools/call`:

1. Offline Ed25519 license check (`keyflint-verify`), including features, node and domain locks.
2. For metered tools, `POST /api/v1/quota/deduct` on your KeyFlint gateway.
3. If the server answers with a JSON-RPC error or `isError: true`, the credits are refunded.

Refused calls never reach your server; the client gets the standard KeyFlint errors
(`-32060` license, `-32061` feature, `-32062` quota, `-32063` gateway). `initialize`, `tools/list`
and every other message pass through untouched.

```bash
export KEYFLINT_LICENSE="LIC-..."          # the buyer's key
export KEYFLINT_PUBLIC_KEYS="k1=<hex>"     # your issuer public key(s)
export KEYFLINT_URL="https://licenses.example.com"   # needed for metered tools

npx @keyflint/wrap --credits 0 --tool summarize=5 -- python server.py
```

| Option | Meaning |
|---|---|
| `--credits N` | Credits per call for tools without `--tool` (default `1` when `KEYFLINT_URL` is set, else `0`). `0` means license check only. |
| `--tool NAME=N` | Credits for one tool. Repeatable. |
| `--free A,B` | Tools that skip KeyFlint entirely. |
| `--features A,B` | Features the license must include. |
| `--offline-grace N` | Calls (0-5) allowed while the gateway is unreachable; their debits are replayed later and never refunded. |
| `--event-type TYPE` | `event_type` sent to the gateway (default `mcp:<tool>`). |

Environment variables are the same as `keyflint-verify` (`KEYFLINT_LICENSE`, `KEYFLINT_PUBLIC_KEYS`,
`KEYFLINT_URL`, `KEYFLINT_CHECKOUT_URL`, `KEYFLINT_MACHINE_ID`, `KEYFLINT_DOMAIN`).

## Claude Desktop (.mcpb)

[`examples/mcpb-template`](../../examples/mcpb-template) packages a server behind the wrapper as an
MCP Bundle. The buyer pastes the license key once at install time; it is declared `sensitive`, so the
host masks it and stores it securely, then passes it to the wrapper as `KEYFLINT_LICENSE`.

## Limits

- stdio transport only (newline-delimited JSON-RPC). For HTTP servers use `keyflint-verify/mcp` in code.
- A gated `tools/call` is forwarded after its check, so it can reach the server after messages the
  client sent later. JSON-RPC does not order requests, and MCP clients do not rely on it.
- JSON-RPC batches (removed in MCP 2025-06-18) may not contain `tools/call`; such entries are refused.
- The wrapper protects honest buyers' keys and quota, not a server the buyer can edit: anyone with
  the server's source can run it without the wrapper. Keep paid logic behind the gateway or on your
  own host if that matters.

MIT licensed.
