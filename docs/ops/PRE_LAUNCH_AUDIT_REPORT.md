# KeyFlint v1.1.0 · Informe Técnico Pre-Lanzamiento y Auditoría

**Fecha:** 2 de noviembre de 2026  
**Entorno de Producción:** `https://licenses.keyflint.dev/`  
**Web Pública:** `https://keyflint.dev`  
**Repositorio:** `https://github.com/ArceeDev/keyflint` (Público)

---

## 1. Estado de los Registros Oficiales de SDKs

Todos los SDKs de verificación criptográfica offline (MIT) están publicados y operativos en sus registros públicos estándar:

| SDK / Lenguaje | Registro | Paquete / Módulo | Estado | Comando de Instalación |
|---|---|---|---|---|
| **Python** | PyPI | `keyflint-verify` | **v1.1.0 Live** | `pip install keyflint-verify` |
| **Node.js / TS** | npm | `keyflint-verify` | **v1.1.0 Live** | `npm install keyflint-verify` |
| **Go** | proxy.golang.org | `github.com/ArceeDev/keyflint/sdks/go-verify` | **v1.1.0 Live** | `go get github.com/ArceeDev/keyflint/sdks/go-verify@v1.1.0` |

---

## 2. Custodia de Clave Maestra (`ED25519_PRIVATE_KEY_HEX`)

- Extraída de forma segura de la máquina en producción sin volcarse en consolas ni en git.
- **Ruta de respaldo fuera de Fly.io:** `C:\Users\Usuario\keyflint_ed25519_private_key_backup.txt` (64 caracteres hex, verificado).

---

## 3. Resolución de los 4 Bloqueos Previos al Día D

1. **DPA y Política de Privacidad:**
   - [keyflint.dev/privacy.html](https://keyflint.dev/privacy.html)
   - [keyflint.dev/dpa.html](https://keyflint.dev/dpa.html)
   - Enlazados en el pie de página de `keyflint.dev`.
2. **Latencia `[BENCH]` comprobada:**
   - Node.js (OpenSSL): **0.0038 ms** (4 µs / ~264.000 ops/s).
   - Python + `cryptography`: **0.0600 ms** (60 µs / ~16.600 ops/s).
   - Python Puro: **2.0911 ms** (~480 ops/s).
   - Go: **< 0.0200 ms** (>50.000 ops/s).
   - Copy: `<0.06 ms per check with OpenSSL / native crypto`.
3. **Precios de Competidores `[PRICE]` comprobados:**
   - Keygen ($99/mo std / $49 legacy), Gumroad (10%), Lemon Squeezy (5% + 50¢).
   - Copy: `without a $49–$99/mo licensing SaaS or a 10% cut on every sale`.
4. **Quickstart y Contenedores GHCR:**
   - Repositorio público, imagen `ghcr.io/arceedev/keyflint:1.1.0` accesible, README actualizado.

---

## 4. PRs Fusionados y Desplegados en Producción

- **PR #19:** `feat(billing): una licencia por compra` (Merged & Deployed).
- **PR #20:** `fix(security): rate limit con Fly-Client-IP` (Merged & Deployed).
  - Evita eludir el rate limit mediante cabeceras falseadas.
- **PR #21:** `feat(ops): alertas por correo en incidencias de cobro` (Merged & Deployed).
  - Configurado en Fly.io: `OPS_ALERT_EMAIL=support@keyflint.dev`.
  - Notifica en tiempo real sobre errores en webhooks, reembolsos ambiguos o compras anónimas.
- **PR #22:** `feat(landing): vista previa social (Open Graph + Twitter card)` (Merged & Live en Pages).
  - Etiquetas OG + Twitter card operativas con imagen en [keyflint.dev/og.png](https://keyflint.dev/og.png).
- **Analítica Web:** Cloudflare Web Analytics integrada y activa en todas las páginas públicas (`index.html`, `privacy.html`, `dpa.html`) sin cookies y con token `3f969046e620462787c3a0fa2515d7e8`.

---

## 5. Estado de Producción Live

```json
{
  "status": "ok",
  "healthy": true,
  "email_provider": "resend",
  "backup": {
    "status": "ok",
    "checked_at": "2026-11-02T20:12:40.825369+00:00"
  }
}
```
- Ping a `healthchecks.io` reportando 200 OK.
