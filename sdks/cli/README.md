# keyflint

Create, run and share **paid MCP servers**. One command scaffolds a server that sells its tools with
KeyFlint licenses (Ed25519, verified offline) and prepaid credits per call, refunded automatically
when a tool fails. Another prints one-click install links for every major AI client.

```bash
npx keyflint init my-tools            # Python (default)
npx keyflint init my-tools --lang node
```

The project works on the first run, with no gateway and no account:

- `keyflint init` creates a **development issuer** (`.keyflint/dev-issuer.pem`, git-ignored) and puts a
  development license in `.env`, so the free example tool answers right away.
- The trusted key ring is compiled into the code (`licensing.py` / `licensing.js`), not read from the
  environment, so a buyer cannot trust a key of their own.
- You also get `manifest.json` (Claude Desktop `.mcpb` bundle), `server.json` (official MCP Registry),
  tests and a README with install snippets.

Point it at your gateway to trust its keys from the start:

```bash
npx keyflint init my-tools --gateway https://licenses.example.com --checkout https://example.com/buy
```

## One-click install links

```bash
npx keyflint links --name my-tools --url https://mcp.example.com/my-tools/mcp --format markdown
npx keyflint links --name my-tools --pypi my-tools --env KEYFLINT_LICENSE
```

| Client | What you get |
|---|---|
| Cursor | `cursor://` deeplink + `cursor.com/en/install-mcp` web link + badge |
| VS Code, VS Code Insiders | `vscode:mcp/install` + `insiders.vscode.dev/redirect` web link + badge |
| Kiro | `kiro.dev/launch/mcp/add` link + badge |
| LM Studio | `lmstudio://add_mcp` + `lmstudio.ai/install-mcp` web link + badge |
| Goose | `goose://extension` deeplink |
| Claude Code, Codex, Gemini CLI | one-line `mcp add` commands |
| Claude, ChatGPT | connector steps (remote servers with OAuth) |
| Windsurf/Devin, Zed, Warp, Cline, JetBrains | `mcpServers` JSON |

Remote links carry only the URL: clients run the MCP OAuth flow on connect. Use `--header` only for
servers that take a static token, and never put a real secret in a public link.

## Other commands

- `keyflint dev-license [--days N] [--features a,b]` prints a fresh development license.
- `keyflint --help` lists every option.

MIT licensed. The KeyFlint gateway itself is BSL 1.1: see the [main repository](https://github.com/ArceeDev/keyflint).
