"""Pure HTML analysis (no network): reader markdown, metadata, links, SEO audit, tech stack."""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

from .fetch import Page

_NOISE = ["script", "style", "noscript", "template", "svg", "iframe", "form", "nav", "header", "footer", "aside"]
_NOISE_HINT = re.compile(r"(cookie|consent|banner|newsletter|subscribe|share|social|sidebar|breadcrumb|menu|popup|modal|advert|promo)", re.I)


def soup_of(page: Page) -> BeautifulSoup:
    return BeautifulSoup(page.text, "html.parser")


def _meta(soup: BeautifulSoup, *names: str) -> Optional[str]:
    for n in names:
        tag = soup.find("meta", attrs={"name": n}) or soup.find("meta", attrs={"property": n})
        if isinstance(tag, Tag) and tag.get("content"):
            return str(tag["content"]).strip()
    return None


def _main_node(soup: BeautifulSoup) -> Tag:
    for sel in ("main", "article", "[role=main]", "#content", ".content", ".post", ".entry-content"):
        node = soup.select_one(sel)
        if node and len(node.get_text(strip=True)) > 200:
            return node
    return soup.body or soup


def to_markdown(page: Page, max_chars: int = 20000) -> dict[str, Any]:
    soup = soup_of(page)
    title = (soup.title.get_text(strip=True) if soup.title else None) or _meta(soup, "og:title")
    for t in soup(_NOISE):
        t.decompose()
    for t in soup.find_all(attrs={"class": _NOISE_HINT}) + soup.find_all(attrs={"id": _NOISE_HINT}):
        if isinstance(t, Tag) and t.name not in ("body", "main", "article", "html"):
            t.decompose()
    node = _main_node(soup)
    for a in node.find_all("a", href=True):
        a["href"] = urljoin(page.final_url, str(a["href"]))
    for img in node.find_all("img", src=True):
        img["src"] = urljoin(page.final_url, str(img["src"]))
    md = markdownify(str(node), heading_style="ATX", bullets="-", strip=["span"])
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    words = len(md.split())
    truncated = len(md) > max_chars
    return {"url": page.final_url, "title": title, "word_count": words,
            "truncated": truncated or page.truncated, "markdown": md[:max_chars]}


