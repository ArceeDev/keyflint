"""Automated Daily Growth Engine, Mobile Pulse & Real-Time Lead Alerts.

Provides:
1. Real-time mobile notifications (Email + optional ntfy.sh push) when a user requests a trial,
   purchases a license, or tops up credits.
2. Live 24h & cumulative ecosystem metrics (`collect_pulse_metrics`).
3. Automated daily IndexNow search-engine ping + optional webhook/Dev.to syndication.
4. Daily Mobile Pulse Email to `OPS_ALERT_EMAIL` with live metrics and 1-tap mobile publishing
   intent links (X/Twitter ES & EN, LinkedIn, Reddit) so daily multi-platform distribution takes 1 tap.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
import json
import logging
from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.application.services.growth_posts import DAILY_POST_QUEUE
from app.config import get_settings

logger = logging.getLogger("keyflint.growth")

INDEXNOW_KEY = "8f4e2a9c1b7d3e5f6a0c8b2d4e6f1a3b"

KEYFLINT_ECOSYSTEM_URLS = [
    "https://keyflint.dev/",
    "https://keyflint.dev/feed.xml",
    "https://keyflint.dev/guides/paid-mcp-server.html",
    "https://keyflint.dev/guides/migrate-from-smithery.html",
    "https://keyflint.dev/guides/oauth-mcp-server.html",
    "https://keyflint.dev/guides/mcp-monetization-stripe-x402.html",
]


def _ensure_pulse_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS growth_pulse_log (
            day_utc TEXT PRIMARY KEY,
            sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            details_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )


def get_daily_post(now: Optional[datetime] = None) -> dict[str, Any]:
    """Selects today's rotating post pack and builds 1-tap mobile intent links."""
    now = now or datetime.now(timezone.utc)
    day_index = now.timetuple().tm_yday % len(DAILY_POST_QUEUE)
    item = dict(DAILY_POST_QUEUE[day_index])
    item["day_index"] = day_index + 1
    item["total_in_queue"] = len(DAILY_POST_QUEUE)
    item["x_es_intent"] = f"https://x.com/intent/tweet?text={quote(item['x_es'])}"
    item["x_en_intent"] = f"https://x.com/intent/tweet?text={quote(item['x_en'])}"
    item["linkedin_intent"] = f"https://www.linkedin.com/feed/?shareActive=true&text={quote(item['linkedin_es'])}"
    item["reddit_intent"] = (
        f"https://www.reddit.com/submit?title={quote(item['reddit_title'])}&text={quote(item['reddit_body'])}"
    )
    return item


def collect_pulse_metrics(conn: Any, now: Optional[datetime] = None) -> dict[str, Any]:
    """Queries live 24h and total metrics from the KeyFlint SQLite database."""
    now = now or datetime.now(timezone.utc)
    since_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    customers_total = int(conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0])
    customers_24h = int(
        conn.execute("SELECT COUNT(*) FROM customers WHERE created_at >= ?", (since_24h,)).fetchone()[0]
    )

    tier_rows = conn.execute(
        "SELECT tier, COUNT(*) AS cnt FROM licenses WHERE status = 'active' GROUP BY tier"
    ).fetchall()
    active_by_tier = {str(r["tier"]): int(r["cnt"]) for r in tier_rows}

    lic_24h_rows = conn.execute(
        "SELECT tier, metadata_json FROM licenses WHERE created_at >= ?", (since_24h,)
    ).fetchall()
    trials_24h = 0
    paid_24h = 0
    for r in lic_24h_rows:
        meta = json.loads(r["metadata_json"] or "{}")
        if r["tier"] == "community" or meta.get("trial"):
            trials_24h += 1
        else:
            paid_24h += 1

    usage_24h_row = conn.execute(
        """
        SELECT COUNT(*) AS calls, COALESCE(SUM(CASE WHEN credits_consumed > 0 THEN credits_consumed ELSE 0 END), 0) AS credits
        FROM usage_events
        WHERE timestamp >= ?
        """,
        (since_24h,),
    ).fetchone()
    tool_calls_24h = int(usage_24h_row["calls"] or 0)
    credits_consumed_24h = int(usage_24h_row["credits"] or 0)

    usage_total_row = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(CASE WHEN credits_consumed > 0 THEN credits_consumed ELSE 0 END), 0) AS credits FROM usage_events"
    ).fetchone()
    tool_calls_total = int(usage_total_row["calls"] or 0)
    credits_consumed_total = int(usage_total_row["credits"] or 0)

    top_events_rows = conn.execute(
        """
        SELECT event_type, COUNT(*) AS calls, COALESCE(SUM(credits_consumed), 0) AS credits
        FROM usage_events
        WHERE timestamp >= ?
        GROUP BY event_type
        ORDER BY calls DESC
        LIMIT 8
        """,
        (since_24h,),
    ).fetchall()
    top_events_24h = [
        {"event_type": str(r["event_type"]), "calls": int(r["calls"]), "credits": int(r["credits"])}
        for r in top_events_rows
    ]

    recent_rows = conn.execute(
        """
        SELECT c.email, l.tier, l.status, l.created_at, l.metadata_json,
               COALESCE(q.balance, 0) AS balance, COALESCE(q.consumed, 0) AS consumed
        FROM licenses l
        JOIN customers c ON c.id = l.customer_id
        LEFT JOIN quotas q ON q.license_id = l.id
        ORDER BY l.created_at DESC
        LIMIT 10
        """
    ).fetchall()
    recent_customers = []
    for r in recent_rows:
        meta = json.loads(r["metadata_json"] or "{}")
        recent_customers.append(
            {
                "email": str(r["email"]),
                "tier": str(r["tier"]),
                "status": str(r["status"]),
                "source": meta.get("source") or ("trial" if meta.get("trial") else "direct"),
                "balance": int(r["balance"]),
                "consumed": int(r["consumed"]),
                "created_at": str(r["created_at"]),
            }
        )

    return {
        "generated_at": now.isoformat(),
        "customers_total": customers_total,
        "customers_24h": customers_24h,
        "trials_24h": trials_24h,
        "paid_24h": paid_24h,
        "active_by_tier": active_by_tier,
        "tool_calls_24h": tool_calls_24h,
        "credits_consumed_24h": credits_consumed_24h,
        "tool_calls_total": tool_calls_total,
        "credits_consumed_total": credits_consumed_total,
        "top_events_24h": top_events_24h,
        "recent_customers": recent_customers,
        "daily_post": get_daily_post(now),
    }


