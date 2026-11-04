"""Web Intel MCP: web pages -> clean markdown, metadata, links, SEO audit, tech stack.

Every paid tool debits KeyFlint credits before it fetches and refunds them if the fetch fails.
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from . import analyze
from .billing import Billing
from .fetch import FetchError, fetch, validate_url

DEFAULT_PRICES = {"read_url": 1, "page_metadata": 1, "extract_links": 1, "tech_stack": 2, "seo_audit": 3}
MAX_COMPARE = 5


def _prices() -> dict[str, int]:
    prices = dict(DEFAULT_PRICES)
    for item in filter(None, (p.strip() for p in os.environ.get("WEB_INTEL_PRICES", "").split(","))):
        name, _, n = item.partition("=")
        if name.strip() in prices and n.strip().isdigit() and int(n) > 0:
            prices[name.strip()] = int(n)
    return prices


PRICES = _prices()
billing = Billing(hosted=os.environ.get("WEB_INTEL_TRANSPORT", "stdio") != "stdio")
RO = ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True)

mcp = MCPServer(
    "keyflint-web-intel",
    title="Web Intel (KeyFlint metered)",
    version="0.1.0",
    website_url="https://keyflint.dev",
    instructions=(
        "Turns web pages into agent-ready data. Paid tools cost KeyFlint credits (see `pricing`); "
        "a failed fetch is refunded automatically. Use `read_url` for content, `page_metadata` for SEO tags, "
        "`seo_audit` for a scored checklist with fixes, `tech_stack` to identify frameworks and hosting."
    ),
)


def _headers(ctx: Context) -> Any:
    try:
        return ctx.headers
    except ValueError:
        return None


async def _paid(ctx: Context, tool: str, url: str, credits: int | None = None) -> tuple[analyze.Page, dict]:
    url = validate_url(url)  # bad input is rejected before any debit
    async with billing.charge(credits or PRICES[tool], tool, _headers(ctx)) as receipt:
        page = await fetch(url)
    return page, receipt


def _billing_note(receipt: dict, credits: int) -> dict[str, Any]:
    return {"credits_charged": credits, "credits_remaining": receipt.get("remaining_balance")}


@mcp.tool(annotations=RO)
async def read_url(url: str, ctx: Context, max_chars: int = 20000) -> dict[str, Any]:
    """Fetch a web page and return its main content as clean Markdown (nav, ads and cookie banners removed).

    Args:
        url: Page URL (https:// is assumed when no scheme is given).
        max_chars: Cap on returned markdown length (default 20000, max 100000).
    """
    max_chars = max(500, min(int(max_chars), 100_000))
    url = validate_url(url)
    async with billing.charge(PRICES["read_url"], "read_url", _headers(ctx)) as receipt:
        page = await fetch(url)
        if page.status >= 400:
            raise FetchError(f"{page.final_url} returned HTTP {page.status}; credits refunded.")
        out = analyze.to_markdown(page, max_chars)
    return {**out, "billing": _billing_note(receipt, PRICES["read_url"])}


@mcp.tool(annotations=RO)
async def page_metadata(url: str, ctx: Context) -> dict[str, Any]:
    """Title, description, canonical, lang, robots, Open Graph, JSON-LD types, H1-H3 and image alt stats."""
    page, receipt = await _paid(ctx, "page_metadata", url)
    return {**analyze.metadata(page), "billing": _billing_note(receipt, PRICES["page_metadata"])}


@mcp.tool(annotations=RO)
async def extract_links(url: str, ctx: Context, limit: int = 200) -> dict[str, Any]:
    """Internal and external links on a page (deduplicated, absolute URLs, anchor text)."""
    page, receipt = await _paid(ctx, "extract_links", url)
    out = analyze.links(page, max(1, min(int(limit), 1000)))
    return {**out, "billing": _billing_note(receipt, PRICES["extract_links"])}


@mcp.tool(annotations=RO)
async def tech_stack(url: str, ctx: Context) -> dict[str, Any]:
    """Detect frameworks, CMS, analytics, payments, CDN/hosting and security headers of a site."""
    page, receipt = await _paid(ctx, "tech_stack", url)
    return {**analyze.tech_stack(page), "billing": _billing_note(receipt, PRICES["tech_stack"])}


@mcp.tool(annotations=RO)
async def seo_audit(url: str, ctx: Context) -> dict[str, Any]:
    """Scored on-page SEO audit (0-100, A-F) with 16 weighted checks and the top fixes to apply first."""
    page, receipt = await _paid(ctx, "seo_audit", url)
    return {**analyze.seo_audit(page), "billing": _billing_note(receipt, PRICES["seo_audit"])}


@mcp.tool(annotations=RO)
async def compare_seo(urls: list[str], ctx: Context) -> dict[str, Any]:
    """Audit 2-5 pages (e.g. you vs competitors) and rank them. Costs seo_audit price x number of URLs.

    Unreachable URLs are reported, not billed: their share is refunded as one batch.
    """
    clean = list(dict.fromkeys(validate_url(u) for u in urls))
    if not 2 <= len(clean) <= MAX_COMPARE:
        raise FetchError(f"Pass between 2 and {MAX_COMPARE} distinct URLs.")
    billing.client(_headers(ctx)).check()  # no fetching for callers without a valid license
    unit = PRICES["seo_audit"]
    results: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    # Debit only the URLs that actually fetched, so failures never cost anything.
    pages = []
    for u in clean:
        try:
            pages.append(await fetch(u))
        except FetchError as exc:
            failed.append({"url": u, "error": str(exc)})
    if not pages:
        raise FetchError("None of the URLs could be fetched; nothing was charged.")
    async with billing.charge(unit * len(pages), "compare_seo", _headers(ctx)) as receipt:
        for p in pages:
            a = analyze.seo_audit(p)
            results.append({"url": a["url"], "score": a["score"], "grade": a["grade"], "top_fixes": a["top_fixes"]})
    results.sort(key=lambda r: -r["score"])
    return {"ranking": results, "failed": failed, "billing": _billing_note(receipt, unit * len(pages))}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def pricing() -> dict[str, Any]:
    """Credit price of each tool and where to buy credits. Free."""
    return {"credits_per_call": {**PRICES, "compare_seo": f"{PRICES['seo_audit']} x URLs"},
            "refunds": "Failed fetches are refunded automatically.",
            "buy_credits": billing.checkout_url or "https://keyflint.dev"}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def credits_balance(ctx: Context) -> dict[str, Any]:
    """Remaining credits on your KeyFlint license. Free."""
    return await billing.balance(_headers(ctx))


def main() -> None:
    p = argparse.ArgumentParser(prog="keyflint-web-intel", description=__doc__)
    p.add_argument("--http", action="store_true", help="Serve Streamable HTTP (hosted, license per request).")
    p.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    args = p.parse_args()
    if args.http:
        billing.hosted = True
        mcp.run("streamable-http", host=args.host, port=args.port, stateless_http=True, json_response=True)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
