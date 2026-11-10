"""Pure-stdlib rotating post queue shared by daily_growth.py and CI feed generator."""

from __future__ import annotations

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