def notify_ntfy(title: str, message: str, click_url: str = "https://mcp.keyflint.dev/estado/") -> bool:
    """Sends a lockscreen push via ntfy.sh if NTFY_TOPIC is set.

    ntfy.sh topics are public to anyone who knows the name: never pass personal data (emails, keys) here.
    JSON publish keeps UTF-8 titles intact (HTTP headers are latin-1 only).
    """
    topic = (get_settings().NTFY_TOPIC or "").strip()
    if not topic:
        return False
    try:
        resp = httpx.post(
            "https://ntfy.sh/",
            json={"topic": topic, "title": title[:120], "message": message[:1000], "click": click_url},
            timeout=5.0,
        )
        return resp.status_code < 300
    except Exception as exc:
        logger.warning("ntfy push failed: %s", type(exc).__name__)
        return False


def send_owner_activity_alert(
    email_sender: Any,
    kind: str,
    title: str,
    **details: Any,
) -> bool:
    """Sends an instant mobile alert to OPS_ALERT_EMAIL (and ntfy.sh) on new trial, purchase or top-up."""
    settings = get_settings()
    if not settings.LEAD_ALERT_ENABLED:
        return False
    lines = [f"{k}: {v}" for k, v in details.items() if v is not None]
    text_body = f"{title}\n\n" + "\n".join(lines) + "\n\nEstado en vivo: https://mcp.keyflint.dev/estado/\n"
    # Push sin datos personales: el detalle (correo, sesión) solo va al correo del propietario.
    notify_ntfy(f"[{kind}] KeyFlint", title if "@" not in title else kind)

    to = (settings.OPS_ALERT_EMAIL or "").strip()
    if not to or email_sender is None:
        return False

    esc = html.escape
    rows_html = "".join(
        f'<tr><td style="padding:8px 0;border-bottom:1px solid #1E233D;color:#8E95AF;font-size:13px;">{esc(str(k))}</td>'
        f'<td align="right" style="padding:8px 0;border-bottom:1px solid #1E233D;color:#FFFFFF;font-weight:600;font-size:13px;">{esc(str(v))}</td></tr>'
        for k, v in details.items()
        if v is not None
    )
    html_body = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body bgcolor="#0B0D17" style="margin:0;padding:16px;background:#0B0D17;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;color:#FFFFFF;">
  <div style="max-width:520px;margin:0 auto;background:#111424;border:1px solid #1E233D;border-radius:12px;padding:24px;">
    <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#CCFF00;margin-bottom:6px;">KeyFlint · {esc(kind)}</div>
    <h1 style="margin:0 0 16px 0;font-size:20px;color:#FFFFFF;line-height:1.3;">{esc(title)}</h1>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:20px;">{rows_html}</table>
    <a href="https://mcp.keyflint.dev/estado/" style="display:block;text-align:center;background:#CCFF00;color:#0B0D17;font-weight:700;font-size:14px;text-decoration:none;padding:12px 16px;border-radius:8px;">Ver estado del ecosistema</a>
  </div>
