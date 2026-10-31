"""Turnkey Example: Monetized Model Context Protocol (MCP) Server with KeyForge.

Run this server with FastMCP:
    pip install keyforge-verify "mcp[cli]"
    export KEYFORGE_LICENSE="LIC-PRO-eyJ..."
    export KEYFORGE_URL="https://licenses.yourdomain.com"
    mcp dev server.py
"""

from mcp.server.fastmcp import FastMCP
from keyforge_verify.mcp import KeyForge

# Initialize FastMCP Server
mcp = FastMCP("MarketResearchAgent")

# Initialize KeyForge Client (reads KEYFORGE_LICENSE, KEYFORGE_URL, KEYFORGE_PUBLIC_KEYS from env)
kf = KeyForge()


@mcp.tool()
@kf.require_license(features=["core"])
def ping() -> str:
    """Free tool for all licensed users (100% offline license validation in < 1ms)."""
    return "Pong! License verified offline."


@mcp.tool()
@kf.metered(credits=5)
async def generate_competitor_analysis(company_name: str) -> str:
    """Premium metered tool: Costs 5 credits per execution.
    
    If this function succeeds: 5 credits are debited from the customer's wallet.
    If an exception occurs or LLM fails: KeyForge automatically refunds the 5 credits.
    If customer balance is zero: Returns standard MCP Error -32062 with your checkout URL.
    """
    # Simulated expensive AI operation / external API call
    return f"Deep competitor analysis generated for '{company_name}' (5 credits consumed)."


if __name__ == "__main__":
    mcp.run()
