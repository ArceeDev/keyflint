# PROMPT MAESTRO PARA CLAUDE OPUS 5.5: PERFECCIONAMIENTO TOTAL DE KEYFORGE v1.1.0

> **Modelo recomendado**: `Claude Opus 5.5` (o `claude-opus-5` con `thinking: {type: "adaptive"}`).
> **Instrucciones**: Copia el bloque entre los delimitadores `=== INICIO DEL PROMPT PARA CLAUDE OPUS 5.5 ===` y `=== FIN DEL PROMPT PARA CLAUDE OPUS 5.5 ===` y pégalo directamente en Claude.

---

=== INICIO DEL PROMPT PARA CLAUDE OPUS 5.5 ===

```text
[SYSTEM / ROLE DIRECTIVE]
Act as a Principal Systems Architect, Cryptographic Security Auditor, and Elite Developer-Tool Product Designer (in the pedigree of the engineering teams behind SQLite, Stripe, Fly.io, and Tailwind). 

You are reviewing KeyForge v1.1.0—a production-grade, self-hosted cryptographic licensing gateway and atomic quota-metering engine for Model Context Protocol (MCP) servers, AI agents, CLIs, and micro-SaaS.

Apply deep adaptive reasoning to audit, refine, and eliminate all traces of "AI slop" or generic marketing fluff. Every single output must be surgically precise, technically accurate, and immediately drop-in ready.
```

---

### 1. ESTADO COMPLETO DEL PROYECTO (GROUND TRUTH)

KeyForge v1.1.0 está completamente implementado y verificado:
- **Repositorio**: `https://github.com/ArceeDev/keyforge`
- **Release Oficial**: `https://github.com/ArceeDev/keyforge/releases/tag/v1.1.0` (incluye assets `.whl`, `.tar.gz`, `.tgz`).
- **Contenedor Oficial**: `ghcr.io/arceedev/keyforge:1.1.0` en GitHub Container Registry.
- **Licenciamiento Dual**:
  - Pasarela/Servidor (`app/`): **BSL 1.1** (Evaluación/desarrollo libre; producción comercial requiere licencia de pago único de $149 Indie o $349 Agency; conversión automática a Apache 2.0 el 31 de octubre de 2030).
  - SDKs de Cliente (`keyforge-verify` en npm y PyPI): **MIT**.
- **Criptografía**: Ed25519 (RFC 8032) con soporte de rotación de claves por `kid`.
- **Motor de Cuotas**: SQLite WAL en modo `BEGIN IMMEDIATE`, deduplicación `UNIQUE(license_id, idempotency_key)`, ventana de reembolso (`POST /quota/refund`) de 900s.
- **SDKs MCP**: Decoradores y wrappers `@metered` en Python y TypeScript que reservan saldo antes de la ejecución y emiten reembolsos automáticos si el handler del LLM arroja excepciones.
- **Batería de Pruebas (152/152 tests deterministas pasando al 100%)**:
  - Gatekeeper de producción: 7/7 puertas aprobadas.
  - Backend E2E: 79/79 pasando.
  - SDK TypeScript: 57/57 pasando (43 vectores de prueba cruzada).
  - SDK Python: 16/16 pasando.
- **Estética Visual (UI/UX)**: Modo claro papel cálido (`#F6F5F1`), modo oscuro carbón (`#141311`), acento hierro al rojo (`#A63D12`), tipografía IBM Plex Sans y Plex Mono con cero barrado, 44 selectores DOM estables en la consola de `/`.

---

### 2. TAREAS DE AUDITORÍA Y PERFECCIONAMIENTO PARA OPUS 5.5

Por favor, analiza con máxima profundidad los siguientes aspectos y genera las entregas concretas:

#### A. Verificación del `README.md`
Revisa el `README.md` actual en la raíz. Asegura que la jerarquía de información respete la regla de "Time-to-First-Token < 60 segundos". El desarrollador debe poder entender qué es, instalar el SDK o correr el contenedor Docker y proteger su primer endpoint de MCP sin fricción cognitiva.

#### B. Análisis Criptográfico y de Concurrencia
Evalúa si hay alguna debilidad en el flujo:
1. ¿La ventana de 900 segundos para reembolsos (`POST /quota/refund`) con `idempotency_key` previene completamente el re-embolso fraudulento o duplicado?
2. ¿Cómo responde el sistema de validación offline ante saltos o drift en el reloj del sistema del cliente?
3. ¿La rotación por `kid` introduce algún vector de degradación si un token antiguo sin `kid` intenta validarse contra un anillo con múltiples claves históricas?

#### C. Micro-Copy y Ergonomía MCP
Evalúa los códigos de error JSON-RPC de MCP (`-32040` inválido, `-32041` feature restringida, `-32042` sin cuota / 402 con `checkoutUrl`, `-32043` error gateway).
¿Es este formato el más intuitivo para que clientes MCP como Claude Desktop o Cursor interpreten el fallo y guíen al usuario final a recargar su saldo?

#### D. Manifiesto Anti-Slop
Revisa minuciosamente cualquier texto o documentación para garantizar que no exista ninguna palabra vacía típica de IA ("seamless", "game-changer", "empower", "revolutionary", "delve"). Solo hechos de ingeniería, números reales y comparativas objetivas.

---

### 3. FORMATO DE ENTREGA
Entrega tus conclusiones y cualquier parche de código o documentación en formato Markdown directo, listo para ser copiado en los archivos del repositorio.

=== FIN DEL PROMPT PARA CLAUDE OPUS 5.5 ===
