# KEYFLINT v1.2.1 — DOSSIER TÉCNICO, ARQUITECTURA Y ANÁLISIS INTEGRAL DEL SISTEMA

---

## ÍNDICE GENERAL

1. **Visión General y Filosofía de Diseño**
   - Problema que resuelve KeyFlint
   - Principios rectores (Offline-First, Zero-Overdraft, Pure-Stdlib, Resiliencia de Infraestructura)
   - Modelo de licencias dual (BSL 1.1 para el Gateway, MIT para los SDKs)
2. **Arquitectura del Sistema (Clean / Hexagonal Architecture)**
   - Desacoplamiento por capas (Domain, Application, Infrastructure, Presentation)
   - Reglas de pureza: la capa de Dominio en Python estándar (Zero-Dependencies)
   - Diagrama de flujo arquitectónico
3. **Capa de Dominio (Domain Layer)**
   - Entidades principales y Value Objects (`License`, `Activation`, `Customer`, `QuotaLedger`, `CreditDeductResult`, `Tier`, `LicenseStatus`)
   - Invariantes de negocio y reglas de dominio
   - Jerarquía de excepciones de dominio (RFC 7807 Problem Details)
4. **Motor de Persistencia y Base de Datos (SQLite WAL)**
   - Por qué SQLite + WAL + Litestream frente a bases de datos relacionales cliente-servidor
   - Concurrencia y mitigación de bloqueos: `BEGIN IMMEDIATE` y `PRAGMA busy_timeout=5000`
   - Esquema DDL completo: tablas, índices, claves foráneas y restricciones
   - Mecanismo de migraciones versionadas y verificación de checksums
   - Tareas periódicas de mantenimiento (Purga de `usage_events`, compactación WAL)
5. **Criptografía y Verificación sin Red (Ed25519 & RFC 8032)**
   - Anatomía y gramática exacta del token (`LIC-<TIER>-<payload>.<sig>`)
   - Especificación del payload JSON y claims
   - Algoritmo de firma y verificación: OpenSSL (vía `cryptography`) frente a motor puro RFC 8032 en Python
   - Rotación de claves (`kid`) y soporte de anillos de claves retiradas
   - Protección contra retraso de reloj (*Clock Rollback Protection* y `clock_state`)
   - Huella digital de hardware (*Stable Node Fingerprinting*) y bloqueo por dominios
   - Suite de conformidad cruzada: los 50 vectores criptográficos
6. **Capa de Aplicación y Lógica de Negocio**
   - `LicenseService`: emisión, validación híbrida, activación de nodos, liberación y revocación
   - `QuotaService`: descuento atómico de créditos, prevención de saldo negativo, reembolsos y Circuit Breaker anti-abuso
   - `BillingService`: ingesta de webhooks (Stripe & LemonSqueezy), idempotencia criptográfica, asignación de tiers y enlaces mágicos del portal
7. **Superficie HTTP API (FastAPI Gateway)**
   - Catálogo exhaustivo de endpoints (Método, Ruta, Autenticación, Parámetros, Respuestas)
   - Middlewares: `SecurityHeadersMiddleware`, `PayloadSizeLimitMiddleware`, `RateLimitMiddleware`
   - Abstracción de proxy inverso (`TRUSTED_PROXY_MODE`: fly, cloudflare, standard, direct)
   - Portal de autoservicio para compradores (Enlaces mágicos de un solo uso con SHA-256)
8. **Ecosistema de SDKs de Verificación (Python, TypeScript, Go)**
   - Paquetes en registros oficiales (`keyflint-verify` en PyPI y npm, `sdks/go-verify` en Go)
   - API pública por lenguaje y ejemplos prácticos
   - Integración nativa con servidores MCP (Model Context Protocol): decoradores `@kf.require_license` y `@kf.metered`
   - Tolerancia a fallos de red: cola de gracia offline (*Offline Grace Queue*) y sincronización diferida
   - Herramienta CLI de auto-activación (`npx/uvx keyflint-verify activate`) para Claude Desktop, Cursor y Windsurf
   - Servidor MCP monetizado de referencia (`examples/monetized-mcp-server`)
9. **Frontend, Consola y Activos Web**
   - Arquitectura de `keyflint.dev` (GitHub Pages) y consola del Gateway
   - Simulador Ed25519 in-browser con WebCrypto API (`demo-api.js`)
   - Activos de SEO y descubribilidad (`sitemap.xml`, `robots.txt`, JSON-LD schema, guía de monetización MCP)
10. **Operaciones, Despliegue y Recuperación ante Desastres (DR)**
    - Topología de despliegue en Fly.io (Contenedor Docker, volumen persistente, recursos)
    - Replicación continua con Litestream hacia Cloudflare R2 / S3
    - Simulacro horario de restauración en caliente (*Restore Drill*) y dead-man heartbeat
    - Canalizaciones de CI/CD en GitHub Actions (7 barreras de calidad, build Docker con SBOM, despliegue con rollback)
    - Monitorización activa cada 15 minutos y alertas operativas
11. **Modelo Comercial, Precios y Gobernanza**
    - Desglose de planes comerciales (Founder, Indie, Agency, Pro Cloud, Studio Cloud)
    - Análisis de costes de infraestructura (~$3/mes) y escalabilidad económica

---

## 1. VISIÓN GENERAL Y FILOSOFÍA DE DISEÑO

