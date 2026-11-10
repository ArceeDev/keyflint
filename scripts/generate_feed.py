"""Generates docs/feed.xml (RSS 2.0) rotated from DAILY_POST_QUEUE for automated RSS-to-social syndication."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import html
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.application.services.daily_growth import DAILY_POST_QUEUE  # noqa: E402


def generate_feed(now: datetime | None = None) -> Path:
    now = (now or datetime.now(timezone.utc)).replace(hour=8, minute=15, second=0, microsecond=0)
    n = len(DAILY_POST_QUEUE)
    items_xml: list[str] = []
    for offset in range(min(5, n)):
        dt = now - timedelta(days=offset)
        idx = dt.timetuple().tm_yday % n
        post = DAILY_POST_QUEUE[idx]
        title = html.escape(post["topic"])
        link = html.escape(post["url"])
        guid = html.escape(f"{post['url']}#{dt.strftime('%Y-%m-%d')}")
        desc = html.escape(post["linkedin_es"] + "\n\n--\n\n" + post["x_en"])
        pub = format_datetime(dt, usegmt=True)
        items_xml.append(
            f"    <item>\n"
            f"      <title>{title}</title>\n"
            f"      <link>{link}</link>\n"
            f"      <guid isPermaLink=\"false\">{guid}</guid>\n"
            f"      <pubDate>{pub}</pubDate>\n"
            f"      <description>{desc}</description>\n"
            f"    </item>"
        )

    last_build = format_datetime(now, usegmt=True)
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        '  <channel>\n'
        '    <title>KeyFlint &amp; Flint Ecosystem Feed</title>\n'
        '    <link>https://keyflint.dev/</link>\n'
        '    <atom:link href="https://keyflint.dev/feed.xml" rel="self" type="application/rss+xml" />\n'
        '    <description>Daily updates on offline Ed25519 licensing, MCP server monetization, OAuth 2.1 connectors, and deterministic financial MCP servers.</description>\n'
        '    <language>en</language>\n'
        f'    <lastBuildDate>{last_build}</lastBuildDate>\n'
        + "\n".join(items_xml)
        + "\n  </channel>\n</rss>\n"
    )
    out = ROOT / "docs" / "feed.xml"
    out.write_text(rss, encoding="utf-8")
    return out


if __name__ == "__main__":
    p = generate_feed()
    print("Generated", p)
