"""Automated Daily Growth Engine, Mobile Pulse & Real-Time Lead Alerts.

Provides:
1. Real-time mobile notifications (Email + optional ntfy.sh push) when a user requests a trial,
   purchases a license, or tops up credits.
2. Live 24h & cumulative ecosystem metrics (`collect_pulse_metrics`).
3. Automated daily IndexNow search-engine ping + optional webhook/Dev.to syndication.
4. Daily Mobile Pulse Email to `OPS_ALERT_EMAIL` with live metrics and 1-tap mobile publishing
   intent links (X/Twitter ES & EN, LinkedIn, Reddit) so daily multi-platform distribution takes 1 tap.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
import json
import logging
from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.config import get_settings

logger = logging.getLogger("keyflint.growth")

INDEXNOW_KEY = "8f4e2a9c1b7d3e5f6a0c8b2d4e6f1a3b"

KEYFLINT_ECOSYSTEM_URLS = [
    "https://keyflint.dev/",
    "https://keyflint.dev/feed.xml",
    "https://keyflint.dev/guides/paid-mcp-server.html",
    "https://keyflint.dev/guides/migrate-from-smithery.html",
    "https://keyflint.dev/guides/oauth-mcp-server.html",
    "https://keyflint.dev/guides/mcp-monetization-stripe-x402.html",
]

DAILY_POST_QUEUE: list[dict[str, str]] = [
    {
        "topic": "CSV y Norma 43 a ContaSol / A3 / ContaPlus sin OCR",
        "url": "https://mcp.keyflint.dev/csv-a-contasol/",
        "x_es": (
            "Convertir un CSV del banco o un fichero Norma 43 (.n43) a ContaSol, A3 o ContaPlus "
            "no debería requerir plantillas manuales ni OCR que inventa importes.\n\n"
            "Arrastra el archivo, revisa la vista previa al instante y descarga el diario cuadrado:\n"
            "https://mcp.keyflint.dev/csv-a-contasol/"
        ),
        "x_en": (
            "Building paid MCP servers in 2026: we just shipped passwordless OAuth 2.1 (6-digit email OTP) "
            "+ offline Ed25519 license verification + atomic SQLite WAL credit metering.\n\n"
            "Architecture & open SDKs:\nhttps://keyflint.dev/guides/oauth-mcp-server.html"
        ),
        "linkedin_es": (
            "Muchos despachos y departamentos contables siguen perdiendo horas adaptando columnas de CSV bancarios "
            "o ficheros Norma 43 (.n43) para importarlos en ContaSol, A3 o Sage.\n\n"
            "En Flint by KeyFlint hemos lanzado el conversor directo CSV y Norma 43 a ContaSol / A3 / ContaPlus:\n"
            "• Vista previa instantánea en el navegador antes de gastar un solo crédito.\n"
            "• Cuadre aritmético céntimo a céntimo con Decimal (cero OCR, cero importes inventados).\n"
            "• Activación inmediata solo escribiendo tu correo (25 créditos de prueba incluidos).\n\n"
            "Pruébalo sin instalar nada: https://mcp.keyflint.dev/csv-a-contasol/"
        ),
        "reddit_title": "How we built passwordless OAuth 2.1 (6-digit OTP) + offline Ed25519 credit metering for remote MCP servers",
        "reddit_body": (
            "When shipping remote MCP servers for Claude Desktop and Cursor, copying long bearer tokens into JSON "
            "configs kills conversion. We solved it by combining OAuth 2.1 (RFC 8414 + PKCE) with a 6-digit email OTP "
            "and an Ed25519 token gateway (KeyFlint).\n\n"
            "Full technical write-up: https://keyflint.dev/guides/oauth-mcp-server.html\n"
            "Live hub with 5 production MCP servers + unified connector: https://mcp.keyflint.dev"
        ),
    },
    {
        "topic": "Conector único /despacho/mcp para Claude (17 herramientas contables)",
        "url": "https://mcp.keyflint.dev/asesorias/#conector",
        "x_es": (
            "Ya puedes conectar las 17 herramientas de Norma 43 + ContaBridge en Claude con una sola URL:\n"
            "https://mcp.keyflint.dev/despacho/mcp\n\n"
            "Sin archivos JSON ni claves largas: pegas la URL, introduces tu correo y el código de 6 dígitos. "
            "Guía: https://mcp.keyflint.dev/asesorias/#conector"
        ),
        "x_en": (
            "Why copy-pasting API keys into claude_desktop_config.json hurts conversion for non-technical users:\n\n"
            "With MCP OAuth 2.1 + 6-digit email OTP, users paste one URL (https://mcp.keyflint.dev/despacho/mcp), "
            "enter their email code, and get 17 metered tools instantly.\n\n"
            "https://keyflint.dev"
        ),
        "linkedin_es": (
            "Hasta hoy, conectar herramientas contables a Claude requería editar archivos JSON o copiar claves.\n\n"
            "Acabamos de lanzar el conector unificado de Flint para despachos (/despacho/mcp): una sola URL que reúne "
            "las 17 herramientas de conciliación bancaria Norma 43 y conversión a ContaSol, A3, Sage y ContaPlus.\n\n"
            "Solo pegas la URL en Claude, verificas tu correo con un código de 6 dígitos y empiezas a trabajar.\n"
            "Detalles aquí: https://mcp.keyflint.dev/asesorias/#conector"
        ),
        "reddit_title": "Show r/mcp: Single-URL OAuth 2.1 connector serving 17 deterministic accounting & banking tools",
        "reddit_body": (
            "We unified our banking (AEB Norma 43) and accounting journal MCP servers behind a single Cloudflare Worker + "
            "container gateway at https://mcp.keyflint.dev/despacho/mcp.\n\n"
            "Every tool call is metered atomically via KeyFlint (https://keyflint.dev) and automatically refunded if a tool raises or returns `isError: true`."
        ),
    },
    {
        "topic": "Veri*factu AEAT (RD 1007/2023) y validación de huella SHA-256",
        "url": "https://mcp.keyflint.dev/verifactu/",
        "x_es": (
            "¿Preparando Veri*factu (RD 1007/2023) o revisando XML Facturae 3.2.2?\n\n"
            "El servidor verifactu-mcp calcula y verifica el encadenamiento SHA-256 de registros de facturación, "
            "valida NIF/CIF y genera el código QR oficial de la AEAT:\n"
            "https://mcp.keyflint.dev/verifactu/"
        ),
        "x_en": (
            "If an MCP tool fails mid-execution, charging the user's credit balance destroys trust.\n\n"
            "In KeyFlint, `@kf.metered(credits=2)` debits atomically in SQLite WAL and triggers an automatic "
            "idempotent refund whenever the tool raises or returns `isError: true`.\n\n"
            "https://keyflint.dev/guides/paid-mcp-server.html"
        ),
        "linkedin_es": (
            "Con la entrada en vigor de Veri*factu (RD 1007/2023), cualquier error en el encadenamiento SHA-256 "
            "de las facturas o en la estructura Facturae 3.2.2 supone un riesgo directo.\n\n"
            "Nuestro servidor verifactu-mcp permite auditar cadenas de hashes AEAT, validar NIF/CIF/IBAN y "
            "generar URLs QR verificables tanto desde la web como desde Claude o Cursor:\n"
            "https://mcp.keyflint.dev/verifactu/"
        ),
        "reddit_title": "Why metered MCP servers need automatic refund circuit-breakers on `isError`",
        "reddit_body": (
            "LLMs frequently pass malformed arguments on the first tool call attempt. If your MCP billing layer "
            "charges per call without refunding failed executions, users burn credits on schema errors.\n\n"
            "Here is how we implemented idempotent debit + auto-refund with circuit breakers in KeyFlint: "
            "https://keyflint.dev/guides/mcp-monetization-stripe-x402.html"
        ),
    },
    {
        "topic": "KeyFlint vs SaaS de licencias: Ed25519 offline en < 1 ms",
        "url": "https://keyflint.dev/guides/mcp-monetization-stripe-x402.html",
        "x_es": (
            "Cómo monetizar un servidor MCP, CLI o API sin pagar comisiones por venta a terceros:\n\n"
            "KeyFlint emite licencias Ed25519 verificables offline en < 1 ms + cobro por créditos atómico en SQLite WAL "
            "conectado directo a tu Stripe.\n\n"
            "https://keyflint.dev"
        ),
        "x_en": (
            "Monetizing MCP servers in 2026: Stripe Checkout vs HTTP 402 vs Offline Ed25519 Licenses.\n\n"
            "We wrote an engineering breakdown based on running 5 production MCP servers on Cloudflare + Fly.io:\n"
            "https://keyflint.dev/guides/mcp-monetization-stripe-x402.html"
        ),
        "linkedin_es": (
            "Para desarrolladores creando herramientas de IA, servidores MCP o CLIs:\n\n"
            "KeyFlint (keyflint.dev) es nuestro gateway autoalojado de licencias criptográficas Ed25519 y "
            "contabilización de créditos por llamada.\n"
            "• Verificación offline en < 1 ms (SDKs MIT en Python, TypeScript y Go).\n"
            "• Webhooks firmados de Stripe y LemonSqueezy (0% comisión adicional).\n"
            "• Reembolso automático de créditos si una herramienta falla.\n\n"
            "Guía técnica completa: https://keyflint.dev/guides/mcp-monetization-stripe-x402.html"
        ),
        "reddit_title": "Comparing MCP server monetization models in 2026: Stripe Webhooks + Ed25519 vs HTTP 402",
        "reddit_body": (
            "We put together an engineering breakdown of the main ways to charge for MCP servers and CLIs right now, "
            "including offline Ed25519 verification vs online call-home, atomic credit metering, and OAuth 2.1 flows:\n\n"
            "https://keyflint.dev/guides/mcp-monetization-stripe-x402.html"
        ),
    },
    {
        "topic": "Conciliación bancaria determinista: Norma 43 CaixaBank, BBVA, Santander, Sabadell",
        "url": "https://mcp.keyflint.dev/lote/",
        "x_es": (
            "Un LLM nunca debe sumar ni cuadrar un extracto bancario a ojo.\n\n"
            "En Flint, el parser Norma 43 comprueba al céntimo que Saldo Inicial + Haber − Debe = Saldo Final "
            "para CaixaBank, BBVA, Santander, Sabadell y Bankinter antes de exportar a Excel o ContaSol:\n"
            "https://mcp.keyflint.dev/lote/"
        ),
        "x_en": (
            "Rule #1 of financial AI tools: never let the LLM do the math.\n\n"
            "Our accounting MCP servers parse bank statements using integer-cent math, verify opening/closing "
            "balances to the cent, and let Claude focus on orchestration and reporting.\n\n"
            "Live at https://mcp.keyflint.dev"
        ),
        "linkedin_es": (
            "¿Por qué falla la IA genérica en contabilidad? Porque un modelo de lenguaje predice texto, no cuadra saldos.\n\n"
            "En Flint by KeyFlint separamos responsabilidades: el motor determinista valida el fichero Norma 43 o CSV "
            "al céntimo y genera el asiento exacto para ContaSol, A3 o Sage, "
            "mientras Claude te asiste en lenguaje natural.\n\n"
            "Pruébalo en el navegador con 25 créditos gratis: https://mcp.keyflint.dev/lote/"
        ),
        "reddit_title": "Deterministic financial MCP servers: why the tool must own integer-cent math and balance assertions",
        "reddit_body": (
            "When we built Flint (https://mcp.keyflint.dev) for Spanish accounting firms, our core design rule was "
            "zero arithmetic inside the LLM prompt. Every Norma 43 bank statement is checked with "
            "integer-cent arithmetic and balance assertions inside the MCP tool before returning structured output."
        ),
    },
    {
        "topic": "Extractos bancarios en PDF digital directo a diario contable (ContaBridge v0.4.0)",
        "url": "https://mcp.keyflint.dev/csv-a-contasol/",
        "x_es": (
            "¿Te pasan extractos del banco en PDF digital en lugar de Norma 43?\n\n"
            "ContaBridge 0.4.0 extrae las tablas sin OCR inventado, comprueba el saldo línea por línea y exporta el asiento para ContaSol, A3 o Sage:\n"
            "https://mcp.keyflint.dev/csv-a-contasol/"
        ),
        "x_en": (
            "Just released `contabridge-mcp` v0.4.0 to PyPI and the Official MCP Registry: deterministic digital bank PDF "
            "statement parsing without OCR hallucinations, line-by-line balance checks, and auto-refund on failure.\n\n"
            "https://github.com/ArceeDev/contabridge-mcp"
        ),
        "linkedin_es": (
            "Uno de los cuellos de botella en cualquier asesoría es recibir un extracto bancario en PDF digital cuando el cliente no descarga el Norma 43.\n\n"
            "Acabamos de lanzar contabridge-mcp 0.4.0: extrae movimientos de PDFs digitales leyendo el texto del documento (sin OCR ni IA generativa), comprueba saldo anterior + movimiento = saldo impreso en cada línea y genera el APU.ods o SUENLACE.DAT.\n\n"
            "Disponible en PyPI y en el procesador web: https://mcp.keyflint.dev/csv-a-contasol/"
        ),
        "reddit_title": "Why we avoided OCR and LLM vision for bank statement PDF extraction in our MCP server (contabridge-mcp 0.4.0)",
        "reddit_body": (
            "Using multimodal LLMs to read bank statement PDFs risks silent digit errors. In `contabridge-mcp` 0.4.0, "
            "we built a deterministic table parser using pypdf layout mode that refuses scanned PDFs without charging credits and "
            "checks `previous_balance + amount == printed_balance` on every row.\n\n"
            "Code & PyPI package: https://github.com/ArceeDev/contabridge-mcp"
        ),
    },
    {
        "topic": "Revolut, Stripe y PayPal a diario contable ContaSol / A3",
        "url": "https://mcp.keyflint.dev/revolut-a-contasol/",
        "x_es": (
            "Pasa tus extractos CSV de Revolut, Stripe o PayPal al diario de ContaSol o A3 con cuadre verificable y vista previa gratis:\n"
            "https://mcp.keyflint.dev/revolut-a-contasol/\n"
            "https://mcp.keyflint.dev/stripe-a-contasol/"
        ),
        "x_en": (
            "Accountants spend hours cleaning Revolut, Stripe, and PayPal CSV exports before importing into ERPs.\n\n"
            "Our ContaBridge web & MCP pipeline maps net amounts, fees, and dates deterministically into ERP journal entries:\n"
            "https://mcp.keyflint.dev/en/"
        ),
        "linkedin_es": (
            "Muchos ecommerce y startups operan con Revolut, Stripe o PayPal, pero sus exportaciones CSV traen importes netos, comisiones y formatos en inglés difíciles de importar en ContaSol o A3.\n\n"
            "Hemos publicado guías y convertidores dedicados para transformar cada fichero en asientos listos para importar:\n"
            "• Revolut: https://mcp.keyflint.dev/revolut-a-contasol/\n"
            "• Stripe: https://mcp.keyflint.dev/stripe-a-contasol/\n"
            "• PayPal: https://mcp.keyflint.dev/paypal-a-contasol/"
        ),
        "reddit_title": "Converting Stripe, PayPal and Revolut CSV exports deterministically into accounting journal entries",
        "reddit_body": (
            "We added header-priority column matching for Revolut, Stripe, and PayPal exports in `contabridge-mcp` + live web batch "
            "conversion at https://mcp.keyflint.dev/stripe-a-contasol/. Reverted or pending rows are skipped and listed separately."
        ),
    },
    {
        "topic": "Envuelve cualquier servidor MCP stdio de pago con KeyFlint",
        "url": "https://keyflint.dev/guides/paid-mcp-server.html",
        "x_es": (
            "¿Tienes un servidor MCP y quieres cobrar por uso o por licencia sin reescribir tu infraestructura?\n\n"
            "Protege tus herramientas en minutos con keyflint-verify en Python, TypeScript o Go:\n"
            "https://keyflint.dev/guides/paid-mcp-server.html"
        ),
        "x_en": (
            "Want to gate an existing MCP server with Ed25519 licenses and per-tool credits in one self-hosted Docker container?\n\n"
            "Read the step-by-step guide with Python, TypeScript, and Go verification SDKs:\n"
            "https://keyflint.dev/guides/paid-mcp-server.html"
        ),
        "linkedin_es": (
            "Si ya construiste un servidor MCP para Claude Desktop, Cursor o VS Code, no necesitas programar un sistema completo de Stripe, webhooks y contadores de saldo desde cero.\n\n"
            "Con KeyFlint despliegas un único contenedor Docker con SQLite WAL y proteges tus herramientas en Python (`keyflint-verify`), TypeScript o Go en minutos.\n\n"
            "Guía paso a paso: https://keyflint.dev/guides/paid-mcp-server.html"
        ),
        "reddit_title": "Ship paid local & remote MCP servers using SQLite WAL + offline Ed25519 signatures (MIT SDKs + self-hosted gateway)",
        "reddit_body": (
            "We open-sourced the verification SDKs for Python, TypeScript, and Go with 50 shared conformance test vectors "
            "so CLI and MCP developers can enforce licenses offline and meter heavy tool calls atomically.\n\n"
            "Full walkthrough: https://keyflint.dev/guides/paid-mcp-server.html"
        ),
    },
    {
        "topic": "Carpeta vigilada para asesorías: procesa extractos en local automáticamente",
        "url": "https://mcp.keyflint.dev/asesorias/",
        "x_es": (
            "Si recibes decenas de ficheros .n43 al mes en tu asesoría, deja una carpeta vigilada con Flint:\n\n"
            "Guardas el extracto de cada cliente en su subcarpeta y en segundos tienes el Excel y el informe auditable al lado:\n"
            "https://mcp.keyflint.dev/asesorias/"
        ),
        "x_en": (
            "For teams automating high-volume bank reconciliation: Flint's watch-folder script processes every incoming statement "
            "dropped into a folder with strict audit logs (`.flint.json`) and idempotent credit billing.\n\n"
            "https://mcp.keyflint.dev/asesorias/"
        ),
        "linkedin_es": (
            "En despachos con decenas de clientes, abrir un conversor web archivo por archivo sigue quitando tiempo.\n\n"
            "Con un solo comando en Windows (PowerShell) o macOS/Linux, Flint crea una carpeta vigilada que procesa automáticamente cada extracto que guardas dentro, incluso tras reiniciar el equipo.\n\n"
            "Conoce el flujo para asesorías: https://mcp.keyflint.dev/asesorias/"
        ),
        "reddit_title": "Folder watcher + remote MCP hub: letting non-technical accounting teams process bank files cleanly",
        "reddit_body": (
            "Non-technical staff prefer dropping files into a folder over pasting prompts. Our lightweight watch script processes "
            "statements idempotently and produces deterministic CSV/journal exports alongside `.flint.json` audit reports: https://mcp.keyflint.dev/asesorias/"
        ),
    },
    {
        "topic": "Limpieza determinista de CSV antes de analizar con IA (dataclean-mcp)",
        "url": "https://mcp.keyflint.dev/dataclean/",
        "x_es": (
            "Antes de pasar un CSV sucio a un LLM o a tu ERP, límpialo de forma determinista con dataclean-mcp:\n"
            "fechas homogéneas, separadores europeos, duplicados y detección de esquemas sin alucinaciones:\n"
            "https://mcp.keyflint.dev/dataclean/"
        ),
        "x_en": (
            "Clean messy CSV/JSON tables deterministically inside Claude or Cursor before your agent writes code against broken columns.\n\n"
            "Explore `dataclean-mcp` (PyPI + remote OAuth MCP):\n"
            "https://mcp.keyflint.dev/dataclean/"
        ),
        "linkedin_es": (
            "Los ficheros CSV con comas decimales europeas, codificaciones rotas (CP1252/Latin-1) y filas duplicadas hacen perder tiempo tanto a analistas como a agentes de IA.\n\n"
            "`dataclean-mcp` normaliza esquemas, fechas e importes con reglas deterministas desde tu asistente de IA o navegador:\n"
            "https://mcp.keyflint.dev/dataclean/"
        ),
        "reddit_title": "DataClean MCP: deterministic European CSV normalization, deduplication and schema profiling for coding agents",
        "reddit_body": (
            "Published `dataclean-mcp` as both a local stdio PyPI package and a hosted Streamable HTTP MCP server so agents inspect and sanitize ugly spreadsheets reliably.\n\n"
            "Docs & live status: https://mcp.keyflint.dev/dataclean/"
        ),
    },
    {
        "topic": "Extracción web en Markdown limpio y auditoría SEO para agentes (web-intel-mcp)",
        "url": "https://mcp.keyflint.dev/web-intel/",
        "x_es": (
            "Web-Intel MCP convierte cualquier URL en Markdown limpio, extrae enlaces/metadatos y ejecuta auditorías SEO técnicas para tu agente:\n"
            "https://mcp.keyflint.dev/web-intel/"
        ),
        "x_en": (
            "Stop burning context windows on raw HTML tags. `web-intel-mcp` turns any URL into clean Markdown, structured metadata, and technical SEO checks.\n\n"
            "Try 25 free credits: https://mcp.keyflint.dev/web-intel/"
        ),
        "linkedin_es": (
            "Cuando conectas un agente a internet, el HTML crudo consume tokens y rompe el razonamiento.\n\n"
            "`web-intel-mcp` extrae contenido principal en Markdown limpio, inventario de enlaces, OpenGraph/JSON-LD y auditoría SEO lista para Claude, Cursor o Windsurf:\n"
            "https://mcp.keyflint.dev/web-intel/"
        ),
        "reddit_title": "Web-Intel MCP: clean Markdown, link extraction, stack detection and SEO checks in one toolset",
        "reddit_body": (
            "Built `web-intel-mcp` (`pip install web-intel-mcp` or remote via `https://mcp.keyflint.dev/web-intel/mcp`) with a free live URL reader on the landing page.\n\n"
            "Try it live: https://mcp.keyflint.dev/web-intel/"
        ),
    },
    {
        "topic": "SDK de verificación KeyFlint en Go, Python y TypeScript con 50 vectores compartidos",
        "url": "https://keyflint.dev/",
        "x_es": (
            "Python, TypeScript y Go verificando las mismas licencias Ed25519 en < 1 ms sin conexión y con 50 vectores de conformidad compartidos:\n"
            "https://keyflint.dev/"
        ),
        "x_en": (
            "Cross-language cryptographic licensing shouldn't drift between Python, TypeScript, and Go.\n\n"
            "All three KeyFlint verifiers share 50 conformance vectors + `kid` key rotation without invalidating active tokens:\n"
            "https://keyflint.dev/"
        ),
        "linkedin_es": (
            "Cuando distribuyes SDKs o CLIs en varios lenguajes, mantener idéntica la validación de licencias es crítico.\n\n"
            "KeyFlint v1.2 ofrece verificadores MIT en Python, TypeScript y Go probados frente a 50 vectores criptográficos compartidos (Ed25519 con rotación `kid`), bloqueo por nodo/dominio y pasarela SQLite WAL.\n\n"
            "Explora la consola interactiva en vivo: https://keyflint.dev/"
        ),
        "reddit_title": "Open-source MIT license verifiers for Python, TypeScript and Go tested against 50 shared Ed25519 conformance vectors",
        "reddit_body": (
            "We built KeyFlint (https://keyflint.dev) so any tool author can verify Ed25519 tokens locally in under 1 ms while metering heavy operations against a single SQLite WAL Docker gateway.\n\n"
            "Includes Stripe/LemonSqueezy webhook provisioning, key rotation (`kid`), and 50 cross-language vectors."
        ),
    },
]


def _ensure_pulse_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS growth_pulse_log (
            day_utc TEXT PRIMARY KEY,
            sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            details_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )


def get_daily_post(now: Optional[datetime] = None) -> dict[str, Any]:
    """Selects today's rotating post pack and builds 1-tap mobile intent links."""
    now = now or datetime.now(timezone.utc)
    day_index = now.timetuple().tm_yday % len(DAILY_POST_QUEUE)
    item = dict(DAILY_POST_QUEUE[day_index])
    item["day_index"] = day_index + 1
    item["total_in_queue"] = len(DAILY_POST_QUEUE)
    item["x_es_intent"] = f"https://x.com/intent/tweet?text={quote(item['x_es'])}"
    item["x_en_intent"] = f"https://x.com/intent/tweet?text={quote(item['x_en'])}"
    item["linkedin_intent"] = f"https://www.linkedin.com/feed/?shareActive=true&text={quote(item['linkedin_es'])}"
    item["reddit_intent"] = (
        f"https://www.reddit.com/submit?title={quote(item['reddit_title'])}&text={quote(item['reddit_body'])}"
    )
    return item


