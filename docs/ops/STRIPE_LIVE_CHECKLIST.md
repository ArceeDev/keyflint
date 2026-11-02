# Stripe live: checklist antes de aceptar pagos reales

Estado verificado el 2026-11-02. Mientras falte cualquier punto marcado ❌, **una compra live cobra pero no entrega licencia**.

| # | Punto | Estado |
|---|-------|--------|
| 1 | 4 Payment Links live en `docs/` y consola (`/test_` eliminado) | ✅ (guardado por `tests/tier2_boundaries/test_payment_links.py`) |
| 2 | Dominio `keyflint.dev` y `licenses.keyflint.dev` apuntando a la gateway | ✅ DNS y TLS Let's Encrypt activo |
| 3 | Gateway desplegada (Fly `cdg` + R2/Litestream) con `KEYFLINT_ENV=production` | ❌ |
| 4 | Webhook **live** creado → `https://licenses.keyflint.dev/api/v1/webhooks/stripe` con `checkout.session.completed`, `invoice.payment_succeeded`, `customer.subscription.deleted` | ❌ (el actual `we_1UWv5N…` es de test) |
| 5 | `STRIPE_WEBHOOK_SECRET` = `whsec_` **live** en la gateway (`fly secrets set`) | ❌ |
| 6 | Cada Payment Link live tiene `metadata.tier` = `indie` / `agency` / `pro` / `studio` | ✅ Verificado en `payment_links.csv` |
| 7 | Email transaccional (Resend/SMTP) con dominio verificado | ❌ depende de 2 |

## Por qué importa `metadata.tier`

`BillingService._extract_webhook_context` toma el tier de `session.metadata.tier` (Stripe copia la metadata del Payment Link a la Checkout Session). Si falta, **cae a `pro` por defecto**: un comprador de Agency recibiría una licencia Pro. Mapeo actual: `indie→PRO`, `agency→STUDIO`, `pro→PRO`, `studio→STUDIO`.

Comprobación (Dashboard → Payment Links → cada enlace → Metadata), o:

```bash
stripe payment_links retrieve plink_1UXIly0g6p4KL4GWrF1MVWWA --live | jq .metadata
```

## Comportamiento conocido del webhook (sin cambios en este PR)

- **Idempotencia**: por `event.id` en `webhook_events`; un reintento de Stripe devuelve `already_processed`. Firma HMAC con tolerancia de 300 s.
- **Reembolsos Stripe**: `charge.refunded` **no** está suscrito ni gestionado → reembolsar **no revoca** la licencia. Revocar a mano (`POST /api/v1/licenses/revoke` o CLI) tras cada reembolso.
- Pagos únicos (Indie/Agency) no emiten `invoice.payment_succeeded` ni `customer.subscription.deleted`.

## Compra de prueba real

Solo cuando 2–6 estén en ✅. Hasta entonces, si alguien compra: el dinero llega, Stripe reintenta el webhook hasta 3 días; despliega la gateway dentro de ese plazo y los eventos se procesarán (o reenvíalos desde Dashboard → Webhooks → Resend).
