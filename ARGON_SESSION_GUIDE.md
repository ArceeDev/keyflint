# KeyForge v1.0.0 — Guía Operativa Multi-Sesión para Argon y Resumen Paso a Paso

> **Versión**: `1.0.0` | **Runtime**: Python 3.11+ (verificado en 3.14.8) | **Arquitectura**: Hexagonal / Clean | **Estado**: `7/7` Gates + `65/65` Tests E2E Aprobados

---

## 1. Propuesta de Valor y Nicho Monetizable

**KeyForge** es un gateway autoalojable de **licenciamiento criptográfico asimétrico (Ed25519 RFC 8032)** y **control atómico de cuotas por créditos** diseñado para un nicho de altísimo margen y baja competencia directa: creadores de servidores **MCP (Model Context Protocol)** de pago, agentes CLI locales, plugins de escritorio (DAW, CAD, trading, ciberseguridad) y micro-SaaS verticales de IA.

- **Ventaja económica**: Cero comisiones porcentuales sobre ingresos (frente al 5%-10% de wrappers SaaS) y coste de infraestructura mínimo (un único binario/proceso FastAPI + SQLite WAL soporta miles de validaciones por segundo en un VPS de $5/mes).
- **Ventaja técnica**: El cliente puede validar licencias **100% offline sin internet ni librerías C** copiando un único archivo estándar (`app/infrastructure/security/offline_validator.py`) o vía WebCrypto en navegador, y sincronizar cuotas online con protección `402 Payment Required` cuando necesita consumir créditos de API.

### Matriz Comercial Integrada (`Tier`)

| Plan | Precio Sugerido | Créditos / Ciclo | Asientos (`max_seats`) | Expiración | Capacidades Clave (`features`) |
|------|-----------------|------------------|------------------------|------------|--------------------------------|
| `community` | $0 / mes | 25 | 1 | 365 días | `core` |
| `pro` | $29 / mes | 500 | 3 | 365 días | `core`, `cli_offline`, `telemetry_sync` |
| `studio` | $89 / mes | 5.000 | 25 | 365 días | `core`, `cli_offline`, `telemetry_sync`, `multi_tenant`, `priority_webhook` |
| `lifetime` | $199 único | 10.000 | 3 | Perpetua (`None`) | `core`, `cli_offline`, `telemetry_sync`, `self_hosted` |

---

## 2. Resumen Cronológico Paso a Paso de Todo lo Construido y Endurecido

1. **Núcleo de Dominio Puro (`app/domain/`)**:
   - Entidades inmutables/optimizadas con `slots=True` (`Customer`, `License`, `Activation`, `QuotaLedger`) usando exclusivamente librería estándar de Python (verificado por AST contra `sys.stdlib_module_names`).
   - Ciclo de vida completo de licencias (`ACTIVE`, `GRACE_PERIOD`, `SUSPENDED`, `EXPIRED`, `REVOKED`) y jerarquía de excepciones de dominio alineada con RFC 7807.
2. **Motor Criptográfico Dual y Validador Air-Gapped (`app/infrastructure/security/`)**:
   - `Ed25519Signer` con aceleración nativa OpenSSL y fallback matemático puro sobre coordenadas extendidas twisted Edwards `(X, Y, Z, T)` (~3.6 ms por verificación, sin recursión ni inversiones modulares por bit).
   - Cumplimiento estricto de **RFC 8032 Sección 5.1.3**: rechazo de firmas maleables (`s >= L`), coordenadas no canónicas (`y >= p`), puntos fuera de curva y codificación inválida `x = 0` con bit de signo `1`.
   - `offline_validator.py` autónomo (cero dependencias externas) con verificación de expiración, estructura tipada JSON y bloqueo opcional por `expected_machine_id`.