def collect_pulse_metrics(conn: Any, now: Optional[datetime] = None) -> dict[str, Any]:
    """Queries live 24h and total metrics from the KeyFlint SQLite database."""
    now = now or datetime.now(timezone.utc)
    since_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    customers_total = int(conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0])
    customers_24h = int(
        conn.execute("SELECT COUNT(*) FROM customers WHERE created_at >= ?", (since_24h,)).fetchone()[0]
    )

    tier_rows = conn.execute(
        "SELECT tier, COUNT(*) AS cnt FROM licenses WHERE status = 'active' GROUP BY tier"
    ).fetchall()
    active_by_tier = {str(r["tier"]): int(r["cnt"]) for r in tier_rows}

    lic_24h_rows = conn.execute(
        "SELECT tier, metadata_json FROM licenses WHERE created_at >= ?", (since_24h,)
    ).fetchall()
    trials_24h = 0
    paid_24h = 0
    for r in lic_24h_rows:
        meta = json.loads(r["metadata_json"] or "{}")
        if r["tier"] == "community" or meta.get("trial"):
            trials_24h += 1
        else:
            paid_24h += 1

    usage_24h_row = conn.execute(
        """
        SELECT COUNT(*) AS calls, COALESCE(SUM(CASE WHEN credits_consumed > 0 THEN credits_consumed ELSE 0 END), 0) AS credits
        FROM usage_events
        WHERE timestamp >= ?
        """,
        (since_24h,),
    ).fetchone()
    tool_calls_24h = int(usage_24h_row["calls"] or 0)
    credits_consumed_24h = int(usage_24h_row["credits"] or 0)

    usage_total_row = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(CASE WHEN credits_consumed > 0 THEN credits_consumed ELSE 0 END), 0) AS credits FROM usage_events"
    ).fetchone()
    tool_calls_total = int(usage_total_row["calls"] or 0)
    credits_consumed_total = int(usage_total_row["credits"] or 0)

    top_events_rows = conn.execute(
        """
        SELECT event_type, COUNT(*) AS calls, COALESCE(SUM(credits_consumed), 0) AS credits
        FROM usage_events
        WHERE timestamp >= ?
        GROUP BY event_type
        ORDER BY calls DESC
        LIMIT 8
        """,
        (since_24h,),
    ).fetchall()
    top_events_24h = [
        {"event_type": str(r["event_type"]), "calls": int(r["calls"]), "credits": int(r["credits"])}
        for r in top_events_rows
    ]

    recent_rows = conn.execute(
        """
        SELECT c.email, l.tier, l.status, l.created_at, l.metadata_json,
               COALESCE(q.balance, 0) AS balance, COALESCE(q.consumed, 0) AS consumed
        FROM licenses l
        JOIN customers c ON c.id = l.customer_id
        LEFT JOIN quotas q ON q.license_id = l.id
        ORDER BY l.created_at DESC
        LIMIT 10
        """
    ).fetchall()
    recent_customers = []
    for r in recent_rows:
        meta = json.loads(r["metadata_json"] or "{}")
        recent_customers.append(
            {
                "email": str(r["email"]),
                "tier": str(r["tier"]),
                "status": str(r["status"]),
                "source": meta.get("source") or ("trial" if meta.get("trial") else "direct"),
                "balance": int(r["balance"]),
                "consumed": int(r["consumed"]),
                "created_at": str(r["created_at"]),
            }
        )

    return {
        "generated_at": now.isoformat(),
        "customers_total": customers_total,
        "customers_24h": customers_24h,
        "trials_24h": trials_24h,
        "paid_24h": paid_24h,
        "active_by_tier": active_by_tier,
        "tool_calls_24h": tool_calls_24h,
        "credits_consumed_24h": credits_consumed_24h,
        "tool_calls_total": tool_calls_total,
        "credits_consumed_total": credits_consumed_total,
        "top_events_24h": top_events_24h,
        "recent_customers": recent_customers,
        "daily_post": get_daily_post(now),
    }


