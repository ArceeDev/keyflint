"""Search GitHub for MCP (Model Context Protocol) creators to prospect for KeyForge.

Usage:
    python scripts/find_mcp_prospects.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def search_github_mcp_repos() -> list[dict]:
    query = "modelcontextprotocol+language:python+stars:>5"
    url = f"https://api.github.com/search/repositories?q={query}&sort=updated&order=desc&per_page=15"
    headers = {
        "User-Agent": "KeyForge-Prospector/1.0",
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
    print("=" * 75)
    print("  KeyForge: Prospectos Recientes de Creadores MCP en GitHub")
    print("=" * 75)
    items = search_github_mcp_repos()
    if not items:
        print("No se pudieron obtener resultados o se alcanzo el limite de peticiones anonimas.")
        return

    for i, repo in enumerate(items, 1):
        name = repo.get("full_name", "")
        desc = (repo.get("description") or "Sin descripcion")[:60]
        stars = repo.get("stargazers_count", 0)
        html_url = repo.get("html_url", "")
        print(f"[{i:02d}] {name} (stars: {stars})")
        print(f"     Desc: {desc}...")
        print(f"     URL:  {html_url}")
        print("-" * 75)


if __name__ == "__main__":
    main()