3. **Persistencia SQLite WAL y Contabilidad ACID (`app/infrastructure/database/` y `repositories/`)**:
   - Conexiones con `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, `BEGIN IMMEDIATE` / `SAVEPOINT` anidados, reintentos con jitter exponencial y cierre limpio de memoria compartida vía `atexit` (cero `ResourceWarning`).
   - Migraciones versionadas con verificación SHA-256 (`schemas.sql` + `schema_migrations`).
   - Deducción atómica sin sobregiro (`balance >= credits`), `consumed_total` acumulado real, aislamiento de idempotencia multi-tenant `UNIQUE(license_id, idempotency_key)`, renovación de ciclo sin inflación (`reset_cycle=True` fija `500 -> 500`) y registro permanente `revoked_licenses` consultado antes de cualquier validación sin estado.
4. **Servicios de Aplicación y Facturación Multi-Proveedor (`app/application/services/`)**:
   - `LicenseService`: emisión Ed25519/HMAC, normalización de `hardware_id` en minúsculas, bloqueo por dominios exactos o comodín (`*.empresa.com`), persistencia automática de `EXPIRED` y re-firma criptográfica en upgrades (`upgrade_existing`) preservando historial en `previous_license_keys`.
   - `QuotaService`: bloqueo de consumo en licencias `REVOKED`, `SUSPENDED` o `EXPIRED`, recarga (`replenish`) y telemetría auditable.
   - `BillingService`: soporte de webhooks firmados para **Stripe** (incluyendo múltiples firmas `v1=` durante rotación de secretos y ventana anti-replay de 300 s) y **LemonSqueezy** (formato nativo `meta.event_name`, `meta.custom_data`, `data.attributes`), deduplicación por `event_id` y cabecera `X-Subscription-Warning` en `GRACE_PERIOD`.
5. **Gateway HTTP FastAPI y Blindaje de Producción (`app/presentation/` y `app/main.py`)**:
   - Middlewares ASGI puros: `SecurityHeadersMiddleware` (CSP estricta, HSTS, `X-Frame-Options: DENY`, `Referrer-Policy` y `X-Request-ID` sincronizado con `metadata.request_id`), `PayloadSizeLimitMiddleware` (64 KB en `Content-Length` y en streaming chunked con señal `BaseException` -> HTTP `413`), y `RateLimitMiddleware` por ventana deslizante inmune a spoofing de `X-Forwarded-For` (`TRUST_PROXY_HEADERS=false`).
   - En `ENVIRONMENT=production`: aborto inmediato en arranque si persiste cualquier secreto público por defecto, exigencia de `X-Admin-Key` en `/issue`, `/revoke` y `/quota/replenish`, y bloqueo `403` de `/api/v1/billing/simulate-webhook`.
6. **CLI Completa (`app/cli.py`)**:
   - Auto-migración en bases SQLite nuevas, comandos `issue` (con defaults automáticos por plan), `verify` (`--offline`, `--pure-python`), `activate`, `revoke`, `quota balance|deduct|replenish` y `serve`, con errores JSON limpios sin trazas crudas.
7. **Consola Web Cyber-Minimalist (`app/presentation/static/index.html` y `app.js`)**:
   - Fondo sólido `#0B0D17`, cero gradientes, cero emojis, contraste mínimo verificado `7.0:1` (> WCAG AA `4.5:1`), acento `#CCFF00` en una única palabra clave del `<h1>`, retícula espacial estricta de `8pt`, glassmorphism y curvas `cubic-bezier`.
   - Incluye emisión, activación, revocación, deducción de cuota, **validador Ed25519 100% en navegador (WebCrypto)**, simulador de webhooks conectado en vivo, feed de telemetría (`/api/v1/telemetry/events`) y tarjetas de precios conectadas a Checkout y Portal; verificado con Playwright en `1440x900` y `375x812` (`0` errores de consola, `0` desbordamiento horizontal).
8. **Verificación Automatizada y CI/CD**:
   - `run_tests.py`: 65 tests deterministas (Tiers 1-4), independientes del orden de ejecución y limpios bajo `-W error::ResourceWarning`.
   - `verify_production.py`: 7 compuertas automáticas (pureza AST, `typing.get_type_hints` en 352 símbolos / 56 módulos, integridad SQLite, paridad OpenSSL <-> Python puro + vectores adversarios RFC 8032, carrera concurrente de 30 hilos sin sobregiro, ciclo CLI y suite E2E completa).
   - `.github/workflows/ci.yml`, `requirements.txt`, `pyproject.toml` (`1.0.0`) y `LICENSE` (MIT).

---

## 3. Mapa de Arquitectura y Endpoints

```text
app/
├── domain/                 # Entidades (slots=True), puertos ABC y excepciones (100% stdlib)
├── application/            # Servicios (License, Quota, Billing) y DTOs Pydantic v2
├── infrastructure/         # SQLite WAL + migraciones, repositorios, Ed25519/HMAC, offline_validator
├── presentation/           # Routers FastAPI v1, middlewares ASGI, errores RFC 7807, UI estática
├── cli.py                  # Interfaz Click de línea de comandos
├── config.py               # Settings tipados y validación de secretos en producción
└── main.py                 # Factoría FastAPI y ciclo lifespan
```

