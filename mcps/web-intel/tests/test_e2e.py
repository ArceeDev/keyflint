"""Web Intel against a real KeyFlint gateway: debits, refunds, paywall and hosted licenses."""

from __future__ import annotations

import importlib
import json
import os

import pytest
from mcp.client import Client
from mcp.shared.exceptions import MCPError

from conftest import PUB


@pytest.fixture(scope="module")
def license_(gateway):
    return gateway["issue"]("buyer@acme.test")


@pytest.fixture()
def server(gateway, license_, monkeypatch):
    monkeypatch.setenv("KEYFLINT_LICENSE", license_["license_key"])
    monkeypatch.setenv("KEYFLINT_PUBLIC_KEYS", PUB)
    monkeypatch.setenv("KEYFLINT_URL", gateway["url"])
    monkeypatch.setenv("KEYFLINT_CHECKOUT_URL", "https://keyflint.dev/buy")
    monkeypatch.setenv("KEYFLINT_CLOCK_STATE", "off")
    monkeypatch.setenv("WEB_INTEL_ALLOW_PRIVATE", "1")
    monkeypatch.delenv("WEB_INTEL_TRANSPORT", raising=False)
    import keyflint_web_intel.server as srv

    return importlib.reload(srv)


async def call(srv, name, **args):
    async with Client(srv.mcp) as c:
        res = await c.call_tool(name, args)
    text = res.content[0].text if res.content else ""
    data = res.structured_content or (json.loads(text) if text.startswith("{") else None)
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    return res.is_error, data, text


async def balance(srv):
    _, data, _ = await call(srv, "credits_balance")
    return data["balance"]


async def test_pricing_is_free(server):
    err, data, _ = await call(server, "pricing")
    assert not err and data["credits_per_call"]["seo_audit"] == 3


async def test_read_url_debits_one_credit(server, site):
    before = await balance(server)
    err, data, _ = await call(server, "read_url", url=f"{site}/")
    assert not err, data
    assert data["title"].startswith("Acme Widgets")
    assert "# Widgets that last" in data["markdown"]
    assert "cookies" not in data["markdown"] and "Pricing" not in data["markdown"]
    assert data["billing"]["credits_charged"] == 1
    assert await balance(server) == before - 1


async def test_failed_fetch_is_refunded(server, site):
    before = await balance(server)
    err, _, text = await call(server, "read_url", url=f"{site}/missing")
    assert err and "404" in text
    assert await balance(server) == before


async def test_invalid_url_never_charges(server):
    before = await balance(server)
    err, _, text = await call(server, "read_url", url="ftp://x")
    assert err and "http(s)" in text
    assert await balance(server) == before


async def test_seo_audit_and_redirect(server, site):
    err, good, _ = await call(server, "seo_audit", url=f"{site}/old")
    assert not err and good["url"] == f"{site}/"
    err, bad, _ = await call(server, "seo_audit", url=f"{site}/bad")
    assert good["score"] > bad["score"] and bad["top_fixes"]


async def test_metadata_links_stack(server, site):
    _, m, _ = await call(server, "page_metadata", url=site)
    assert m["jsonld_types"] == ["Organization", "WebSite"] and m["lang"] == "en"
    _, links, _ = await call(server, "extract_links", url=site)
    assert {"url": "https://github.com/acme", "text": "GitHub"} in links["external"]
    assert any(link["url"].endswith("/docs") for link in links["internal"])
    _, stack, _ = await call(server, "tech_stack", url=site)
    names = {t["name"] for t in stack["technologies"]}
    assert {"Next.js", "Stripe", "nginx"} <= names


async def test_compare_bills_only_fetched(server, site):
    before = await balance(server)
    err, data, _ = await call(server, "compare_seo", urls=[f"{site}/", f"{site}/bad", "http://127.0.0.1:1/x"])
    assert not err, data
    assert data["ranking"][0]["url"] == f"{site}/" and len(data["failed"]) == 1
    assert await balance(server) == before - 6


async def test_paywall_when_credits_run_out(gateway, site, monkeypatch):
    lic = gateway["issue"]("broke@acme.test", tier="community")
    monkeypatch.setenv("KEYFLINT_LICENSE", lic["license_key"])
    monkeypatch.setenv("KEYFLINT_PUBLIC_KEYS", PUB)
    monkeypatch.setenv("KEYFLINT_URL", gateway["url"])
    monkeypatch.setenv("KEYFLINT_CHECKOUT_URL", "https://keyflint.dev/buy")
    monkeypatch.setenv("WEB_INTEL_ALLOW_PRIVATE", "1")
    monkeypatch.setenv("WEB_INTEL_PRICES", f"seo_audit={lic['quota_credits'] + 1}")
    import keyflint_web_intel.server as srv

    srv = importlib.reload(srv)
    async with Client(srv.mcp) as c:
        with pytest.raises(MCPError) as exc:
            await c.call_tool("seo_audit", {"url": site})
    assert exc.value.code == -32062
    assert "Credits exhausted" in str(exc.value) and "keyflint.dev/buy" in str(exc.value)


async def test_hosted_mode_requires_header(gateway, license_, monkeypatch):
    from keyflint_web_intel.billing import Billing, license_from_headers
    from keyflint_verify.mcp import LicenseError

    monkeypatch.setenv("KEYFLINT_PUBLIC_KEYS", PUB)
    monkeypatch.setenv("KEYFLINT_URL", gateway["url"])
    monkeypatch.delenv("KEYFLINT_LICENSE", raising=False)
    b = Billing(hosted=True)
    with pytest.raises(LicenseError):
        b.client(None)
    hdr = {"Authorization": f"Bearer {license_['license_key']}"}
    assert license_from_headers(hdr) == license_["license_key"]
    async with b.charge(1, "read_url", hdr) as receipt:
        assert receipt["remaining_balance"] >= 0
    with pytest.raises(LicenseError):
        b.client({"X-KeyFlint-License": "LIC-forged"}).check()
