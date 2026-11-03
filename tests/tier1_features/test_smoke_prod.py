"""Tier 1: production smoke checks judge responses correctly (no network)."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "smoke_prod", Path(__file__).resolve().parents[2] / "scripts" / "smoke_prod.py"
)
smoke = importlib.util.module_from_spec(_SPEC)
sys.modules["smoke_prod"] = smoke
_SPEC.loader.exec_module(smoke)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 10


def fake(overrides=None):
    pages = {
        "/readyz": (200, json.dumps({"ready": True}).encode()),
        "/api/v1/health": (200, json.dumps({"healthy": True, "backup": {"status": "ok"}}).encode()),
        "/openapi.json": (200, b'{"paths": {}}'),
        "/": (200, b"<title>KeyFlint</title> https://buy.stripe.com/x"),
        "/og.png": (200, PNG),
    }
    pages.update(overrides or {})

    def fetch(url, timeout):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1] if url.count("/") > 2 else "/"
        result = pages[path]
        if isinstance(result, Exception):
            raise result
        return result

    return fetch


def run(**kw):
    return {c.name: c for c in smoke.run_checks("https://g.test", "https://s.test", fetch=kw.pop("fetch"), **kw)}


class TestSmokeProd(unittest.TestCase):
    def test_all_green(self):
        self.assertTrue(all(c.ok for c in run(fetch=fake()).values()))

    def test_backup_failed_is_red_even_when_pending_allowed(self):
        f = fake({"/api/v1/health": (200, b'{"healthy": true, "backup": {"status": "failed"}}')})
        self.assertFalse(run(fetch=f, require_backup=False)["gateway_health"].ok)

    def test_backup_disabled_needs_flag(self):
        f = fake({"/api/v1/health": (200, b'{"healthy": true, "backup": {"status": "disabled"}}')})
        self.assertFalse(run(fetch=f)["gateway_health"].ok)
        self.assertTrue(run(fetch=f, require_backup=False)["gateway_health"].ok)

    def test_network_error_and_bad_status_are_failures_not_crashes(self):
        f = fake({"/readyz": OSError("refused"), "/og.png": (404, b"")})
        res = run(fetch=f)
        self.assertFalse(res["gateway_ready"].ok)
        self.assertFalse(res["site_og_image"].ok)

    def test_landing_without_checkout_links_fails(self):
        self.assertFalse(run(fetch=fake({"/": (200, b"KeyFlint")}))["site_landing"].ok)


if __name__ == "__main__":
    unittest.main()