| Método | Ruta | Protección | Función |
|--------|------|------------|---------|
| `GET` | `/healthz`, `/readyz`, `/api/v1/health` | Pública | Sondas de vida e integridad SQLite |
| `GET` | `/api/v1/licenses/public-key` | Pública | Clave pública Ed25519 (hex) para clientes offline |
| `POST` | `/api/v1/licenses/issue` | `X-Admin-Key` (prod) | Emite licencia firmada y ledger inicial |
| `POST` | `/api/v1/licenses/verify` | Pública | Valida firma, estado, nodo y dominio |
| `POST` | `/api/v1/licenses/activate` | Pública | Registra `hardware_id` controlando asientos |
| `POST` | `/api/v1/licenses/revoke` | `X-Admin-Key` (prod) | Revoca licencia y registra en `revoked_licenses` |
| `GET` | `/api/v1/quota/balance` | Pública | Consulta balance, asignación y consumo |
| `POST` | `/api/v1/quota/deduct` | Pública | Debita créditos atómicamente (`Idempotency-Key`) |
| `POST` | `/api/v1/quota/replenish` | `X-Admin-Key` (prod) | Recarga o reinicia ciclo (`reset_cycle`) |
| `GET` | `/api/v1/telemetry/events` | Pública | Historial auditable de eventos de consumo |
| `POST` | `/api/v1/billing/checkout` | Pública | Genera sesión de compra por plan |
| `POST` | `/api/v1/billing/portal` | Pública | Genera sesión de portal de cliente |
| `GET` | `/api/v1/billing/status` | Pública | Estado consolidado de plan, asientos y cuota |
| `POST` | `/api/v1/billing/simulate-webhook` | Solo dev/mock | Arnés local de eventos de facturación |
| `POST` | `/api/v1/webhooks/stripe` | Firma `Stripe-Signature` | Ingesta real Stripe (soporta multi-`v1=`) |
| `POST` | `/api/v1/webhooks/lemonsqueezy` | Firma `X-Signature` | Ingesta real LemonSqueezy |

---

## 4. Variables de Entorno (`.env`)

| Variable | Valor por Defecto (Dev) | Uso |
|----------|-------------------------|-----|
| `DATABASE_URL` | `sqlite:///data/keyforge.db` | Ruta SQLite o `sqlite:///:memory:` |
| `SECRET_KEY` | *(clave dev de 45 chars)* | Firma simétrica HMAC-SHA256 (>= 32 bytes únicos en prod) |
| `ED25519_PRIVATE_KEY_HEX` | *(64 hex dev)* | Semilla privada Ed25519 de 32 bytes (obligatorio rotar en prod) |
| `ED25519_PUBLIC_KEY_HEX` | *(64 hex dev)* | Clave pública derivada de 32 bytes |
| `ADMIN_API_KEY` | `kf_dev_admin_key_change_in_prod` | Cabecera `X-Admin-Key` obligatoria en producción |
| `STRIPE_WEBHOOK_SECRET` | `whsec_test_stripe_secret_12345` | Secreto HMAC de Stripe |
| `LEMONSQUEEZY_WEBHOOK_SECRET` | `whsec_test_lemonsqueezy_secret_12345` | Secreto HMAC de LemonSqueezy |
| `BILLING_MODE` | `mock` | `mock` (desarrollo) o `live` (bloquea simulador) |
| `ENVIRONMENT` | `development` | `development`, `testing` o `production` |
| `HOST` / `PORT` / `LOG_LEVEL` | `0.0.0.0` / `8000` / `INFO` | Parámetros del servidor HTTP y logs |
| `MAX_PAYLOAD_BYTES` | `65536` | Límite máximo de cuerpo HTTP (64 KB) |
| `RATE_LIMIT_ENABLED` | `true` | Activa limitador por ventana deslizante |
| `RATE_LIMIT_REQUESTS` | `25` | Peticiones API por ventana (`RATE_LIMIT_WINDOW_SECONDS`) |
| `RATE_LIMIT_WEBHOOK_REQUESTS` | `300` | Peticiones de webhook por ventana |
| `RATE_LIMIT_WINDOW_SECONDS` | `10` | Duración de ventana en segundos |
| `TRUST_PROXY_HEADERS` | `false` | Solo activar (`true`) detrás de proxy inverso confiable |

---

## 5. Comandos Verificados de Operación

```powershell
# 1. Ubicarse en el proyecto y verificar las 7 compuertas de producción
Set-Location C:\Users\Usuario\teamwork_projects\monetizable_project
python verify_production.py

# 2. Ejecutar suite E2E completa con control estricto de recursos
python -W error::ResourceWarning run_tests.py

# 3. Emitir licencia Pro por CLI (aplica 3 asientos y 500 créditos automáticamente)
python -m app.cli issue --email "cliente@empresa.io" --tier "pro"

# 4. Verificar token en modo air-gapped (matemática pura RFC 8032, cero red)
python -m app.cli verify "LIC-PRO-..." --offline --pure-python

# 5. Activar nodo hardware, descontar créditos, recargar y revocar
python -m app.cli activate "LIC-PRO-..." --hardware-id "nodo-prod-01" --machine-name "workstation-01"
python -m app.cli quota balance "LIC-PRO-..."
python -m app.cli quota deduct "LIC-PRO-..." --credits 10 --idempotency-key "op-001"
python -m app.cli quota replenish "LIC-PRO-..." --credits 50
python -m app.cli revoke "LIC-PRO-..." --reason "baja_manual"

# 6. Levantar servidor web y consola interactiva
python -m app.cli serve --host 127.0.0.1 --port 8000
```