def notify_ntfy(title: str, message: str, click_url: str = "https://mcp.keyflint.dev/estado/") -> bool:
    """Sends a lockscreen push via ntfy.sh if NTFY_TOPIC is set.

    ntfy.sh topics are public to anyone who knows the name: never pass personal data (emails, keys) here.
    JSON publish keeps UTF-8 titles intact (HTTP headers are latin-1 only).
    """
    topic = (get_settings().NTFY_TOPIC or "").strip()
    if not topic:
        return False
    try:
        resp = httpx.post(
            "https://ntfy.sh/",
            json={"topic": topic, "title": title[:120], "message": message[:1000], "click": click_url},
            timeout=5.0,
        )
        return resp.status_code < 300
    except Exception as exc:
        logger.warning("ntfy push failed: %s", type(exc).__name__)
        return False


def send_owner_activity_alert(
    email_sender: Any,
    kind: str,
    title: str,
    **details: Any,
) -> bool:
    """Sends an instant mobile alert to OPS_ALERT_EMAIL (and ntfy.sh) on new trial, purchase or top-up."""
    settings = get_settings()
    if not settings.LEAD_ALERT_ENABLED:
        return False
    lines = [f"{k}: {v}" for k, v in details.items() if v is not None]
    text_body = f"{title}\n\n" + "\n".join(lines) + "\n\nEstado en vivo: https://mcp.keyflint.dev/estado/\n"
    # Push sin datos personales: el detalle (correo, sesión) solo va al correo del propietario.
    notify_ntfy(f"[{kind}] KeyFlint", title if "@" not in title else kind)

    to = (settings.OPS_ALERT_EMAIL or "").strip()
    if not to or email_sender is None:
        return False

    esc = html.escape
    rows_html = "".join(
        f'<tr><td style="padding:8px 0;border-bottom:1px solid #1E233D;color:#8E95AF;font-size:13px;">{esc(str(k))}</td>'
        f'<td align="right" style="padding:8px 0;border-bottom:1px solid #1E233D;color:#FFFFFF;font-weight:600;font-size:13px;">{esc(str(v))}</td></tr>'
        for k, v in details.items()
        if v is not None
    )
    html_body = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body bgcolor="#0B0D17" style="margin:0;padding:16px;background:#0B0D17;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;color:#FFFFFF;">
  <div style="max-width:520px;margin:0 auto;background:#111424;border:1px solid #1E233D;border-radius:12px;padding:24px;">
    <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#CCFF00;margin-bottom:6px;">KeyFlint · {esc(kind)}</div>
    <h1 style="margin:0 0 16px 0;font-size:20px;color:#FFFFFF;line-height:1.3;">{esc(title)}</h1>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:20px;">{rows_html}</table>
    <a href="https://mcp.keyflint.dev/estado/" style="display:block;text-align:center;background:#CCFF00;color:#0B0D17;font-weight:700;font-size:14px;text-decoration:none;padding:12px 16px;border-radius:8px;">Ver estado del ecosistema</a>
  </div>
