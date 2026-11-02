# Stripe live: checklist antes de aceptar pagos reales

Estado verificado el 2026-11-02. Mientras falte cualquier punto marcado ❌, **una compra live cobra pero no entrega licencia**.

| # | Punto | Estado |
|---|-------|--------|
| 1 | 4 Payment Links live en `docs/` y consola (`/test_` eliminado) | ✅ (guardado por `tests/tier2_boundaries/test_payment_links.py`) |
| 2 | Dominio `keyflint.dev` y `licenses.keyflint.dev` apuntando a la gateway | ✅ DNS y TLS Let's Encrypt activo |
| 3 | Gateway desplegada (Fly `cdg` + R2/Litestream) con `KEYFLINT_ENV=production` | ✅ Activa en `licenses.keyflint.dev` |
| 4 | Webhook **live** creado → `https://licenses.keyflint.dev/api/v1/webhooks/stripe` con `checkout.session.completed`, `invoice.payment_succeeded`, `customer.subscription.deleted` | ✅ Creado y activo en Stripe Live |
| 5 | `STRIPE_WEBHOOK_SECRET` = `whsec_` **live** en la gateway (`fly secrets set`) | ✅ Inyectado y verificado en Fly.io |
| 6 | Cada Payment Link live tiene `metadata.tier` = `indie` / `agency` / `pro` / `studio` | ✅ Verificado en `payment_links.csv` |
| 7 | Email transaccional (Resend/SMTP) con dominio verificado | ❌ depende de 2 |
| 8 | Webhook live suscrito además a `charge.refunded`, `charge.dispute.created`, `charge.dispute.closed` | ✅ Suscrito y activo en Stripe Live |

## Por qué importa `metadata.tier`

`BillingService._extract_webhook_context` toma el tier de `session.metadata.tier` (Stripe copia la metadata del Payment Link a la Checkout Session). Si falta, **cae a `pro` por defecto**: un comprador de Agency recibiría una licencia Pro. Mapeo actual: `indie→PRO`, `agency→STUDIO`, `pro→PRO`, `studio→STUDIO`.

Comprobación (Dashboard → Payment Links → cada enlace → Metadata), o:

```bash
stripe payment_links retrieve plink_1UXIly0g6p4KL4GWrF1MVWWA --live | jq .metadata
```

## Comportamiento conocido del webhook

- **Idempotencia**: por `event.id` en `webhook_events`; un reintento de Stripe devuelve `already_processed`. Firma HMAC con tolerancia de 300 s.
- **Reembolsos y disputas** (`BillingService._handle_stripe_payment_reversal`):
  - Al provisionar (`checkout.session.completed`) y renovar (`invoice.payment_succeeded`) se guardan en `license.metadata.payment_refs` los IDs de Stripe (`cs_`, `pi_`, `in_`, `sub_`, `cus_`).
  - Búsqueda de la licencia: `payment_intent`/`charge`/`invoice`/`subscription` → `customer` (`cus_`) → `billing_details.email`/`receipt_email`. Sin coincidencia: 200 con `no_matching_license` (Stripe no reintenta; revisar a mano).
  - `charge.refunded` **total** (`refunded=true` o `amount_refunded >= amount`) → **revoca** (ledger permanente, motivo `payment_refunded`). **Parcial** → no cambia nada (`partial_refund_ignored`); si reembolsos parciales suman el total, el último evento revoca.
  - Suscripciones: reembolsar cualquier cargo completo revoca la licencia (coincide por `cus_`). Cancelar la suscripción sigue llegando por `customer.subscription.deleted`. Para un reembolso de cortesía sin quitar acceso, usar reembolso parcial.
  - `charge.dispute.created` → **suspende** (reversible). `charge.dispute.closed`: `lost` → revoca; `won`/`warning_closed` → reactiva solo si la suspensión vino de la disputa.
  - Idempotente: deduplicación por `event.id` + revocar una licencia ya revocada no hace nada. Misma verificación de firma que el resto.
  - LemonSqueezy `order_refunded` sigue revocando por email (sin cambios).
- Pagos únicos (Indie/Agency) no emiten `invoice.payment_succeeded` ni `customer.subscription.deleted`.

## Compra de prueba real

Solo cuando 2–6 estén en ✅. Hasta entonces, si alguien compra: el dinero llega, Stripe reintenta el webhook hasta 3 días; despliega la gateway dentro de ese plazo y los eventos se procesarán (o reenvíalos desde Dashboard → Webhooks → Resend).