</body></html>"""
    try:
        return bool(
            email_sender._dispatch(
                recipient=to,
                subject=f"[KeyFlint {kind}] {title}",
                text_body=text_body,
                html_body=html_body,
            )
        )
    except Exception as exc:
        logger.warning("Owner activity alert failed: %s", exc)
        return False


def ping_indexnow() -> dict[str, Any]:
    """Submits keyflint.dev URLs to IndexNow so Bing, ChatGPT Search, and DuckDuckGo index updates daily."""
    payload = {
        "host": "keyflint.dev",
        "key": INDEXNOW_KEY,
        "keyLocation": f"https://keyflint.dev/{INDEXNOW_KEY}.txt",
        "urlList": KEYFLINT_ECOSYSTEM_URLS,
    }
    try:
        resp = httpx.post(
            "https://api.indexnow.org/indexnow",
            json=payload,
            timeout=8.0,
        )
        return {"ok": resp.status_code in (200, 202), "status_code": resp.status_code}
    except Exception as exc:
        logger.warning("IndexNow ping failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def syndicate_external(pulse: dict[str, Any]) -> dict[str, Any]:
    """Dispatches today's post to optional connected webhooks (Make/Zapier/n8n/Discord)."""
    settings = get_settings()
    out: dict[str, Any] = {"webhook": False}
    webhook_url = (settings.SOCIAL_WEBHOOK_URL or "").strip()
    if webhook_url:
        try:
            resp = httpx.post(
                webhook_url,
                json={
                    "source": "keyflint-daily-growth",
                    "generated_at": pulse["generated_at"],
                    "metrics_24h": {
                        "trials_24h": pulse["trials_24h"],
                        "paid_24h": pulse["paid_24h"],
                        "tool_calls_24h": pulse["tool_calls_24h"],
                        "credits_consumed_24h": pulse["credits_consumed_24h"],
                    },
                    "post": pulse["daily_post"],
                },
                timeout=8.0,
            )
            out["webhook"] = resp.status_code < 300
        except Exception as exc:
            logger.warning("Social webhook syndication failed: %s", exc)
    return out


def render_daily_pulse_email(pulse: dict[str, Any]) -> tuple[str, str, str]:
    """Returns (subject, text_body, html_body) for the Daily Mobile Pulse & 1-Tap Social Pack."""
    post = pulse["daily_post"]
    t24 = pulse["trials_24h"]
    p24 = pulse["paid_24h"]
    c24 = pulse["tool_calls_24h"]
    cr24 = pulse["credits_consumed_24h"]

    subject = (
        f"[KeyFlint Pulso] +{t24} solicitudes · {c24} llamadas (24h) · Post #{post['day_index']}: {post['topic'][:38]}"
    )

    recent_lines = [
        f"- {c['email']} ({c['tier']} · {c['source']} · {c['consumed']} cr usados / {c['balance']} disp.)"
        for c in pulse["recent_customers"][:6]
    ] or ["- Sin registros recientes"]

    text_body = (
        f"PULSO DIARIO KEYFLINT & FLINT (24h)\n"
        f"==================================\n"
        f"Nuevas solicitudes prueba (24h): {t24}\n"
        f"Nuevas compras/planes (24h): {p24}\n"
        f"Llamadas a herramientas (24h): {c24} ({cr24} créditos)\n"
        f"Clientes totales acumulados: {pulse['customers_total']}\n"
        f"Llamadas totales acumuladas: {pulse['tool_calls_total']} ({pulse['credits_consumed_total']} créditos)\n\n"
        f"ÚLTIMOS USUARIOS:\n" + "\n".join(recent_lines) + "\n\n"
        f"PUBLICACIÓN DEL DÍA (#{post['day_index']} - {post['topic']})\n"
        f"----------------------------------\n"
        f"Publicar en X (ES) en 1 toque:\n{post['x_es_intent']}\n\n"
        f"Publicar en X (EN) en 1 toque:\n{post['x_en_intent']}\n\n"
        f"Publicar en LinkedIn en 1 toque:\n{post['linkedin_intent']}\n\n"
        f"Publicar en Reddit en 1 toque:\n{post['reddit_intent']}\n"
    )

    esc = html.escape
    recent_rows_html = "".join(
        f'<tr>'
        f'<td style="padding:8px 0;border-bottom:1px solid #1E233D;color:#FFFFFF;font-size:12px;">{esc(c["email"])}</td>'
        f'<td style="padding:8px 4px;border-bottom:1px solid #1E233D;color:#CCFF00;font-size:11px;font-family:monospace;">{esc(c["tier"])}</td>'
        f'<td align="right" style="padding:8px 0;border-bottom:1px solid #1E233D;color:#8E95AF;font-size:12px;">{c["consumed"]} us. / {c["balance"]} disp.</td>'
        f'</tr>'
        for c in pulse["recent_customers"][:6]
    ) or '<tr><td colspan="3" style="padding:8px 0;color:#8E95AF;font-size:12px;">Sin actividad registrada</td></tr>'

    html_body = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="dark only">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(subject)}</title>
