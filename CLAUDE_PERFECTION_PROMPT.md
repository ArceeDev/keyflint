# PROMPT MAESTRO PARA CLAUDE: PERFECCIONAMIENTO TOTAL DE KEYFORGE v1.1.0

> **Instrucciones para el usuario**: Copia todo el bloque de texto que se encuentra entre los delimitadores `=== INICIO DEL PROMPT PARA CLAUDE ===` y `=== FIN DEL PROMPT PARA CLAUDE ===` y pégalo directamente en una nueva conversación con Claude (Claude 3.5 Sonnet / Claude 3.7 / Claude Opus).

---

=== INICIO DEL PROMPT PARA CLAUDE ===

Actúa como un Principal Software Architect, Staff Security Engineer y Director de Producto y UX de primer nivel (al estilo de los equipos fundadores de Stripe, Fly.io, Tailwind y Linear). 

Tu misión es realizar una **auditoría y perfeccionamiento integral de KeyForge**, un producto de software monetizable de grado de producción que acabamos de llevar a la versión **v1.1.0**. Necesito que elimines cualquier rastro de "AI slop", detectes inconsistencias técnicas, afiles el copy comercial y proporciones código y documentación de reemplazo directo para que el proyecto sea una obra de arte técnica y comercial.

---

### 1. CONTEXTO COMPLETO DEL PROYECTO

**¿Qué es KeyForge?**
KeyForge es una pasarela de licenciamiento criptográfico y medición atómica de cuotas de uso (credits) diseñada específicamente para la nueva ola de creadores de software:
- Servidores MCP (Model Context Protocol).
- Agentes de IA autónomos y herramientas CLI para desarrolladores.
- Micro-SaaS y aplicaciones de escritorio.

**El problema que resuelve:**
Plataformas como Keygen o Cryptolens cobran entre $49 y $499 **todos los meses**, obligan a depender de servidores de terceros y causan latencia en cada ejecución. KeyForge es **self-hosted**, se adquiere mediante pago único ($149 Indie / $349 Agency), y genera tokens Ed25519 (`LIC-<TIER>-<PAYLOAD>.<SIGNATURE>`) verificables **offline en <1 ms** sin llamadas de red obligatorias.

**Ficha Técnica Actual (v1.1.0):**
- **Arquitectura Backend**: FastAPI (Python 3.12+), Clean Architecture pura (Domain, Application, Infrastructure, Presentation).
- **Criptografía**: Ed25519 asimétrico (RFC 8032) con aceleración OpenSSL en el servidor y fallback puro en Python estándar (sin compilador C ni dependencias externas en clientes offline). Soporte de rotación dinámica de claves por `kid`.
- **Motor de Cuotas**: SQLite WAL en modo `BEGIN IMMEDIATE`, deduplicación transaccional `UNIQUE(license_id, idempotency_key)`, reintentos automáticos contra `SQLITE_BUSY` y ventana de reembolso (`POST /quota/refund`) de 900 segundos ante fallos de ejecución.
- **SDKs Oficiales de Cliente (`keyforge-verify`)**:
  - **TypeScript/JavaScript**: Zero-dependencies, usa Web Crypto API nativa (Node ≥18.4, Bun, Deno, Navegador). Incluye wrappers `@metered` y `requireLicense` para servidores MCP (`@modelcontextprotocol/sdk`).
  - **Python**: Biblioteca estándar pura (`verify_license`) con decoradores `@kf.metered` y `@kf.require_license` compatibles con FastMCP y el SDK oficial de MCP.
- **Distribución y Releases**:
  - Repositorio GitHub: `https://github.com/ArceeDev/keyforge`
  - Release v1.1.0: `https://github.com/ArceeDev/keyforge/releases/tag/v1.1.0` con binarios adjuntos (`.whl`, `.tar.gz`, `.tgz`).
  - Contenedor Docker oficial en GHCR: `ghcr.io/arceedev/keyforge:1.1.0`
- **Licenciamiento Dual**:
  - Servidor / Gateway: Licencia **BSL 1.1** (gratuito para desarrollo y evaluación no comercial; uso comercial requiere licencia comercial de pago único).
  - SDKs de cliente (`keyforge-verify` en npm y PyPI): Licencia **MIT**.
- **Estado de Pruebas**:
  - **152 tests deterministas pasando al 100%**:
    - Gatekeeper de producción: **7/7 puertas aprobadas** (AST, Type-hints, Schema SQLite, Criptografía RFC 8032, Atomicidad ACID bajo concurrencia, CLI, E2E).
    - Backend E2E: 79/79 tests pasando.
    - SDK TypeScript: 57/57 tests pasando (43 vectores de conformidad idénticos al backend).
    - SDK Python: 16/16 tests pasando.

**Evolución Visual Previa:**
En una iteración anterior ya se erradicó la plantilla genérica oscura de neón y se adoptó una estética editorial de ingeniería inspirada en publicaciones técnicas clásicas:
- Paleta: Modo claro principal con fondo de papel cálido (`#F6F5F1`), modo oscuro carbón cálido (`#141311`), y un único acento funcional color hierro al rojo (`#A63D12`).
- Tipografía: IBM Plex Sans y IBM Plex Mono (con cero barrado para datos técnicos, endpoints y tokens).
- Consola web interactiva en `/` con 44 selectores DOM estables, badges de estado OK/AVISO/ERROR por CSS `::before` y feedback mediante toasts accesibles.