Generar un par de claves Ed25519 nuevo para producción:

```powershell
python -c "import secrets; from app.infrastructure.security.ed25519_signer import Ed25519Signer; priv = secrets.token_hex(32); s = Ed25519Signer(private_key_hex=priv); print('ED25519_PRIVATE_KEY_HEX=' + priv); print('ED25519_PUBLIC_KEY_HEX=' + s.get_public_key_hex())"
```

---

## 6. Playbook de Monetización y Marketing de Alto Margen

1. **Posicionamiento de Producto Dual**:
   - **Venta Directa B2D (Cashflow Inmediato)**: Comercializar KeyForge como plantilla/gateway autoalojable ("Self-Hosted Licensing & Credit Gateway") en LemonSqueezy / Gumroad: licencia Indie a **$149** y licencia Agency/Unlimited a **$349** (un solo pago frente a pagar comisiones perpetuas a terceros).
   - **Infraestructura Propia Multi-Producto**: Usar la misma instancia de KeyForge como motor de cobro para lanzar múltiples micro-herramientas propias (servidores MCP especializados, CLIs de auditoría de código, scrapers estructurados o agentes locales) cobrando suscripciones de **$29-$89/mes**.
2. **Embudo Técnico de Conversión Automática (Product-Led Growth)**:
   - Entregar instantáneamente una clave `LIC-COMMUNITY-...` con 25 créditos gratuitos al instalar la CLI o servidor MCP.
   - Al agotar el saldo, el gateway responde `HTTP 402 QUOTA_EXHAUSTED`: el cliente CLI muestra directamente el enlace de `/api/v1/billing/checkout` para pasar a `Pro` ($29/mes) sin fricción manual; el webhook re-firma y recarga los 500 créditos en milisegundos.
3. **Canales de Distribución con CAC Cero**:
   - Publicar `offline_validator.py` como paquete ultraligero open-source (imán técnico en GitHub, PyPI, Hacker News *Show HN* y directorios de servidores MCP) enlazando al gateway completo KeyForge para emisión, webhooks y control de cuotas.

---

## 7. Protocolo Multi-Sesión para Argon (Handoff Checkpoint)

### Rutina de Reanudación en Nueva Sesión (< 10 segundos)
1. Leer únicamente este archivo (`ARGON_SESSION_GUIDE.md`) — evita escanear todo el repositorio y ahorra >80% de tokens de contexto.
2. Ejecutar `python verify_production.py` para confirmar estado base intacto (`7/7` compuertas en verde).
3. Editar únicamente los módulos objetivo con cambios atómicos y volver a correr `python verify_production.py` antes de hacer commit siguiendo Conventional Commits.

### Estado Verificado Actual (Checkpoint `v1.0.0`)
- **Backend, Dominio, Criptografía y SQLite WAL**: Completos y verificados (`352` símbolos tipados sin errores en `56` módulos).
- **Seguridad HTTP y Secretos de Producción**: Completos (`CSP`, `HSTS`, `413` streaming, `429` anti-spoofing, `X-Admin-Key`, fail-fast en producción).
- **Consola Frontend**: Completa y auditada visualmente con Playwright en escritorio (`1440x900`) y móvil (`375x812`).
- **Tests y CI**: `65/65` tests E2E aprobados (orden normal y aleatorio, cero `ResourceWarning`) + `.github/workflows/ci.yml` listo.
- **Git**: Repositorio local en rama `main` limpio (sin `push` remoto pendiente de configurar credenciales del repositorio destino).

### Próximos Módulos Opcionales para Futuras Sesiones con Argon
- **Sesión A — Conector SDK Live de Checkout**: Conectar `BillingService.create_checkout_session` y `create_portal_session` contra las APIs REST reales de Stripe Checkout / LemonSqueezy Checkouts cuando `BILLING_MODE=live`.
- **Sesión B — SDKs Cliente Multi-Lenguaje**: Portar `offline_validator.py` a paquetes ligeros en TypeScript (`@keyforge/verify` usando WebCrypto) y Go/Rust para binarios nativos.
- **Sesión C — Panel Admin Multi-Producto**: Añadir tabla `products` y vista protegida por `X-Admin-Key` con métricas MRR, retención y revocaciones por lote.