### 1.1. El problema que resuelve KeyFlint
Los desarrolladores que construyen servidores MCP (Model Context Protocol) para Claude Desktop, Cursor o herramientas CLI se enfrentan a un dilema fundamental:
1. **SaaS tradicionales de licencias (Keygen, Cryptlex):** Cobran entre $49 y $199 mensuales de cuota fija más variables por validación. Obligan a que cada ejecución de una tool MCP realice una petición HTTP externa al servidor de licencias, introduciendo latencias inaceptables (150–500 ms) y provocando caídas completas de la herramienta si el servidor de licencias sufre cortes de red.
2. **Desarrollos caseros:** La mayoría de creadores no implementan firmas criptográficas asimétricas reales ni protección contra ataques de concurrencia (doble gasto de créditos), dejando sus herramientas vulnerables a pirateo inmediato o desbordamiento de cuotas.

KeyFlint resuelve este problema proporcionando un **Gateway autoalojado de control total** con **SDKs de verificación local offline Ed25519 (<1 ms)** y **medición atómica de créditos por llamada** con compensación automática por fallos.

### 1.2. Principios Rectores
* **Offline-First:** La validez criptográfica de la licencia, la fecha de expiración, las características (*features*), el bloqueo de máquina y el dominio se verifican en el propio proceso del cliente sin enviar un solo byte por la red.
* **Zero-Overdraft (Tolerancia Cero al Saldo Negativo):** SQLite ejecutado en transacciones `BEGIN IMMEDIATE` garantiza atomicidad estricta (ACID) en el descuento de créditos. En condiciones de alta concurrencia, es físicamente imposible que un usuario gaste más saldo del asignado.
* **Pure-Stdlib Fallback:** Tanto el Gateway como los SDKs incluyen motores criptográficos basados exclusivamente en la biblioteca estándar (Python puro sin dependencias C, Go stdlib, TypeScript con APIs web nativas), garantizando compatibilidad en entornos restringidos o contenedores mínimos.
* **Resiliencia Extrema:** La base de datos es un único archivo SQLite replicado en tiempo real a nivel de página (WAL) hacia almacenamiento de objetos S3/R2 mediante Litestream.

### 1.3. Modelo de Licencia Dual
* **Gateway y Servidor Backend:** Distribuido bajo licencia **BSL 1.1 (Business Source License)**. El código es abierto y auditable. Los desarrolladores pueden ejecutarlo gratis en modo Community o adquirir una licencia comercial (Indie, Agency o Founder) para producción sin cuotas mensuales. Pasados 4 años desde cada versión, el código revierte automáticamente a licencia de código abierto permisiva.
* **SDKs de Verificación (`keyflint-verify`):** Distribuidos bajo licencia permisiva **MIT**. Se instalan como dependencias estándar en las herramientas de los creadores sin imponer restricciones a sus usuarios finales.

---

## 2. ARQUITECTURA DEL SISTEMA (CLEAN / HEXAGONAL ARCHITECTURE)

KeyFlint está estructurado siguiendo los principios de la Arquitectura Limpia (Hexagonal / Ports and Adapters), aislando por completo la lógica de negocio de los detalles de infraestructura, frameworks web y proveedores de bases de datos.

```
                    +-------------------------------------------------------+
                    |                 PRESENTATION LAYER                    |
                    |   FastAPI Routers, ASGI Middlewares, Static UI, DTOs  |
                    +---------------------------+---------------------------+
                                                |
                                                v
                    +-------------------------------------------------------+
                    |                  APPLICATION LAYER                    |
                    |   LicenseService, QuotaService, BillingService        |
                    +---------------------------+---------------------------+
                                                |
                                                v
                    +-------------------------------------------------------+
                    |                    DOMAIN LAYER                       |
                    |   Entities (License, QuotaLedger), Exceptions, Types  |
                    |        [100% Python Standard Library - ZERO DEPS]     |
                    +---------------------------+---------------------------+
                                                ^
                                                | (Implementa Interfaces)
                    +---------------------------+---------------------------+
                    |                 INFRASTRUCTURE LAYER                  |
                    |   SQLite Repos, Ed25519 Signer, Email, Litestream     |
                    +-------------------------------------------------------+
```

### Reglas de Dependencia
1. **La capa de Dominio no importa a nadie:** `app/domain` utiliza únicamente módulos de la biblioteca estándar (`dataclasses`, `datetime`, `enum`, `typing`, `uuid`). No tiene dependencias de FastAPI, SQLite, Pydantic o bibliotecas criptográficas externas.
2. **La capa de Aplicación depende solo del Dominio:** `app/application` orquesta los casos de uso a través de interfaces abstractas (`ILicenseRepository`, `IQuotaRepository`, `ICryptoSigner`).
3. **La capa de Infraestructura implementa los puertos:** `app/infrastructure` provee adaptadores concretos (`SqliteLicenseRepo`, `Ed25519Signer`, `TransactionalEmailService`).
4. **La capa de Presentación expone los adaptadores de entrada:** `app/presentation` maneja peticiones HTTP, valida payloads con Pydantic y gestiona errores RFC 7807.

---

## 3. CAPA DE DOMINIO (DOMAIN LAYER)

### 3.1. Entidades Principales