---

### 2. TUS TAREAS ESPECÍFICAS DE PERFECCIONAMIENTO

Revisa meticulosamente el proyecto y genera las siguientes entregas sin rodeos ni preámbulos innecesarios:

#### TAREA 1: Reemplazo Drop-in del `README.md` Principal de la Raíz
El `README.md` actual tiene inconsistencias graves que deben corregirse de inmediato:
- Todavía dice `v1.0.0` y tiene badges desactualizados (badge de MIT en el servidor en lugar de BSL 1.1, dice 69 tests en vez de 79 backend / 152 totales).
- Menciona la antigua consola "B2B dark web console" que ya fue eliminada.
- No incluye los comandos de instalación directa de los SDKs desde la Release v1.1.0 de GitHub (`pip install ...whl`, `npm install ...tgz`) ni la imagen Docker oficial de GHCR (`ghcr.io/arceedev/keyforge:1.1.0`).
- No muestra ejemplos claros del decorador `@metered` para MCP.

**Qué debes entregar**: El archivo `README.md` completo, redactado en inglés impecable, técnico, sobrio, sin clichés de marketing, estructurado como los mejores proyectos open-core (Stripe, Supabase, Tailwind). Debe incluir:
1. Badges oficiales (Version 1.1.0, Python 3.12+, BSL 1.1 Gateway / MIT SDKs, Tests 152/152 pass, Docker GHCR).
2. Propuesta de valor en 3 párrafos de alta densidad informativa.
3. Quickstarts claros para:
   - Levantar el servidor en Docker (`docker run -d -p 8788:8788 ghcr.io/arceedev/keyforge:1.1.0`).
   - SDK TypeScript (offline verify + MCP `@metered`).
   - SDK Python (offline verify + FastMCP `@metered`).
4. Arquitectura criptográfica (RFC 8032 Ed25519, SQLite WAL ACID debits, rotación de kid, refund window).
5. Matriz de comparación objetiva contra SaaS tradicionales (Keygen, Cryptolens, Stripe Usage-based).
6. Modelo de licenciamiento explicado con total claridad jurídica y comercial (BSL 1.1 vs MIT).

---

#### TAREA 2: Auditoría del Kit de Lanzamiento Comercial (`COMMERCIAL_LAUNCH_KIT.md`)
Revisa la estrategia de monetización y el copy comercial:
1. **Precios y Posicionamiento**: Explicar con precisión matemática por qué pagar $149 (Indie) o $349 (Agency) una sola vez es infinitamente superior a regalarle $600/año a un SaaS de licencias.
2. **Manejo de Objeciones de Desarrolladores**:
   - *"¿Por qué no uso simplemente JWTs firmados con HMAC?"* (Explicar la asimetría de Ed25519: la clave privada nunca sale del servidor, los clientes nunca pueden falsificar tokens, y cómo se evita el ataque de algoritmo "none" o la filtración de secretos compartidos).
   - *"¿Cómo evito que me hagan trampas con la hora del sistema en offline?"* (Explicar el modelo de tokens con expiración y el balance entre conveniencia air-gapped y re-validación periódica).
   - *"¿Cómo gestiono reembolsos si mi llamada a Claude/OpenAI falla a mitad de camino?"* (Explicar la ventana de 900s de `POST /quota/refund` y el `idempotency_key`).
3. **Copy de Lanzamiento para Hacker News / Show HN y X (Twitter)**:
   - Proporciona un borrador de **"Show HN: KeyForge – Self-hosted Ed25519 licensing & credit metering for MCP servers"** que respete las pautas no publicitarias de Hacker News (enfocado en arquitectura, decisiones de diseño, fallas que superamos y lecciones aprendidas).
   - Un hilo de X conciso y técnico de 5 tweets, sin emojis exagerados ni hype.

---

#### TAREA 3: Auditoría de Experiencia de Desarrollador (DX)
Analiza el flujo de adopción de un desarrollador que encuentra KeyForge por primera vez:
1. **Time-to-First-Token**: ¿Cómo lograr que un desarrollador pase de leer el README a verificar su primer token o proteger una herramienta MCP en menos de 60 segundos?
2. **Manejo de Errores MCP**: Evalúa los códigos JSON-RPC implementados (`-32040` token inválido, `-32041` feature restringida, `-32042` sin saldo / HTTP 402, `-32043` gateway error). ¿Son los más limpios para que Claude / ChatGPT muestren un mensaje de error accionable con el enlace de compra o recarga?
3. Si detectas cualquier aspereza en las interfaces TypeScript o Python, propon la mejora exacta.

---

### 3. REGLAS DE TONO Y ESTILO

1. **Cero AI Slop**: Prohibido usar palabras vacías como "unleash", "delve", "game-changer", "revolutionary", "seamlessly", "cutting-edge". Usa verbos concretos y sustantivos específicos.
2. **Precisión Técnica Absoluta**: Respeta los hechos demostrados (Ed25519, RFC 8032 §5.1.3, SQLite WAL `BEGIN IMMEDIATE`, 152 tests, <1 ms de latencia offline).
3. **Entregables Inmediatos**: Entrega el contenido listo para copiar y pegar directamente en los archivos del repositorio.

¡Adelante!
=== FIN DEL PROMPT PARA CLAUDE ===