</head>
<body bgcolor="#0B0D17" style="margin:0;padding:16px 8px;background-color:#0B0D17;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Roboto,sans-serif;color:#FFFFFF;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:580px;margin:0 auto;background-color:#111424;border:1px solid #1E233D;border-radius:14px;">
    <tr>
      <td style="padding:28px 20px;">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#CCFF00;margin-bottom:6px;">KeyFlint &amp; Flint · Pulso Móvil Diario</div>
        <h1 style="margin:0 0 18px 0;font-size:22px;font-weight:700;color:#FFFFFF;line-height:1.25;">Solicitudes, uso en vivo y <span style="color:#CCFF00;">publicación en 1 toque</span></h1>

        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#171B30;border:1px solid #282F50;border-radius:10px;padding:14px;margin-bottom:20px;">
          <tr>
            <td width="50%" style="padding:6px 8px;border-right:1px solid #232944;border-bottom:1px solid #232944;">
              <div style="font-size:11px;color:#8E95AF;">Solicitudes prueba (24h)</div>
              <div style="font-size:22px;font-weight:800;color:#CCFF00;margin-top:2px;">+{t24}</div>
            </td>
            <td width="50%" style="padding:6px 12px;border-bottom:1px solid #232944;">
              <div style="font-size:11px;color:#8E95AF;">Llamadas MCP / Web (24h)</div>
              <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-top:2px;">{c24} <span style="font-size:12px;color:#8E95AF;font-weight:500;">({cr24} cr)</span></div>
            </td>
          </tr>
          <tr>
            <td width="50%" style="padding:10px 8px 4px 8px;border-right:1px solid #232944;">
              <div style="font-size:11px;color:#8E95AF;">Clientes acumulados</div>
              <div style="font-size:18px;font-weight:700;color:#FFFFFF;margin-top:2px;">{pulse['customers_total']} <span style="font-size:11px;color:#CCFF00;">(+{p24} pagos 24h)</span></div>
            </td>
            <td width="50%" style="padding:10px 12px 4px 12px;">
              <div style="font-size:11px;color:#8E95AF;">Uso total acumulado</div>
              <div style="font-size:18px;font-weight:700;color:#FFFFFF;margin-top:2px;">{pulse['tool_calls_total']} <span style="font-size:12px;color:#8E95AF;font-weight:500;">({pulse['credits_consumed_total']} cr)</span></div>
            </td>
          </tr>
        </table>

        <div style="font-size:12px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;color:#8E95AF;margin-bottom:8px;">Últimas solicitudes y licencias</div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:24px;">
          {recent_rows_html}
        </table>

        <div style="background:#171B30;border:1px solid #282F50;border-radius:10px;padding:18px;margin-bottom:20px;">
          <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#CCFF00;margin-bottom:4px;">Publicación del día #{post['day_index']} de {post['total_in_queue']}</div>
          <div style="font-size:16px;font-weight:700;color:#FFFFFF;margin-bottom:12px;">{esc(post['topic'])}</div>

          <div style="font-size:11px;color:#8E95AF;margin-bottom:4px;">Texto listo para X / Redes (Español):</div>
          <pre style="margin:0 0 12px 0;padding:10px;background:#0B0D17;border:1px solid #1E233D;border-radius:6px;color:#E6E8EF;font-size:12px;white-space:pre-wrap;font-family:ui-monospace,monospace;">{esc(post['x_es'])}</pre>

          <div style="font-size:11px;color:#8E95AF;margin-bottom:4px;">Texto listo para X / HN / Dev (English):</div>
          <pre style="margin:0 0 16px 0;padding:10px;background:#0B0D17;border:1px solid #1E233D;border-radius:6px;color:#E6E8EF;font-size:12px;white-space:pre-wrap;font-family:ui-monospace,monospace;">{esc(post['x_en'])}</pre>

          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td style="padding-bottom:8px;">
                <a href="{esc(post['x_es_intent'], quote=True)}" style="display:block;text-align:center;background:#CCFF00;color:#0B0D17;font-size:13px;font-weight:700;text-decoration:none;padding:11px 14px;border-radius:8px;">Publicar en X (Español) en 1 toque</a>
              </td>
            </tr>
            <tr>
              <td style="padding-bottom:8px;">
                <a href="{esc(post['x_en_intent'], quote=True)}" style="display:block;text-align:center;background:#0B0D17;color:#CCFF00;border:1px solid #CCFF00;font-size:13px;font-weight:700;text-decoration:none;padding:11px 14px;border-radius:8px;">Post on X (English) in 1 tap</a>
              </td>
            </tr>
            <tr>
              <td style="padding-bottom:8px;">
                <a href="{esc(post['linkedin_intent'], quote=True)}" style="display:block;text-align:center;background:#0B0D17;color:#FFFFFF;border:1px solid #282F50;font-size:13px;font-weight:600;text-decoration:none;padding:10px 14px;border-radius:8px;">Publicar en LinkedIn en 1 toque</a>
              </td>
            </tr>
            <tr>
              <td>
                <a href="{esc(post['reddit_intent'], quote=True)}" style="display:block;text-align:center;background:#0B0D17;color:#FFFFFF;border:1px solid #282F50;font-size:13px;font-weight:600;text-decoration:none;padding:10px 14px;border-radius:8px;">Publicar en Reddit en 1 toque</a>
              </td>
            </tr>
          </table>
        </div>

        <div style="text-align:center;font-size:12px;color:#8E95AF;">
          <a href="https://mcp.keyflint.dev/estado/" style="color:#CCFF00;text-decoration:none;font-weight:600;">Estado MCP Hub</a> &nbsp;·&nbsp;
          <a href="https://keyflint.dev/" style="color:#CCFF00;text-decoration:none;font-weight:600;">KeyFlint.dev</a>
        </div>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return subject, text_body, html_body