#### `License` (`app/domain/entities/license.py`)
Representa el agregado raíz de la licencia.
* **Campos:** `id` (UUIDv4), `customer_id` (FK), `license_key` (token firmado), `tier` (Enum: `community`, `indie`, `agency`, `pro`, `studio`, `lifetime`), `status` (Enum: `active`, `suspended`, `expired`, `revoked`, `grace_period`), `max_seats` (int), `current_activations` (int), `expires_at` (datetime opcional), `created_at` (datetime), `signature` (str), `features` (tuple de strings), `metadata` (dict JSON).
* **Invariantes:**
  - Si `expires_at` es `None`, la licencia es perpetua.
  - No se puede activar un nodo si `current_activations >= max_seats`.
  - No se pueden realizar operaciones sobre licencias revocadas o suspendidas.

#### `QuotaLedger` (`app/domain/entities/quota.py`)
Gestiona el saldo de créditos bajo el patrón token-bucket.
* **Campos:** `id` (UUIDv4), `license_id` (FK única), `total_allowance` (int), `balance` (int), `consumed` (int), `last_reset_at` (datetime), `updated_at` (datetime).
* **Invariantes:**
  - `balance` nunca puede descender por debajo de 0 en una deducción válida.
  - La deducción debe ser un entero estrictamente positivo (`credits > 0`).

#### `Tier` (Enum de Tiers Comerciales)
Define los derechos y valores por defecto:
* **Community:** 25 créditos, 1 nodo, expira en 365 días, features: `("core",)`.
* **Indie:** 10.000 créditos, 3 nodos, perpetua (sin exp), features: `("core", "cli_offline", "telemetry_sync", "lifetime_v1")`.
* **Agency:** 50.000 créditos, 25 nodos, perpetua, features: `("core", "cli_offline", "telemetry_sync", "multi_tenant", "priority_support")`.
* **Pro Cloud:** 500 créditos/ciclo, 3 nodos, 365 días, features: `("core", "cli_offline", "telemetry_sync")`.
* **Studio Cloud:** 5.000 créditos/ciclo, 25 nodos, 365 días, features: `("core", "cli_offline", "telemetry_sync", "multi_tenant", "priority_webhook")`.
* **Lifetime / Founder:** 10.000 créditos iniciales, 3 nodos (10 en Founder extendido), perpetua, features: `("core", "cli_offline", "telemetry_sync", "self_hosted")`.

### 3.2. Excepciones de Dominio (`app/domain/exceptions.py`)
Todas las excepciones heredan de `DomainError` y mapean directamente a códigos de estado HTTP y estructuras RFC 7807:

| Excepción | Código Error (`code`) | HTTP Status | Causa |
| :--- | :--- | :--- | :--- |
| `QuotaExceededError` | `QUOTA_EXHAUSTED` | 402 Payment Required | Saldo de créditos insuficiente para ejecutar la llamada. |
| `LicenseExpiredError` | `LICENSE_EXPIRED` | 403 Forbidden | La fecha del sistema supera `expires_at`. |
| `LicenseRevokedError` | `LICENSE_REVOKED` | 403 Forbidden | Licencia explícitamente cancelada o reembolsada. |
| `LicenseSuspendedError` | `LICENSE_SUSPENDED` | 403 Forbidden | Suscripción impagada o en periodo de disputa. |
| `LicenseNotFoundError` | `LICENSE_NOT_FOUND` | 404 Not Found | El token o ID de licencia no existe en la base de datos. |
| `CustomerNotFoundError` | `CUSTOMER_NOT_FOUND` | 404 Not Found | Cliente no localizado por ID o email. |
| `InvalidSignatureError` | `INVALID_SIGNATURE` | 401 Unauthorized | Firma Ed25519 adulterada o clave pública incorrecta. |
| `SeatLimitExceededError` | `SEAT_LIMIT_EXCEEDED` | 409 Conflict | Se ha alcanzado el número máximo de máquinas activadas. |
| `NodeLockViolationError` | `NODE_LOCK_VIOLATION` | 403 Forbidden | La huella de hardware del cliente no coincide con la licencia. |
| `DuplicateActivationError` | `DUPLICATE_ACTIVATION` | 409 Conflict | La máquina ya se encuentra registrada en la licencia. |
| `InvalidLicenseFormatError`| `INVALID_LICENSE_FORMAT` | 400 Bad Request | Sintaxis de token corrupta (falta prefijo `LIC-`, separadores, etc.). |
| `IdempotencyConflictError` | `IDEMPOTENCY_CONFLICT` | 409 Conflict | Reutilización de una misma clave con parámetros dispares. |

---

## 4. MOTOR DE PERSISTENCIA Y BASE DE DATOS (SQLITE WAL)

### 4.1. Filosofía del Almacenamiento
En lugar de depender de clústeres Postgres o MySQL con costes fijos elevados ($25–$50/mes) y latencias de conexión por socket, KeyFlint opera sobre **SQLite en modo WAL (Write-Ahead Logging)** embebido en el mismo proceso del Gateway.
* **Latencia de lectura:** ~0.05 ms.
* **Transacciones ACID concurrentes:** Modo `BEGIN IMMEDIATE` para serializar escrituras en SQLite sin condiciones de carrera.
* **Configuración de conexión (`app/infrastructure/database/connection.py`):**
  ```python
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  PRAGMA busy_timeout = 5000;
  PRAGMA foreign_keys = ON;
  PRAGMA cache_size = -64000; -- 64 MB de caché en memoria
  ```

### 4.2. Esquema DDL Relacional (`schemas.sql`)

