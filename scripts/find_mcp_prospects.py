"""Search GitHub for MCP (Model Context Protocol) creators and projects to prospect for KeyForge.

Usage:
    python scripts/find_mcp_prospects.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
import urllib.error

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def search_github_mcp_repos(query: str = "modelcontextprotocol+stars:>10", per_page: int = 15) -> list[dict]:
    url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page={per_page}"
    headers = {
        "User-Agent": "KeyForge-Prospector/1.1",
        "Accept": "application/vnd.github.v3+json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("items", [])
    except urllib.error.URLError as e:
        print(f"Error accessing GitHub API: {e}")
        return []


def main() -> None:
    print("=" * 78)
    print("  KeyForge: Active Model Context Protocol (MCP) Prospects on GitHub")
    print("=" * 78)
    items = search_github_mcp_repos()
    if not items:
        print("No se pudieron obtener resultados o se alcanzo el limite de peticiones anonimas.")
        return

    for i, repo in enumerate(items, 1):
        name = repo.get("full_name", "")
        desc = (repo.get("description") or "Sin descripcion").replace("\n", " ")[:65]
        stars = repo.get("stargazers_count", 0)
        html_url = repo.get("html_url", "")
        lang = repo.get("language") or "Other"
        print(f"[{i:02d}] {name} ({stars} stars | {lang})")
        print(f"     Desc: {desc}...")
        print(f"     URL:  {html_url}")
        print("-" * 78)

    print("\nTip: For 20 curated prospects with complete 3-paragraph developer outreach")
    print("pitches ready to copy and paste, see: MCP_PROSPECT_LEADS.md")


if __name__ == "__main__":
    main()
