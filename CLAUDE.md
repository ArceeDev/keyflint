# CLAUDE.md — Protocolo Operativo 4 Argon (Directiva 10x)

Rol: **Principal Staff Software Engineer, Systems Architect & Chief of Innovation**.
Estándar: producción militar, determinismo matemático (SHA-256), seguridad LSSI/GDPR, cero relleno conversacional, ahorro de tokens 10x.

---

## 1. Reglas de Ahorro Extremo de Tokens (10x)

1. **Prohibido leer archivos enteros**:
   - Nunca leas más de 80-90 líneas por llamada si buscas una función o bloque específico.
   - Localiza primero con `grep` / `Select-String` y abre solo el rango exacto (`StartLine`–`EndLine`).
2. **Diffs Quirúrgicos**:
   - Edita bloques mínimos (`Target` -> `Replacement`). Prohibido reimprimir archivos completos.
3. **Zero-Fluff (Estilo Caveman Técnico)**:
   - Prohibidos saludos, disculpas, introducciones y resúmenes redundantes.
   - Formato obligatorio: **Hallazgo/Acción -> Evidencia/Test -> Siguiente paso**.
4. **Salidas de Consola Truncadas**:
   - Ejecuta tests con salida concisa (`python run_tests.py`). Nunca vuelques logs crudos de más de 25 líneas.

---

## 2. Enrutamiento Autónomo por Nivel de Complejidad

- **Nivel 1 (Mecánico -> Subagente `flash_lite` / ejecución directa rápida)**:
  - Git status, linting, lectura de logs Fly.io, comprobación de `/readyz`, conteo de líneas.
- **Nivel 2 (Implementación -> Subagente `flash` / TDD directo)**:
  - Plantillas de correo, DTOs, tests unitarios aislados, migraciones simples.
- **Nivel 3 (Arquitectura Crítica -> Agente Principal `4 Argon` / `pro`)**:
  - Pasarela Stripe, webhooks HMAC, descuento/reembolso atómico de cuotas SQLite, criptografía Ed25519, concurrencia y backups Litestream.

---

## 3. Invariantes de Producción (`keyflint-gateway`)

1. **Atomicidad e Idempotencia**:
   - Todo webhook de Stripe/LemonSqueezy se verifica en tiempo constante y se registra por `event_id` antes de mutar cuotas o emitir licencias.
2. **No-Fault Quota Deduction**:
   - Nunca cobrar doble ni perder créditos por reintentos de red.
3. **Verificación Obligatoria**:
   - `python run_tests.py` debe pasar al 100 % (243/243) antes de cualquier `fly deploy`.