def run_daily_growth(
    conn: Any,
    email_sender: Any,
    *,
    force: bool = False,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Executes the daily growth cycle (metrics + IndexNow + syndication + mobile pulse email)."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    if not force:
        if not settings.DAILY_PULSE_ENABLED:
            return {"status": "disabled"}
        if now.hour < settings.DAILY_PULSE_HOUR_UTC:
            return {"status": "waiting_for_hour", "target_hour_utc": settings.DAILY_PULSE_HOUR_UTC}

    _ensure_pulse_table(conn)
    day_utc = now.strftime("%Y-%m-%d")
    if not force:
        existing = conn.execute("SELECT 1 FROM growth_pulse_log WHERE day_utc = ?", (day_utc,)).fetchone()
        if existing is not None:
            return {"status": "already_sent_today", "day_utc": day_utc}

    pulse = collect_pulse_metrics(conn, now=now)
    indexnow_res = ping_indexnow()
    syndication_res = syndicate_external(pulse)

    email_sent = False
    to = (settings.OPS_ALERT_EMAIL or "").strip()
    if to and email_sender is not None:
        subject, text_body, html_body = render_daily_pulse_email(pulse)
        try:
            email_sent = bool(
                email_sender._dispatch(
                    recipient=to,
                    subject=subject,
                    text_body=text_body,
                    html_body=html_body,
                )
            )
        except Exception as exc:
            logger.error("Daily pulse email failed: %s", exc)

    notify_ntfy(
        f"Pulso KeyFlint: +{pulse['trials_24h']} pruebas, {pulse['tool_calls_24h']} llamadas",
        f"Post de hoy listo en tu correo: {pulse['daily_post']['topic']}",
    )

    summary = {
        "status": "sent" if email_sent else "completed_no_email",
        "day_utc": day_utc,
        "email_sent": email_sent,
        "indexnow": indexnow_res,
        "syndication": syndication_res,
        "metrics_24h": {
            "customers_24h": pulse["customers_24h"],
            "trials_24h": pulse["trials_24h"],
            "paid_24h": pulse["paid_24h"],
            "tool_calls_24h": pulse["tool_calls_24h"],
            "credits_consumed_24h": pulse["credits_consumed_24h"],
        },
        "daily_post_topic": pulse["daily_post"]["topic"],
    }

    conn.execute(
        "INSERT OR REPLACE INTO growth_pulse_log (day_utc, sent_at, details_json) VALUES (?, ?, ?)",
        (day_utc, now.isoformat(), json.dumps(summary)),
    )
    conn.commit()
    return summary