</body></html>"""
    try:
        return bool(
            email_sender._dispatch(
                recipient=to,
                subject=f"[KeyFlint {kind}] {title}",
                text_body=text_body,
                html_body=html_body,
            )
        )
    except Exception as exc:
        logger.warning("Owner activity alert failed: %s", exc)
        return False


def ping_indexnow() -> dict[str, Any]:
    """Submits keyflint.dev URLs to IndexNow so Bing, ChatGPT Search, and DuckDuckGo index updates daily."""
    payload = {
        "host": "keyflint.dev",
        "key": INDEXNOW_KEY,
        "keyLocation": f"https://keyflint.dev/{INDEXNOW_KEY}.txt",
        "urlList": KEYFLINT_ECOSYSTEM_URLS,
    }
    try:
        resp = httpx.post(
            "https://api.indexnow.org/indexnow",
            json=payload,
            timeout=8.0,
        )
        return {"ok": resp.status_code in (200, 202), "status_code": resp.status_code}
    except Exception as exc:
        logger.warning("IndexNow ping failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def syndicate_external(pulse: dict[str, Any]) -> dict[str, Any]:
    """Dispatches today's post to optional connected webhooks (Make/Zapier/n8n/Discord)."""
    settings = get_settings()
    out: dict[str, Any] = {"webhook": False}
    webhook_url = (settings.SOCIAL_WEBHOOK_URL or "").strip()
    if webhook_url:
        try:
            resp = httpx.post(
                webhook_url,
                json={
                    "source": "keyflint-daily-growth",
                    "generated_at": pulse["generated_at"],
                    "metrics_24h": {
                        "trials_24h": pulse["trials_24h"],
                        "paid_24h": pulse["paid_24h"],
                        "tool_calls_24h": pulse["tool_calls_24h"],
                        "credits_consumed_24h": pulse["credits_consumed_24h"],
                    },
                    "post": pulse["daily_post"],
                },
                timeout=8.0,
            )
            out["webhook"] = resp.status_code < 300
        except Exception as exc:
            logger.warning("Social webhook syndication failed: %s", exc)
    return out


