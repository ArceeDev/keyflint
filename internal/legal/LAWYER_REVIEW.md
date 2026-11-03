# Revisión legal pendiente: privacidad y DPA

> **Esto no es asesoramiento legal.** Las páginas `docs/privacy.html` y `docs/dpa.html` son una traducción al inglés de borradores escritos sin abogado. Hasta que un abogado (RGPD/LOPDGDD) las revise, muestran el aviso "Draft pending legal review". Quitar ese aviso solo tras la revisión.

Borradores fuente en español: `PRIVACIDAD_BORRADOR.md`, `DPA_BORRADOR.md`.

## Cambios respecto al texto español (verificar)

- [ ] Pagos: se quitó Lemon Squeezy (no se usa); queda Stripe con Managed Payments como Merchant of Record.
- [ ] Cookies: se añadió Cloudflare Web Analytics (sin cookies), que ya está en las páginas.
- [ ] Cloudflare: además de R2, figura como DNS, reenvío de correo (support@) y analítica.
- [ ] "cuentas de usuario" se omitió: el producto no tiene cuentas.

## Puntos que debe revisar el abogado

### Identidad y jurisdicción
- [ ] Identificación del responsable: "KeyFlint (ArceeDev)" no es una persona física ni jurídica identificable. Art. 13.1.a RGPD exige nombre/razón social, NIF y dirección postal.
- [ ] ¿Hace falta DPO (art. 37)? Probablemente no, confirmar.
- [ ] Ley aplicable y fuero del DPA.

### Política de privacidad
- [ ] Bases jurídicas por tratamiento (tabla de la sección 2), en especial soporte técnico (interés legítimo vs. contrato).
- [ ] Plazos de conservación: 90 días logs web, 30 días Resend, 2 años soporte, "plazos fiscales" (concretar: 4 años LGT / 6 años Código de Comercio).
- [ ] Logs de Fly.io: el gateway registra IP de cliente (rate limit por `Fly-Client-IP`); ¿se menciona suficientemente?
- [ ] Rol de Stripe Managed Payments como Merchant of Record: ¿Stripe es responsable independiente de los datos de compra? Ajustar la redacción.
- [ ] Transferencias internacionales (sección 4): confirmar que cada proveedor de EE. UU. está adherido al DPF o firma SCC.
- [ ] Usuarios finales (sección 6): la frase "KeyFlint no almacena tus datos de uso salvo por cuenta del desarrollador" solo es cierta en Managed; en self-hosted KeyFlint no recibe nada.
- [ ] Derecho a retirar consentimiento y decisiones automatizadas (art. 13.2): indicar que no aplica si es así.

### DPA (art. 28.3 RGPD)
- [ ] Faltan cláusulas obligatorias: duración, tipo de datos completo, auditorías/inspecciones (28.3.h), autorización general vs. específica de subencargados y aviso de cambios con derecho de oposición (28.2), obligaciones del responsable.
- [ ] Plazo concreto de notificación de brechas (p. ej. 48-72 h) en lugar de "sin dilación indebida".
- [ ] Lista de subencargados: añadir Stripe si procesa datos de usuarios finales del Cliente; confirmar si Resend envía correos a usuarios finales del Cliente.
- [ ] Ubicación de Resend (EE. UU.) y mecanismo de transferencia.
- [ ] Medidas de seguridad (art. 32): "TLS 1.3" y "cifrado en reposo en R2" deben verificarse; Fly.io volúmenes cifrados en reposo.
- [ ] Devolución/supresión (28.3.g): 7 días de gracia; ¿y las copias de R2 (retención 720 h = 30 días)? Debe constar que los backups se borran a los 30 días.
- [ ] Forma de aceptación (clic al contratar Managed) y versión/fecha del DPA.
- [ ] Responsabilidad y limitación de responsabilidad.

### Otros documentos que faltan
- [ ] Términos de servicio / condiciones de venta (reembolso 14 días, Lifetime/Founder "v1.x + v2.x", tiers perpetuos).
- [ ] Aviso legal (LSSI-CE art. 10): datos identificativos del titular del sitio.
- [ ] Revisar `LICENSE` (BSL 1.1) frente a lo que promete la landing.

Bloquea: lanzar KeyFlint Managed. El self-hosted y la venta de licencias pueden seguir con el aviso de borrador.
