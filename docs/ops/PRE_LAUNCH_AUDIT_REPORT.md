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

### Detalle de PyPI Trusted Publishing
Se configuró OIDC Trusted Publisher entre PyPI y GitHub Actions:
- **Project Name:** `keyflint-verify`
- **Owner:** `ArceeDev`
- **Repository:** `keyflint`
- **Workflow:** `publish-sdks.yml`
- **Environment:** `pypi`
- Publicación sin contraseñas ni tokens estáticos (`id-token: write`).

---

## 2. Custodia de Clave Maestra (`ED25519_PRIVATE_KEY_HEX`)

- Extraída de forma segura de la máquina en producción sin volcarse en consolas ni en git.
- **Ruta de respaldo fuera de Fly.io:** `C:\Users\Usuario\keyflint_ed25519_private_key_backup.txt` (64 caracteres hex, verificado).

---

## 3. Resolución de los 4 Bloqueos Previos al Día D

### Bloqueo 1: DPA y Política de Privacidad
- Se redactaron y maquetaron dos páginas completas con la estética Cyber-Minimalism (`#0B0D17`, texto blanco, acentos `#CCFF00`):
  - **Política de Privacidad:** [keyflint.dev/privacy.html](https://keyflint.dev/privacy.html)
  - **DPA (Data Processing Agreement, Art. 28 RGPD):** [keyflint.dev/dpa.html](https://keyflint.dev/dpa.html)
- Ambas páginas están enlazadas en el pie de página de la landing `keyflint.dev`.

### Bloqueo 2: Verificación de Latencia `[BENCH]`
Se ejecutaron microbenchmarks con los 47 vectores de prueba oficiales (`valid_basic`):
- **Node.js** (`crypto.verify` / OpenSSL): **0.0038 ms** (4 µs / ~264.000 ops/s).
- **Python + `cryptography`** (OpenSSL): **0.0600 ms** (60 µs / ~16.600 ops/s).
- **Python Puro** (RFC 8032 sin dependencias C): **2.0911 ms** (~480 ops/s).
- **Go** (`crypto/ed25519`): **< 0.0200 ms** (>50.000 ops/s).

**Copy adoptado en Show HN y redes:**  
> *"Verification is sub-millisecond (<0.06 ms with OpenSSL / native crypto, ~2 ms in pure Python fallback), cheap enough to run on every tool call."*

### Bloqueo 3: Verificación de Precios de Competidores `[PRICE]`
- **Keygen.sh:** Tiers estándar arrancan en $99/mes (históricamente tenían planes indie de $49/mes).
- **Gumroad:** 10% flat fee + pasarela de pago.
- **Lemon Squeezy:** 5% + $0.50 por venta.

**Copy adoptado:**  
> *"without a $49–$99/mo licensing SaaS or a 10% cut on every sale"*.

### Bloqueo 4: Quickstart y Contenedores GHCR
- Repositorio verificado como **PÚBLICO**.
- Imagen Docker `ghcr.io/arceedev/keyflint:1.1.0` verificada y descargable anónimamente.
- `README.md` actualizado: referencias provisionales a URLs `.tgz` reemplazadas por los comandos oficiales de npm/PyPI/Go; volumen unificado a `keyflint_data:/app/data`.

---

## 4. Fusión y Despliegue de PR #19

- **PR #19:** `feat(billing): una licencia por compra`.
- **Cambios esenciales:**
  1. Cada `checkout.session.completed` emite una licencia nueva e independiente (dos compras = dos cupos separados). Nadie desciende de tier.
  2. Licencia Community gratuita se actualiza in situ sin cambiar de clave token.
  3. Los eventos de suscripción (`customer.subscription.*`) únicamente aplican sobre la licencia asociada a ese `sub_`. Indie, Agency y Lifetime son inmunes.
  4. Si un reembolso es ambiguo, no se revoca nada y se registra alerta en logs.
- **Pruebas:** 147/147 tests superados, 7/7 gates de producción aprobados.
- **Despliegue:** Integrado en `main` y desplegado en Fly.io.