```sql
-- 1. Clientes
CREATE TABLE customers (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    company TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Licencias
CREATE TABLE licenses (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    license_key TEXT UNIQUE NOT NULL,
    tier TEXT NOT NULL CHECK(tier IN ('community', 'indie', 'agency', 'pro', 'studio', 'lifetime')),
    status TEXT NOT NULL CHECK(status IN ('active', 'suspended', 'expired', 'revoked', 'grace_period')),
    max_seats INTEGER NOT NULL DEFAULT 1,
    current_activations INTEGER NOT NULL DEFAULT 0,
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    signature TEXT NOT NULL,
    features TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

-- 3. Activaciones de Nodos (Hardware Locking)
CREATE TABLE activations (
    id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    hardware_id TEXT NOT NULL,
    machine_name TEXT,
    ip_address TEXT,
    activated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(license_id, hardware_id)
);

-- 4. Saldos de Cuota (Patrón Token-Bucket)
CREATE TABLE quotas (
    id TEXT PRIMARY KEY,
    license_id TEXT UNIQUE NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    total_allowance INTEGER NOT NULL DEFAULT 1000,
    balance INTEGER NOT NULL DEFAULT 1000,
    consumed INTEGER NOT NULL DEFAULT 0,
    last_reset_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5. Registro de Consumo e Idempotencia
CREATE TABLE usage_events (
    id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    credits_consumed INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    metadata_json TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(license_id, idempotency_key)
);

-- 6. Auditoría y Circuit Breaker
CREATE TABLE license_events (
    id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. Webhooks Procesados (Protección Anti-Replay)
CREATE TABLE webhook_events (
    id TEXT PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    provider TEXT NOT NULL CHECK(provider IN ('stripe', 'lemonsqueezy')),
    event_type TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('processed', 'failed', 'ignored')),
    processed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 8. Licencias Revocadas
CREATE TABLE revoked_licenses (
    license_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    revoked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 9. Enlaces Mágicos del Portal (Hash SHA-256)
CREATE TABLE portal_login_tokens (
    token_hash TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT NULL
);

-- 10. Control de Migraciones
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checksum TEXT NOT NULL
);
```

### 4.3. Atomicidad en la Deducción de Cuota
Para evitar condiciones de carrera, el repositorio `SqliteQuotaRepo.atomic_deduct` ejecuta:
1. Comprueba si el `(license_id, idempotency_key)` ya existe en `usage_events`. Si existe, retorna el resultado cacheado inmediatamente (`is_cached=True`), garantizando deducción idempotente.
2. Abre transacción con `BEGIN IMMEDIATE`.
3. Consulta el balance actual: `SELECT balance, consumed FROM quotas WHERE license_id = ?`.
4. Si `balance < credits`, aborta lanzando `QuotaExceededError`.
5. Ejecuta `UPDATE quotas SET balance = balance - ?, consumed = consumed + ? WHERE license_id = ?`.
6. Inserta el evento en `usage_events`.
7. Hace `COMMIT`. Si múltiples hilos o workers compiten a la vez, SQLite serializa la escritura de forma segura sin sobregiro.

---

## 5. CRIPTOGRAFÍA Y VERIFICACIÓN SIN RED (ED25519 & RFC 8032)

### 5.1. Formato Exacto del Token de Licencia
El token de KeyFlint es completamente autocontenido y sigue la estructura:
```
LIC-<TIER>-<PAYLOAD_BASE64URL>.<SIGNATURE_BASE64URL>
```
* **Prefijo:** `LIC-` obligatorio.
* **Tier:** Nombre del nivel en mayúsculas (`COMMUNITY`, `INDIE`, `AGENCY`, `PRO`, `STUDIO`, `LIFETIME`, `FOUNDER`).
* **Payload:** Objeto JSON codificado en Base64URL sin relleno (*unpadded*).
* **Separador de firma:** Punto (`.`).
* **Firma:** 64 bytes binarios de la firma Ed25519 codificados en Base64URL sin relleno.

#### Ejemplo de Claims en el Payload JSON:
```json
{
  "license_id": "lic_9e84b2c1_3d4e_4a1f",
  "email": "developer@acme.ai",
  "tier": "indie",
  "features": ["core", "cli_offline", "telemetry_sync", "lifetime_v1"],
  "max_seats": 3,
  "expires_at": null,
  "issued_at": 1793721600,
  "kid": "k2",
  "machine_id": "9f8a3b1c2d4e...",
  "allowed_domains": ["api.acme.ai", "*.internal.net"]
}
```

### 5.2. Motor de Firma y Verificación Híbrido
* **Ruta Rápida (OpenSSL / `cryptography`):** Ejecuta la verificación Ed25519 en código C nativo en **0,116 ms** por validación.
* **Ruta Pura Python (Fallback RFC 8032):** Si el entorno no dispone del paquete `cryptography` compilado (por ejemplo, entornos embebidos mínimos), KeyFlint incluye una implementación completa de la curva de Edwards $2^{255}-19$ en Python estándar (`app/infrastructure/security/offline_validator.py`). Ejecuta la verificación matemática estricta en ~3 ms sin dependencias externas.

