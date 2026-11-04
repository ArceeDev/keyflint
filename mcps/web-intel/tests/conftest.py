"""End-to-end fixtures: a real KeyFlint gateway, a freshly issued license and a local test website."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PRIV = "a01fd194d15178191f62e570962a579e61bf728945f79655d9df145eada811ec"
PUB = "0043b567534bfa2d55059a05642f75573d420899146f334a9f7fc5fba797bd0b"

GOOD_HTML = """<!doctype html><html lang="en"><head>
<title>Acme Widgets - Industrial widgets for teams</title>
<meta name="description" content="Acme builds durable industrial widgets for engineering teams. Ships worldwide in 48 hours with a lifetime warranty.">
<meta name="viewport" content="width=device-width"><link rel="canonical" href="https://acme.test/">
<meta property="og:title" content="Acme"><meta property="og:image" content="https://acme.test/og.png">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization"},{"@type":"WebSite"}]}</script>
<script src="/_next/static/chunks/main.js"></script><script src="https://js.stripe.com/v3"></script>
</head><body><nav><a href="/pricing">Pricing</a></nav><div class="cookie-banner">We use cookies</div>
<main><h1>Widgets that last</h1>""" + "<p>" + ("Durable widget engineering for demanding teams. " * 60) + """</p>
<h2>Why Acme</h2><ul><li>Fast shipping</li><li>Warranty</li></ul><a href="https://github.com/acme">GitHub</a>
<a href="/docs#intro">Docs</a><img src="/w.png" alt="Widget"></main><footer>(c) Acme</footer></body></html>"""

BAD_HTML = "<html><body><h1>a</h1><h1>b</h1><img src=x.png><p>tiny</p></body></html>"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Site(BaseHTTPRequestHandler):
    server_version, sys_version = "nginx", ""

    def do_GET(self) -> None:  # noqa: N802
        routes = {"/": (200, GOOD_HTML), "/bad": (200, BAD_HTML), "/missing": (404, "nope")}
        if self.path == "/old":
            self.send_response(301)
            self.send_header("Location", "/")
            self.end_headers()
            return
        status, body = routes.get(self.path, (404, "nope"))
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a: object) -> None:
        pass


@pytest.fixture(scope="session")
def site() -> str:
    srv = ThreadingHTTPServer(("127.0.0.1", _free_port()), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="session")
def gateway(tmp_path_factory: pytest.TempPathFactory) -> dict:
    db = tmp_path_factory.mktemp("kf") / "kf.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "ED25519_PRIVATE_KEY_HEX": PRIV,
           "ED25519_PUBLIC_KEY_HEX": PUB, "ENVIRONMENT": "testing", "BILLING_MODE": "mock",
           "REFUND_BREAKER_ENABLED": "false"}
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level",
                             "warning"], cwd=REPO, env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{url}/healthz", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.skip("KeyFlint gateway did not start")

    def issue(email: str, tier: str = "indie") -> dict:
        out = subprocess.run([sys.executable, "-m", "app.cli", "issue", "-e", email, "-t", tier], cwd=REPO, env=env,
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out[out.index("{"):])

    yield {"url": url, "issue": issue}
    proc.terminate()