def render_daily_pulse_email(pulse: dict[str, Any]) -> tuple[str, str, str]:
    """Returns (subject, text_body, html_body) for the Daily Mobile Pulse & 1-Tap Social Pack."""
    post = pulse["daily_post"]
    t24 = pulse["trials_24h"]
    p24 = pulse["paid_24h"]
    c24 = pulse["tool_calls_24h"]
    cr24 = pulse["credits_consumed_24h"]

    subject = (
        f"[KeyFlint Pulso] +{t24} solicitudes · {c24} llamadas (24h) · Post #{post['day_index']}: {post['topic'][:38]}"
    )

    recent_lines = [
        f"- {c['email']} ({c['tier']} · {c['source']} · {c['consumed']} cr usados / {c['balance']} disp.)"
        for c in pulse["recent_customers"][:6]
    ] or ["- Sin registros recientes"]

    text_body = (
        f"PULSO DIARIO KEYFLINT & FLINT (24h)\n"
        f"==================================\n"
        f"Nuevas solicitudes prueba (24h): {t24}\n"
        f"Nuevas compras/planes (24h): {p24}\n"
        f"Llamadas a herramientas (24h): {c24} ({cr24} créditos)\n"
        f"Clientes totales acumulados: {pulse['customers_total']}\n"
        f"Llamadas totales acumuladas: {pulse['tool_calls_total']} ({pulse['credits_consumed_total']} créditos)\n\n"
        f"ÚLTIMOS USUARIOS:\n" + "\n".join(recent_lines) + "\n\n"
        f"PUBLICACIÓN DEL DÍA (#{post['day_index']} - {post['topic']})\n"
        f"----------------------------------\n"
        f"Publicar en X (ES) en 1 toque:\n{post['x_es_intent']}\n\n"
        f"Publicar en X (EN) en 1 toque:\n{post['x_en_intent']}\n\n"
        f"Publicar en LinkedIn en 1 toque:\n{post['linkedin_intent']}\n\n"
        f"Publicar en Reddit en 1 toque:\n{post['reddit_intent']}\n"
    )

    esc = html.escape
    recent_rows_html = "".join(
        f'<tr>'
        f'<td style="padding:8px 0;border-bottom:1px solid #1E233D;color:#FFFFFF;font-size:12px;">{esc(c["email"])}</td>'
        f'<td style="padding:8px 4px;border-bottom:1px solid #1E233D;color:#CCFF00;font-size:11px;font-family:monospace;">{esc(c["tier"])}</td>'
        f'<td align="right" style="padding:8px 0;border-bottom:1px solid #1E233D;color:#8E95AF;font-size:12px;">{c["consumed"]} us. / {c["balance"]} disp.</td>'
        f'</tr>'
        for c in pulse["recent_customers"][:6]
    ) or '<tr><td colspan="3" style="padding:8px 0;color:#8E95AF;font-size:12px;">Sin actividad registrada</td></tr>'

    html_body = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="dark only">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(subject)}</title>