### 5.3. Mitigaciones Criptográficas y de Seguridad
1. **Clock Rollback Protection (`~/.keyflint/clock_state`):**
   - Si un usuario tiene una licencia temporal que expira el 31 de diciembre, podría retrasar el reloj de su ordenador al mes anterior para usarla indefinidamente sin red.
   - KeyFlint mantiene un registro monótono del "último tiempo visto" en `~/.keyflint/clock_state`. Si el reloj actual está retrasado más de 300 segundos respecto a este registro, rechaza la validación con `ERR_CLOCK_ROLLBACK_DETECTED`. Las licencias perpetuas están exentas de este chequeo.
2. **Key Rotation (`kid`):**
   - Admite cabecera `kid` en el payload para identificar qué clave pública del anillo (*key ring*) firmó el token. Permite retirar claves antiguas sin invalidar licencias emitidas con claves previas.
3. **Resistencia a Firmas Maleables y Puntos No Canónicos:**
   - Cumple estrictamente con la sección 5.1.3 de RFC 8032: rechaza escalares $S \ge L$ y puntos $Y \ge P$ o con bits de signo corruptos en $X=0$.

---

## 6. CAPA DE APLICACIÓN Y LÓGICA DE NEGOCIO

### 6.1. `LicenseService` (`app/application/services/license_service.py`)
* **`issue(request)`:** Crea el cliente si no existe, genera el token firmado Ed25519, registra la licencia en SQLite y aprovisiona el balance inicial en `quotas` de forma transaccional.
* **`verify(request)`:** Validación en dos niveles: consulta el estado en SQLite (para detectar revocaciones o suspensiones administrativas) y, si la base de datos no está disponible, ejecuta la validación criptográfica sin red del token.
* **`activate(request)`:** Comprueba el límite de asientos (`max_seats`), valida que no esté revocada y registra el `hardware_id` en la tabla `activations`.
* **`release_node(license_key, hardware_id)`:** Libera un asiento para que el desarrollador pueda reinstalar su contenedor o cambiar de máquina, protegido por un límite de enfriamiento de **1 liberación cada 24 horas** por licencia (`NODE_RELEASES_PER_24H = 1`).

### 6.2. `QuotaService` y Circuit Breaker de Reembolsos
* **`deduct(request)`:** Descuenta créditos atómicamente. Si el saldo es insuficiente, arroja `QuotaExceededError` (HTTP 402).
* **`refund(request)`:** Compensa una deducción fallida dentro de la ventana de tiempo `QUOTA_REFUND_WINDOW_SECONDS` (900 s por defecto).
* **Circuit Breaker Anti-Abuso (`RefundBreaker`):**
  - **Problema de seguridad prevenido:** Evita que un cliente modifique el SDK local para consumir una tool con éxito y solicitar inmediatamente un reembolso simulando un error, logrando créditos infinitos.
  - **Regla de corte:** Si una licencia acumula más de **5 reembolsos consecutivos** en una ventana de 10 minutos (`REFUND_BREAKER_MAX_CONSECUTIVE = 5`), o si su tasa de reembolsos supera el **25%** (`REFUND_BREAKER_MAX_RATIO = 0.25`) en las últimas 50 llamadas (con una muestra mínima de 10 llamadas), el servidor deniega automáticamente el reembolso con HTTP 429 (`ERR_REFUND_VELOCITY_EXCEEDED`) y registra un evento de auditoría de seguridad para intervención manual.

### 6.3. `BillingService` y Webhooks de Pago
* **Proveedores soportados:** Stripe y LemonSqueezy.
* **Verificación de firma:**
  - Stripe: Valida cabecera `Stripe-Signature` (`t=...,v1=...`) mediante HMAC-SHA256 con protección contra ataques de temporización (`hmac.compare_digest`).
  - LemonSqueezy: Valida cabecera `X-Signature` mediante HMAC-SHA256.
* **Resolución de Tiers y Regla *One-License-Per-Purchase*:**
  - En Stripe Checkout, el tier se lee de `metadata.tier` en el enlace de pago o línea de factura (`indie`, `agency`, `pro`, `studio`, `lifetime`).
  - Si un webhook no incluye metadata de tier válida, KeyFlint no descarta el pago: emite defensivamente una licencia de prueba Community para asegurar el servicio y dispara un correo de alerta inmediata al operador (`OPS_ALERT_EMAIL`) para reasignar el plan sin perder al cliente.
* **Entrega de Licencia por Email:**
  - Se despacha vía Resend (API v1) o SMTP. Si el proveedor de email sufre una caída transitoria, el evento queda registrado en SQLite y un proceso en segundo plano reintenta automáticamente el envío cada 300 segundos.

---

## 7. SUPERFICIE HTTP API (FASTAPI GATEWAY)

### 7.1. Catálogo Completo de Endpoints