def _jsonld_types(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(s.string or "")
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                t = item.get("@type")
                out.extend(t if isinstance(t, list) else [t] if t else [])
                stack.extend(item.get("@graph") or [])
    return sorted({str(t) for t in out})


def metadata(page: Page) -> dict[str, Any]:
    soup = soup_of(page)
    canon = soup.find("link", rel="canonical")
    html = soup.find("html")
    headings = {f"h{i}": [h.get_text(" ", strip=True)[:160] for h in soup.find_all(f"h{i}")][:20] for i in (1, 2, 3)}
    imgs = soup.find_all("img")
    return {
        "url": page.final_url, "status": page.status, "elapsed_ms": page.elapsed_ms, "redirects": page.redirects,
        "title": soup.title.get_text(strip=True) if soup.title else None,
        "description": _meta(soup, "description"),
        "canonical": canon.get("href") if isinstance(canon, Tag) else None,
        "lang": html.get("lang") if isinstance(html, Tag) else None,
        "robots": _meta(soup, "robots"),
        "open_graph": {k: _meta(soup, f"og:{k}") for k in ("title", "description", "image", "type", "url")},
        "twitter_card": _meta(soup, "twitter:card"),
        "jsonld_types": _jsonld_types(soup),
        "headings": headings,
        "images": {"total": len(imgs), "missing_alt": sum(1 for i in imgs if not (i.get("alt") or "").strip())},
        "word_count": len(soup.get_text(" ", strip=True).split()),
    }


def links(page: Page, limit: int = 200) -> dict[str, Any]:
    soup = soup_of(page)
    host = urlsplit(page.final_url).hostname
    internal: dict[str, str] = {}
    external: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absu = urljoin(page.final_url, href).split("#")[0]
        bucket = internal if urlsplit(absu).hostname == host else external
        bucket.setdefault(absu, a.get_text(" ", strip=True)[:120])
    fmt = lambda d: [{"url": u, "text": t} for u, t in list(d.items())[:limit]]  # noqa: E731
    return {"url": page.final_url, "internal_count": len(internal), "external_count": len(external),
            "internal": fmt(internal), "external": fmt(external)}


def seo_audit(page: Page) -> dict[str, Any]:
    m = metadata(page)
    checks: list[dict[str, Any]] = []

    def add(cid: str, ok: bool, weight: int, fix: str, value: Any = None) -> None:
        checks.append({"id": cid, "pass": ok, "weight": weight, "value": value, "fix": None if ok else fix})

    title, desc = m["title"] or "", m["description"] or ""
    add("status_200", m["status"] == 200, 10, "Serve the page with HTTP 200.", m["status"])
    add("https", page.final_url.startswith("https://"), 8, "Serve over HTTPS and redirect HTTP to it.")
    add("title_present", bool(title), 10, "Add a <title>.", title)
    add("title_length", 30 <= len(title) <= 60, 5, "Keep the title between 30 and 60 characters.", len(title))
    add("description_present", bool(desc), 8, "Add <meta name=description>.", desc[:160] or None)
    add("description_length", 70 <= len(desc) <= 160, 4, "Keep the description between 70 and 160 characters.", len(desc))
    add("single_h1", len(m["headings"]["h1"]) == 1, 7, "Use exactly one <h1>.", len(m["headings"]["h1"]))
    add("canonical", bool(m["canonical"]), 5, "Add <link rel=canonical>.", m["canonical"])
    add("lang", bool(m["lang"]), 3, "Set <html lang>.", m["lang"])
    add("indexable", "noindex" not in (m["robots"] or "").lower()
        and "noindex" not in page.headers.get("x-robots-tag", "").lower(), 10, "Remove noindex.", m["robots"])
    add("open_graph", bool(m["open_graph"]["title"] and m["open_graph"]["image"]), 5,
        "Add og:title and og:image for link previews.")
    add("structured_data", bool(m["jsonld_types"]), 6, "Add JSON-LD (Organization, Product, Article, FAQPage...).",
        m["jsonld_types"])
    add("img_alt", m["images"]["missing_alt"] == 0, 4, "Add alt text to every meaningful image.", m["images"])
    add("content_depth", m["word_count"] >= 300, 6, "Thin content: aim for 300+ words of real text.", m["word_count"])
    add("viewport", bool(re.search(r'<meta[^>]+name=["\']viewport', page.text, re.I)), 5, "Add a viewport meta tag.")
    add("fast_response", m["elapsed_ms"] < 1500, 4, "Server response is slow (>1.5 s).", m["elapsed_ms"])
    total = sum(c["weight"] for c in checks)
    score = round(100 * sum(c["weight"] for c in checks if c["pass"]) / total)
    fixes = sorted((c for c in checks if not c["pass"]), key=lambda c: -c["weight"])
    grade = next(g for g, floor in (("A", 90), ("B", 80), ("C", 70), ("D", 60), ("F", 0)) if score >= floor)
    return {"url": page.final_url, "score": score, "grade": grade, "top_fixes": [c["fix"] for c in fixes[:5]], "checks": checks}


_SIGNATURES: list[tuple[str, str, str]] = [
    # (name, where: html|header, regex)
    ("Next.js", "html", r"/_next/|__NEXT_DATA__"), ("Nuxt", "html", r"/_nuxt/|__NUXT__"),
    ("React", "html", r"data-reactroot|react-dom"), ("Vue", "html", r"data-v-[0-9a-f]{6}|vue(\.min)?\.js"),
    ("Svelte", "html", r"svelte-[a-z0-9]{5,}"), ("Astro", "html", r"astro-island|/_astro/"),
    ("Angular", "html", r"ng-version="), ("Gatsby", "html", r"___gatsby"), ("Remix", "html", r"__remixContext"),
    ("WordPress", "html", r"wp-content|wp-includes"), ("Shopify", "html", r"cdn\.shopify\.com|Shopify\.theme"),
    ("Webflow", "html", r"webflow\.(js|css)|data-wf-page"), ("Wix", "html", r"static\.wixstatic\.com"),
    ("Squarespace", "html", r"squarespace\.com"), ("Framer", "html", r"framerusercontent\.com"),
    ("Ghost", "html", r'content="Ghost'), ("Tailwind CSS", "html", r'class="[^"]*\b(?:flex|grid) [^"]*\b(?:px|py|mt|mb)-\d'),
    ("Bootstrap", "html", r"bootstrap(\.min)?\.(css|js)"), ("jQuery", "html", r"jquery(\.min)?\.js"),
    ("Google Analytics", "html", r"googletagmanager\.com/gtag|google-analytics\.com"),
    ("Google Tag Manager", "html", r"googletagmanager\.com/gtm\.js"), ("Plausible", "html", r"plausible\.io/js"),
    ("PostHog", "html", r"posthog"), ("Segment", "html", r"cdn\.segment\.com"), ("Hotjar", "html", r"hotjar\.com"),
    ("Intercom", "html", r"widget\.intercom\.io"), ("Crisp", "html", r"client\.crisp\.chat"),
    ("Stripe", "html", r"js\.stripe\.com"), ("Lemon Squeezy", "html", r"lemonsqueezy"),
    ("Cloudflare", "header", r"^server: cloudflare|^cf-ray:"), ("Vercel", "header", r"^server: vercel|^x-vercel-id:"),
    ("Netlify", "header", r"^server: netlify|^x-nf-request-id:"), ("Fly.io", "header", r"^fly-request-id:"),
    ("nginx", "header", r"^server: nginx"), ("Apache", "header", r"^server: apache"),
    ("AWS CloudFront", "header", r"^x-amz-cf-id:|^via: .*cloudfront"), ("PHP", "header", r"^x-powered-by: php"),
    ("Express", "header", r"^x-powered-by: express"),
]


def tech_stack(page: Page) -> dict[str, Any]:
    hdr = "\n".join(f"{k}: {v}" for k, v in page.headers.items()).lower()
    found = []
    for name, where, rx in _SIGNATURES:
        hay = page.text if where == "html" else hdr
        if re.search(rx, hay, re.I | re.M):
            found.append({"name": name, "evidence": where})
    gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', page.text, re.I)
    sec = {h: page.headers.get(h) is not None for h in
           ("strict-transport-security", "content-security-policy", "x-frame-options", "x-content-type-options",
            "referrer-policy")}
    return {"url": page.final_url, "technologies": found, "generator": gen.group(1) if gen else None,
            "security_headers": sec, "server": page.headers.get("server")}
