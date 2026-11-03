# KeyFlint .mcpb template (Claude Desktop extension)

An [MCP Bundle](https://github.com/modelcontextprotocol/mcpb) (manifest spec `0.3`) that runs your
stdio MCP server behind [`@keyflint/wrap`](../../sdks/js-wrap). Buyers install one file in Claude
Desktop, paste their license key once, and every tool call is license-checked and metered.

## Use it

1. Copy this folder and replace `server/index.js` with your server (any stdio MCP server; for a
   Python one, change the last two `args` to your interpreter and script, and note that the buyer then
   needs that interpreter installed).
2. In `manifest.json`, set `name`, `display_name`, `author`, `tools`, and in `server.mcp_config`:
   - `args`: `--credits` / `--tool NAME=N` / `--free` per tool (see the wrapper README).
   - `env.KEYFLINT_PUBLIC_KEYS`: your issuer public key(s) (`kid=hex`). Public keys are safe to ship.
   - `env.KEYFLINT_URL`: your gateway (needed for metered tools).
   - `env.KEYFLINT_CHECKOUT_URL`: where buyers get or renew a license.
3. Build:

```bash
npm install
npx @anthropic-ai/mcpb validate manifest.json
npx @anthropic-ai/mcpb pack . my-paid-mcp-server.mcpb
```

The license key is a `user_config` field with `"sensitive": true`: the host masks it and stores it
securely instead of in plain config, and injects it as `KEYFLINT_LICENSE`. Never put a license key or
your private signing key in the bundle.