</head>
<body bgcolor="#0B0D17" style="margin:0;padding:16px 8px;background-color:#0B0D17;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Roboto,sans-serif;color:#FFFFFF;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:580px;margin:0 auto;background-color:#111424;border:1px solid #1E233D;border-radius:14px;">
    <tr>
      <td style="padding:28px 20px;">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#CCFF00;margin-bottom:6px;">KeyFlint &amp; Flint · Pulso Móvil Diario</div>
        <h1 style="margin:0 0 18px 0;font-size:22px;font-weight:700;color:#FFFFFF;line-height:1.25;">Solicitudes, uso en vivo y <span style="color:#CCFF00;">publicación en 1 toque</span></h1>

        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#171B30;border:1px solid #282F50;border-radius:10px;padding:14px;margin-bottom:20px;">
          <tr>
            <td width="50%" style="padding:6px 8px;border-right:1px solid #232944;border-bottom:1px solid #232944;">
              <div style="font-size:11px;color:#8E95AF;">Solicitudes prueba (24h)</div>
              <div style="font-size:22px;font-weight:800;color:#CCFF00;margin-top:2px;">+{t24}</div>
            </td>
            <td width="50%" style="padding:6px 12px;border-bottom:1px solid #232944;">
              <div style="font-size:11px;color:#8E95AF;">Llamadas MCP / Web (24h)</div>
              <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-top:2px;">{c24} <span style="font-size:12px;color:#8E95AF;font-weight:500;">({cr24} cr)</span></div>
            </td>
          </tr>
          <tr>
            <td width="50%" style="padding:10px 8px 4px 8px;border-right:1px solid #232944;">
              <div style="font-size:11px;color:#8E95AF;">Clientes acumulados</div>
              <div style="font-size:18px;font-weight:700;color:#FFFFFF;margin-top:2px;">{pulse['customers_total']} <span style="font-size:11px;color:#CCFF00;">(+{p24} pagos 24h)</span></div>
            </td>
            <td width="50%" style="padding:10px 12px 4px 12px;">
              <div style="font-size:11px;color:#8E95AF;">Uso total acumulado</div>
              <div style="font-size:18px;font-weight:700;color:#FFFFFF;margin-top:2px;">{pulse['tool_calls_total']} <span style="font-size:12px;color:#8E95AF;font-weight:500;">({pulse['credits_consumed_total']} cr)</span></div>
            </td>
          </tr>
        </table>

        <div style="font-size:12px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;color:#8E95AF;margin-bottom:8px;">Últimas solicitudes y licencias</div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:24px;">
          {recent_rows_html}
        </table>

        <div style="background:#171B30;border:1px solid #282F50;border-radius:10px;padding:18px;margin-bottom:20px;">
          <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#CCFF00;margin-bottom:4px;">Publicación del día #{post['day_index']} de {post['total_in_queue']}</div>
          <div style="font-size:16px;font-weight:700;color:#FFFFFF;margin-bottom:12px;">{esc(post['topic'])}</div>

          <div style="font-size:11px;color:#8E95AF;margin-bottom:4px;">Texto listo para X / Redes (Español):</div>
          <pre style="margin:0 0 12px 0;padding:10px;background:#0B0D17;border:1px solid #1E233D;border-radius:6px;color:#E6E8EF;font-size:12px;white-space:pre-wrap;font-family:ui-monospace,monospace;">{esc(post['x_es'])}</pre>

          <div style="font-size:11px;color:#8E95AF;margin-bottom:4px;">Texto listo para X / HN / Dev (English):</div>
          <pre style="margin:0 0 16px 0;padding:10px;background:#0B0D17;border:1px solid #1E233D;border-radius:6px;color:#E6E8EF;font-size:12px;white-space:pre-wrap;font-family:ui-monospace,monospace;">{esc(post['x_en'])}</pre>

          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td style="padding-bottom:8px;">
                <a href="{esc(post['x_es_intent'], quote=True)}" style="display:block;text-align:center;background:#CCFF00;color:#0B0D17;font-size:13px;font-weight:700;text-decoration:none;padding:11px 14px;border-radius:8px;">Publicar en X (Español) en 1 toque</a>
              </td>
            </tr>
            <tr>
              <td style="padding-bottom:8px;">
                <a href="{esc(post['x_en_intent'], quote=True)}" style="display:block;text-align:center;background:#0B0D17;color:#CCFF00;border:1px solid #CCFF00;font-size:13px;font-weight:700;text-decoration:none;padding:11px 14px;border-radius:8px;">Post on X (English) in 1 tap</a>
              </td>
            </tr>
            <tr>
              <td style="padding-bottom:8px;">
                <a href="{esc(post['linkedin_intent'], quote=True)}" style="display:block;text-align:center;background:#0B0D17;color:#FFFFFF;border:1px solid #282F50;font-size:13px;font-weight:600;text-decoration:none;padding:10px 14px;border-radius:8px;">Publicar en LinkedIn en 1 toque</a>
              </td>
            </tr>
            <tr>
              <td>
                <a href="{esc(post['reddit_intent'], quote=True)}" style="display:block;text-align:center;background:#0B0D17;color:#FFFFFF;border:1px solid #282F50;font-size:13px;font-weight:600;text-decoration:none;padding:10px 14px;border-radius:8px;">Publicar en Reddit en 1 toque</a>
              </td>
            </tr>
          </table>
        </div>

        <div style="text-align:center;font-size:12px;color:#8E95AF;">
          <a href="https://mcp.keyflint.dev/estado/" style="color:#CCFF00;text-decoration:none;font-weight:600;">Estado MCP Hub</a> &nbsp;·&nbsp;
          <a href="https://keyflint.dev/" style="color:#CCFF00;text-decoration:none;font-weight:600;">KeyFlint.dev</a>
        </div>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return subject, text_body, html_body