| Método | Ruta | Autenticación | Propósito |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | Pública | Dashboard y Consola interactiva Cyber-Minimalista. |
| `GET` | `/healthz` | Pública | Probe de liveness (supervivencia básica del proceso). |
| `GET` | `/readyz` | Pública | Probe de readiness (comprueba conexión `SELECT 1` a SQLite). |
| `GET` | `/api/v1/health` | Pública | Estado general: email provider, estado del backup Litestream. |
| `GET` | `/api/v1/licenses/public-key` | Pública | Clave pública Ed25519 y anillo de claves para SDKs. |
| `POST` | `/api/v1/licenses/issue` | `X-Admin-Api-Key` | Emisión administrativa de una nueva licencia firmada. |
| `POST` | `/api/v1/licenses/verify` | Pública / Token | Verificación online de licencia y estado de nodo. |
| `POST` | `/api/v1/licenses/activate` | Pública / Token | Vinculación de máquina/hardware a una licencia. |
| `POST` | `/api/v1/licenses/nodes` | Pública / Token | Consulta de máquinas activas vinculadas a una licencia. |
| `POST` | `/api/v1/licenses/nodes/release` | Pública / Token | Liberación de máquina/asiento (sujeto a cooldown de 24 h). |
| `POST` | `/api/v1/licenses/revoke` | `X-Admin-Api-Key` | Revocación administrativa inmediata de una licencia. |
| `POST` | `/api/v1/quota/deduct` | Pública / Token | Deducción atómica de créditos con clave de idempotencia. |
| `POST` | `/api/v1/quota/refund` | Pública / Token | Reembolso de créditos por llamada fallida (Circuit Breaker). |
| `POST` | `/api/v1/quota/replenish` | `X-Admin-Api-Key` | Recarga de créditos o renovación de ciclo. |
| `GET` | `/api/v1/quota/balance` | Pública / Token | Consulta del saldo restante y créditos consumidos. |
| `POST` | `/api/v1/billing/checkout` | Pública | Generación de sesión de checkout para compras. |
| `POST` | `/api/v1/billing/portal` | Pública | Generación de sesión del portal de Stripe/LemonSqueezy. |
| `POST` | `/api/v1/billing/portal/lookup` | Pública (Rate Limit) | Envío de enlace mágico de autoservicio al email del comprador. |
| `POST` | `/api/v1/billing/portal/redeem` | Token Mágico | Canje de enlace mágico de un solo uso para ver licencias. |
| `POST` | `/api/v1/webhooks/stripe` | HMAC Stripe | Recepción de eventos de ciclo de vida de Stripe. |
| `POST` | `/api/v1/webhooks/lemonsqueezy`| HMAC LemonSqueezy| Recepción de eventos de ciclo de vida de LemonSqueezy. |
| `GET` | `/api/v1/telemetry/events` | Pública / Token | Historial de auditoría y eventos de consumo de la licencia. |

### 7.2. Middlewares y Seguridad de Red

```
Petición Entrante
      │
      ▼
[SecurityHeadersMiddleware]  --> Asigna X-Request-ID, Content-Security-Policy estricta, HSTS, X-Frame-Options
      │
      ▼
[PayloadSizeLimitMiddleware] --> Valida Content-Length y corta streams > 64 KB (HTTP 413)
      │
      ▼
[RateLimitMiddleware]       --> Sliding Window en memoria (25 req/10s endpoints normales, 300/10s webhooks)
      │
      ▼
[Controlador / Router]       --> Inyección de dependencias y lógica de negocio
```

#### Abstracción de Proxy Inverso (`TRUSTED_PROXY_MODE`)
En despliegues Self-Hosted detrás de Cloudflare, Traefik, Hetzner, AWS ALB o Railway, la IP real del cliente no siempre viene en la conexión TCP directa. Para evitar suplantación (*IP Spoofing*) o que todos los usuarios compartan el mismo cubo de rate limit, KeyFlint soporta 4 modos configurables:
* `fly`: Confía en la cabecera `Fly-Client-IP` provista por la malla de Fly.io.
* `cloudflare`: Confía en `CF-Connecting-IP` solo si el salto previo proviene de rangos autorizados.
* `standard`: Extrae la IP de `X-Real-IP` o del salto seguro de `X-Forwarded-For` validando contra `TRUSTED_PROXY_IPS`.
* `direct`: Utiliza directamente la IP de la conexión TCP (`request.client.host`).

---

## 8. ECOSISTEMA DE SDKS DE VERIFICACIÓN (PYTHON, TYPESCRIPT, GO)

### 8.1. Arquitectura y Disponibilidad
Los tres SDKs comparten paridad matemática absoluta, el mismo formato de token, idéntica gramática y los mismos 50 vectores de prueba:

| SDK | Lenguaje | Paquete Oficial | Runtime Dependencies |
| :--- | :--- | :--- | :--- |
| **Python** | Python $\ge$ 3.10 | `keyflint-verify` (PyPI) | 0 (Usa stdlib; `cryptography` opcional para modo acelerado). |
| **TypeScript / Node** | Node $\ge$ 18 | `keyflint-verify` (npm) | 0 (Usa APIs estándar Node/WebCrypto). |
| **Go** | Go $\ge$ 1.21 | `github.com/ArceeDev/keyflint/sdks/go-verify` | 0 (Solo biblioteca estándar de Go: `crypto/ed25519`). |

### 8.2. Integración en Servidores MCP (Model Context Protocol)

#### Ejemplo en Python (FastMCP / MCP SDK):
```python
from mcp.server.fastmcp import FastMCP
from keyflint_verify.mcp import KeyFlint

mcp = FastMCP("SQL-Optimizer-MCP")
kf = KeyFlint()  # Lee variables KEYFLINT_LICENSE, KEYFLINT_PUBLIC_KEYS, KEYFLINT_URL

# Tool con verificación 100% offline (<1 ms, sin coste de red)
@mcp.tool()
@kf.require_license
def inspect_schema(table_name: str) -> str:
    return f"Schema info for {table_name}"

# Tool monetizada por consumo: descuenta 5 créditos por consulta y reembolsa si falla
@mcp.tool()
@kf.metered(credits=5, offline_grace_calls=2, timeout_ms=1500)
async def optimize_query(sql_query: str) -> str:
    # Si la ejecución lanza una excepción o devuelve isError,
    # el decorador llama a POST /api/v1/quota/refund automáticamente.
    return "Optimized: " + sql_query
```

