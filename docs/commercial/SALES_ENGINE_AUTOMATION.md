# KeyFlint — Autonomous Sales & Marketing Playbook

> **Sistema de Comercialización Automatizada**: Antigravity (Ingeniería y Operaciones) + Claude (Copywriting y Estrategia) + Fundador (Aprobador y Titular de Cuentas).

---

## 1. El Trío Operativo: ¿Quién hace qué?

| Rol | Agente / Persona | Responsabilidades |
| :--- | :--- | :--- |
| **Director de Producto & Infraestructura** | **Antigravity** (Yo) | - Mantiene 167/167 tests y release gates al 100%.<br>- Empaqueta SDKs, Docker en GHCR y plantillas de 1-click deploy.<br>- Ejecuta scripts de prospección automática (identificar creadores de MCP en GitHub). |
| **Director de Copywriting & Adquisición** | **Claude** (Opus 5.5) | - Redacta posts virales de alta densidad para Hacker News (*Show HN*).<br>- Diseña hilos educativos en X (Twitter) mostrando el demo en vídeo.<br>- Redacta mensajes de venta directos y personalizados para creadores de MCP.<br>- Optimiza los textos de conversión en LemonSqueezy/Gumroad. |
| **Fundador & Dueño del Negocio** | **Tú** | - Configuras la cuenta receptora de fondos (LemonSqueezy / Stripe).<br>- Apruebas los lanzamientos con un solo clic.<br>- Recibes el 100% del dinero de las ventas. |

---

## 2. Los 3 Motores de Venta Automatizados

### Motor 1: El Boom de Model Context Protocol (MCP)
- **Oportunidad**: En GitHub hay más de 3.000 repositorios de servidores MCP creados en los últimos 4 meses. **Ninguno tiene sistema de cobro.**
- **Acción automatizada**:
  1. Con la API de GitHub, buscamos repositorios que usen `@modelcontextprotocol/sdk` o `mcp.server.fastmcp`.
  2. Filtramos creadores con más de 20 estrellas que ofrezcan herramientas útiles (scraping, SQL, análisis de datos).
  3. Claude genera un email o mensaje directo de 3 párrafos mostrándoles cómo poner un `@metered(credits=5)` en su repo para monetizar su trabajo sin pagar suscripciones a nadie.

### Motor 2: Tráfico Orgánico de Alta Autoridad (Hacker News + Reddit)
- **Hacker News (Show HN)**: Los ingenieros de HN desprecian la publicidad pero adoran la buena arquitectura técnica. El post se centra en:
  - *"Cómo resolvimos la verificación offline en 0.13 ms con OpenSSL y fallback puro en Python".*
  - *"Cómo SQLite WAL con BEGIN IMMEDIATE elimina race-conditions en créditos concurrentes".*
  - El enlace lleva directamente a la demo interactiva y al repositorio de GitHub.
- **Subreddits clave**: `r/ClaudeAI`, `r/cursor`, `r/LocalLLaMA`, `r/SideProject`.

### Motor 3: Directorios y Ecosistemas de IA
Listar KeyFlint en:
1. **PulseMCP** (`pulsemcp.com`): El directorio de referencia de herramientas MCP.
2. **Smithery.ai**: El registro de servidores MCP para Cursor y Claude.
3. **Awesome-MCP-Servers** (Repositorio de GitHub con miles de estrellas).
*Posicionamiento*: "KeyFlint – The official open monetization gateway for MCP tools".

---

## 3. Oferta Comercial Lista para Publicar

### Producto A: Licencia Indie ($149 pago único)
- Acceso completo al código fuente de la Gateway (BSL 1.1).
- Servidor Docker listo para desplegar en 1 clic (Railway / Render / VPS).
- SDKs oficiales (TypeScript & Python) con decorador `@metered` y auto-reembolsos.
- Actualizaciones gratuitas a la rama v1.x.

### Producto B: Licencia Agency / Studio ($349 pago único)
- Todo lo de la licencia Indie.
- Permiso para desplegar instancias multi-inquilino para clientes.
- Soporte técnico prioritario y auditoría de integración.

---

## 4. Próxima Acción Inmediata (Checklist de 10 minutos)
1. **Crear producto en LemonSqueezy o Gumroad**:
   - Nombre: `KeyFlint – Self-Hosted MCP & AI Licensing Gateway`.
   - Precio: $149.
   - Descripción: Copiar y pegar el texto listo de `COMMERCIAL_LAUNCH_KIT.md` (Sección 3).
2. **Publicar el Show HN**:
   - Copiar el texto de `COMMERCIAL_LAUNCH_KIT.md` (Sección 4).
3. **Nosotros nos encargamos del resto**:
   - Cada actualización, mejora de código, soporte a compradores y optimización de conversión la resolvemos Claude y yo.
