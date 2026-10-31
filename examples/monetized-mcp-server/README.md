# Monetized MCP Server Example (FastMCP + KeyForge)

This example shows how to turn any Model Context Protocol (MCP) tool into a revenue-generating asset in under 60 seconds using KeyForge.

---

## 1. Quickstart

```bash
# 1. Install dependencies
pip install keyforge-verify "mcp[cli]"

# 2. Set your environment variables
export KEYFORGE_LICENSE="LIC-PRO-eyJ..."
export KEYFORGE_PUBLIC_KEYS="0043b567534bfa2d55059a05642f75573d420899146f334a9f7fc5fba797bd0b"
export KEYFORGE_URL="http://127.0.0.1:8000"
export KEYFORGE_CHECKOUT_URL="https://yourstore.lemonsqueezy.com/buy"

# 3. Test interactively with MCP Inspector
mcp dev server.py
```

---

## 2. Integrating with Claude Desktop

Add this block to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "market-research": {
      "command": "python",
      "args": ["/path/to/server.py"],
      "env": {
        "KEYFORGE_LICENSE": "LIC-PRO-eyJ...",
        "KEYFORGE_PUBLIC_KEYS": "0043b5...",
        "KEYFORGE_URL": "https://licenses.yourdomain.com",
        "KEYFORGE_CHECKOUT_URL": "https://yourstore.lemonsqueezy.com/buy"
      }
    }
  }
}
```

---

## 3. What happens during execution?

1. **Offline License Check (`@kf.require_license`)**:
   - The license token signature is checked with local Ed25519 cryptography in **0.13 milliseconds**. Zero network requests.
2. **Atomic Quota Metering (`@kf.metered(credits=5)`)**:
   - Sends an atomic debit to your KeyForge server via SQLite WAL `BEGIN IMMEDIATE`.
   - If credits exist: tool executes.
   - If user is out of credits: returns MCP code `-32062` and Claude displays: *"Credits exhausted. Top up here: https://yourstore.lemonsqueezy.com/buy"*.
   - If your downstream code or AI model throws an error: KeyForge automatically executes a signed refund within 900 seconds!