#### Ejemplo en TypeScript (Node.js MCP Server):
```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { createKeyFlint } from "keyflint-verify/mcp";

const server = new McpServer({ name: "CodeAuditor", version: "1.0.0" });
const kf = createKeyFlint();

server.tool(
  "audit_repository",
  { repoUrl: z.string() },
  kf.metered(10, async ({ repoUrl }) => {
    return { content: [{ type: "text", text: `Audit completed for ${repoUrl}` }] };
  })
);
```

#### Ejemplo en Go:
```go
package main

import (
    "fmt"
    "github.com/ArceeDev/keyflint/sdks/go-verify"
)

func main() {
    v, err := keyflint.NewVerifier("18a9fc...64-char-hex-public-key...")
    if err != nil {
        panic(err)
    }

    result, err := v.Verify("LIC-INDIE-eyJsaW...64-bytes-signature...")
    if err != nil {
        fmt.Printf("Licencia inválida: %v\n", err)
        return
    }

    fmt.Printf("Licencia válida. Tier: %s, Max Seats: %d\n", result.Payload.Tier, result.Payload.MaxSeats)
}
```

### 8.3. Herramienta CLI de Activación Zero-Friction
Pedir a usuarios no técnicos que editen manualmente el archivo `claude_desktop_config.json` provoca errores de sintaxis JSON. Los paquetes de npm y PyPI incluyen el comando CLI:
```bash
# Vía NPX (JavaScript)
npx keyflint-verify activate LIC-PRO-xxxx --client claude

# Vía UVX (Python)
uvx keyflint-verify activate LIC-PRO-xxxx --client cursor
```
* **Comportamiento:**
  1. Detecta automáticamente el sistema operativo (macOS, Windows `%APPDATA%`, Linux `~/.config`).
  2. Crea una copia de seguridad `claude_desktop_config.json.bak`.
  3. Inserta de forma segura la variable de entorno `"KEYFLINT_LICENSE": "LIC-..."` dentro del servidor MCP correspondiente sin alterar el resto de herramientas.
  4. Valida sintaxis JSON antes de guardar.

---

## 9. FRONTEND, CONSOLA Y ACTIVOS WEB

### 9.1. Arquitectura de `keyflint.dev` y Gateway Console
KeyFlint cuenta con dos interfaces estáticas sincronizadas mediante tests de paridad de bytes (`test_landing_v12.py`):
1. **Consola del Gateway (`app/presentation/static/index.html`):** Servida directamente por FastAPI en la raíz `/` de la instancia autoalojada. Conecta con los endpoints locales del servidor.
2. **Landing Pública (`docs/index.html` en GitHub Pages):** Hospedada en `keyflint.dev` con CDN global de Cloudflare.

### 9.2. Simulador Criptográfico en el Navegador (`docs/demo-api.js`)
Dado que GitHub Pages no dispone de backend dinámico para procesar llamadas POST, `docs/demo-api.js` intercepta las llamadas `fetch("/api/v1/licenses/issue")` y `fetch("/api/v1/licenses/verify")` directamente en el navegador del visitante utilizando la **Web Crypto API**:
* Genera pares de claves Ed25519 en memoria del navegador.
* Firma tokens reales `LIC-COMMUNITY-...` en el cliente.
* Permite al desarrollador probar la emisión, firma y verificación en menos de 1 segundo sin tocar servidores externos y sin fallos HTTP 405.

### 9.3. Activos de SEO y Descubribilidad
* **Sitemap:** `https://keyflint.dev/sitemap.xml` indexa la landing principal, la guía de monetización, la política de privacidad y el DPA.
* **Guía Long-Tail:** `docs/guides/paid-mcp-server.html` es una guía técnica completa indexada sobre cómo monetizar servidores MCP con Stripe y verificación Ed25519.
* **Esquema Estructurado JSON-LD:** Proporciona a Google y Bing los metadatos de producto de software, catálogo de ofertas y precios oficiales.

---

## 10. OPERACIONES, DESPLIEGUE Y RECUPERACIÓN ANTE DESASTRES (DR)

### 10.1. Topología de Despliegue en Fly.io (`fly.toml`)
* **Región:** `cdg` (París, Francia).
* **Tamaño de Máquina:** `shared-cpu-1x` (1 CPU compartida, 512 MB RAM).
* **Volumen Persistente:** `keyflint_data` de 1 GB montado en `/data`.
* **Regla Crítica de Escala:** `min_machines_running = 1`, `auto_stop_machines = "off"`. **KeyFlint corre exactamente en 1 máquina activa**. No debe escalarse horizontalmente a múltiples máquinas sobre el mismo archivo SQLite, ya que SQLite requiere acceso a un único sistema de archivos local para mantener el bloqueo WAL. La escalabilidad vertical y la replicación streaming resuelven la capacidad sobradamente para millones de peticiones diarias.

### 10.2. Replicación Litestream a Cloudflare R2 / AWS S3
* Litestream ejecuta como proceso supervisor en el contenedor Docker.
* Cada modificación del archivo WAL de SQLite se replica en streaming hacia el bucket de objetos (`LITESTREAM_BUCKET`).
* El Recovery Point Objective (RPO) es prácticamente de **0 segundos** (menos de 1 segundo de desfase).