def run_daily_growth(
    conn: Any,
    email_sender: Any,
    *,
    force: bool = False,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Executes the daily growth cycle (metrics + IndexNow + syndication + mobile pulse email)."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    if not force:
        if not settings.DAILY_PULSE_ENABLED:
            return {"status": "disabled"}
        if now.hour < settings.DAILY_PULSE_HOUR_UTC:
            return {"status": "waiting_for_hour", "target_hour_utc": settings.DAILY_PULSE_HOUR_UTC}

    _ensure_pulse_table(conn)
    day_utc = now.strftime("%Y-%m-%d")
    if not force:
        existing = conn.execute("SELECT 1 FROM growth_pulse_log WHERE day_utc = ?", (day_utc,)).fetchone()
        if existing is not None:
            return {"status": "already_sent_today", "day_utc": day_utc}

    pulse = collect_pulse_metrics(conn, now=now)
    indexnow_res = ping_indexnow()
    syndication_res = syndicate_external(pulse)

    email_sent = False
    to = (settings.OPS_ALERT_EMAIL or "").strip()
    if to and email_sender is not None:
        subject, text_body, html_body = render_daily_pulse_email(pulse)
        try:
            email_sent = bool(
                email_sender._dispatch(
                    recipient=to,
                    subject=subject,
                    text_body=text_body,
                    html_body=html_body,
                )
            )
        except Exception as exc:
            logger.error("Daily pulse email failed: %s", exc)

    notify_ntfy(
        f"Pulso KeyFlint: +{pulse['trials_24h']} pruebas, {pulse['tool_calls_24h']} llamadas",
        f"Post de hoy listo en tu correo: {pulse['daily_post']['topic']}",
    )

    summary = {
        "status": "sent" if email_sent else "completed_no_email",
        "day_utc": day_utc,
        "email_sent": email_sent,
        "indexnow": indexnow_res,
        "syndication": syndication_res,
        "metrics_24h": {
            "customers_24h": pulse["customers_24h"],
            "trials_24h": pulse["trials_24h"],
            "paid_24h": pulse["paid_24h"],
            "tool_calls_24h": pulse["tool_calls_24h"],
            "credits_consumed_24h": pulse["credits_consumed_24h"],
        },
        "daily_post_topic": pulse["daily_post"]["topic"],
    }

    conn.execute(
        "INSERT OR REPLACE INTO growth_pulse_log (day_utc, sent_at, details_json) VALUES (?, ?, ?)",
        (day_utc, now.isoformat(), json.dumps(summary)),
    )
    conn.commit()
    return summary