### 10.3. Simulacro Horario de Restauración en Caliente (*Restore Drill*)
La mayoría de sistemas descubren que sus copias de seguridad están corruptas el día que necesitan restaurarlas. KeyFlint implementa una verificación activa periódica (`app/infrastructure/backup_check.py`):
1. Cada 60 minutos, el Gateway descarga la réplica de Litestream desde S3/R2 a un archivo temporal aislado en `/tmp`.
2. Ejecuta `sqlite3` sobre el archivo restaurado y compara el conteo de filas de `customers`, `licenses` y `webhook_events` contra la base de datos en vivo.
3. Si los conteos son consistentes, hace ping a la URL de monitorización (*Dead-man's switch* de Healthchecks.io):
   ```
   https://hc-ping.com/b78292df-ab5d-438d-bfae-c38539e68e57
   ```
4. Si la restauración falla o la réplica se atrasa, el endpoint `/api/v1/health` reporta `"backup": {"status": "failed"}` y envía un ping de fallo `.../fail` disparando alertas de guardia.

### 10.4. Canalizaciones CI/CD en GitHub Actions
El repositorio dispone de 5 workflows automatizados:
1. **`ci.yml` (Barrera de Calidad):** Ejecuta la matriz en Python 3.11, 3.12 y 3.13, la suite de conformidad de los SDKs (JS, Go, Python), el test de integración de contenedor, el test de restauración de backups y la auditoría de dependencias (`pip-audit`, `npm audit`, `govulncheck`).
2. **`release.yml`:** Al crear un tag `v*.*.*`, compila la imagen Docker, genera el SBOM (Software Bill of Materials) y publica en GitHub Container Registry (`ghcr.io/arceedev/keyflint:<tag>`).
3. **`deploy.yml`:** Despliegue con aprobación manual (*gated environment*) que actualiza la máquina de Fly.io y ejecuta un test de humo de producción (`scripts/smoke_prod.py`).
4. **`monitor.yml`:** Monitoriza proactivamente cada 15 minutos el endpoint de salud; si detecta anomalías, abre automáticamente un issue en GitHub etiquetado como `outage`.
5. **`publish-sdks.yml`:** Despacha releases automatizadas hacia PyPI y npm al etiquetar versiones de los SDKs.

---

## 11. MODELO COMERCIAL, PRECIOS Y GOBERNANZA

### 11.1. Tabla de Planes y Precios Oficiales

```
+---------------------------------------------------------------------------------------------------+
| PLAN               | PRECIO       | TIPO DE PAGO | NODOS | CRÉDITOS   | MODELO DE DESPLIEGUE      |
+--------------------+--------------+--------------+-------+------------+---------------------------+
| Community ($0)     | $0           | Gratuito     | 1     | 25         | Autoalojado (Open-Source) |
| Founder Lifetime   | $199         | Pago Único   | 10    | 25.000     | Autoalojado (100 unidades)|
| Indie License      | $149         | Pago Único   | 3     | 10.000     | Autoalojado (v1.x perpetua)|
| Agency License     | $349         | Pago Único   | 25    | 50.000     | Autoalojado (Agencias)    |
| Pro Cloud          | $29 / mes    | Suscripción  | 3     | 500 / mes  | Gateway Gestionado Cloud  |
| Studio Cloud       | $89 / mes    | Suscripción  | 25    | 5.000 / mes| Gateway Gestionado Cloud  |
+---------------------------------------------------------------------------------------------------+
```

### 11.2. Economía y Estructura de Costes
* **Coste mensual de infraestructura para KeyFlint:**
  - Fly.io Machine (`shared-cpu-1x`, 512MB RAM, 1GB volumen): ~$2.50 / mes.
  - Cloudflare R2 (Litestream backup): $0.00 (primeros 10 GB gratuitos).
  - Resend (Emails transaccionales): $0.00 (primeros 3.000 emails/mes gratuitos).
  - GitHub Pages (Landing y docs): $0.00.
  - **Coste total de operación:** **$\approx$ $2,50 a $3,00 dólares al mes**.
* **Margen operativo:** Superior al **98%**. La venta de una única licencia Indie ($149) financia más de 4 años de infraestructura del Gateway gestionado.
* **Garantía comercial:** Política de reembolso íntegro de 14 días reflejada en el código y en la landing page si el software no satisface las necesidades técnicas del comprador.

---

## 12. CONCLUSIÓN DEL ANÁLISIS

KeyFlint no es un simple script de validación, sino un **SaaS y plataforma de infraestructura de grado de producción completo**:
* Cumple rigurosamente con los estándares criptográficos modernos (Ed25519 RFC 8032).
* Su arquitectura hexagonal y base de datos SQLite WAL ofrecen un rendimiento de lectura y escritura del orden de microsegundos sin costes de servidores de base de datos dedicados.
* Protege a los desarrolladores de herramientas MCP y CLI contra abusos mediante Circuit Breakers, idempotencia transaccional y bloqueos por hardware/dominio.
* El ecosistema está empaquetado, verificado con 202 pruebas automatizadas y en vivo en producción en [keyflint.dev](https://keyflint.dev) y [licenses.keyflint.dev](https://licenses.keyflint.dev).
