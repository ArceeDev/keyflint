"""Infrastructure adapter for transactional email dispatching via Resend or SMTP."""

from __future__ import annotations

import html

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import smtplib
import time
from typing import Optional

import httpx

from app.config import get_settings
from app.domain.interfaces.email_sender import IEmailSender, LicenseEmailPayload

logger = logging.getLogger("keyflint.email")

_DOCS_URL = "https://github.com/ArceeDev/keyflint#client-sdks"
_BRAND_LOGO_URL = "https://mcp.keyflint.dev/assets/flint-brand.png"
_RESEND_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RESEND_HINTS = {
    401: "RESEND_API_KEY is invalid or revoked.",
    403: "Sender domain not verified in Resend (check SPF/DKIM DNS records) or EMAIL_FROM uses another domain.",
    422: "Resend rejected the payload (check EMAIL_FROM format and recipient).",
}


class TransactionalEmailService(IEmailSender):
    """Dispatches license tokens and quota alerts via Resend API or SMTP."""

    def __init__(
        self,
        resend_api_key: Optional[str] = None,
        smtp_host: Optional[str] = None,
        smtp_port: int = 587,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        from_address: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        settings = get_settings()
        self._resend_api_key = resend_api_key or settings.RESEND_API_KEY
        self._smtp_host = smtp_host or settings.SMTP_HOST
        self._smtp_port = smtp_port or settings.SMTP_PORT
        self._smtp_username = smtp_username or settings.SMTP_USERNAME
        self._smtp_password = smtp_password or settings.SMTP_PASSWORD
        self._from_address = from_address or settings.EMAIL_FROM
        self._enabled = enabled if enabled is not None else (
            settings.EMAIL_ENABLED or bool(self._resend_api_key or self._smtp_host)
        )
        self.last_error: Optional[str] = None

    @property
    def provider(self) -> str:
        """Active provider: 'resend', 'smtp' or 'none' (nothing will be delivered)."""
        if not self._enabled:
            return "none"
        if self._resend_api_key:
            return "resend"
        if self._smtp_host:
            return "smtp"
        return "none"

    def send_license_issued(self, payload: LicenseEmailPayload) -> bool:
        """Dispatches license activation email with signed Ed25519 token."""
        subject = f"Your KeyFlint {payload.tier.capitalize()} license"
        text_body = self._render_license_text(payload)
        html_body = self._render_license_html(payload)

        return self._dispatch(
            recipient=payload.recipient_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

    def send_quota_replenished(
        self,
        recipient_email: str,
        license_key: str,
        added_credits: int,
        new_balance: int,
    ) -> bool:
        """Dispatches quota cycle replenishment notification."""
        subject = f"KeyFlint: +{added_credits:,} créditos sumados a tu licencia"
        short = f"{license_key[:12]}..."
        text_body = (
            f"Hola,\n\n"
            f"Se han añadido +{added_credits:,} créditos a tu licencia de Flint ({short}).\n"
            f"Saldo disponible: {new_balance:,} créditos.\n\n"
            f"Consultar mi saldo: https://mcp.keyflint.dev/saldo/\n\n"
            f"Dudas o soporte: support@keyflint.dev\n"
        )
        html_body = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><meta name="color-scheme" content="light"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Saldo actualizado · Flint</title></head>
<body style="margin: 0; padding: 40px 16px; background-color: #F7F8FA; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, Helvetica, Arial, sans-serif; color: #0B0D17; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #F7F8FA;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 580px; background-color: #FFFFFF; border: 1px solid #E3E6EE; border-radius: 14px; box-shadow: 0 4px 24px rgba(11, 13, 23, 0.05);" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding: 40px 36px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 28px;">
                <tr>
                  <td align="left" style="vertical-align: middle;">
                    <a href="https://mcp.keyflint.dev" target="_blank" style="text-decoration: none; display: inline-block;">
                      <img src="{_BRAND_LOGO_URL}" alt="Flint by KeyFlint" width="132" height="auto" style="display: block; border: 0; outline: none; text-decoration: none; max-width: 132px; height: auto;" />
                    </a>
                  </td>
                  <td align="right" style="vertical-align: middle;">
                    <span style="display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; background-color: #CCFF00; color: #0B0D17; padding: 4px 9px; border-radius: 5px;">Recarga Confirmada</span>
                  </td>
                </tr>
              </table>
              <h1 style="margin: 0 0 12px 0; font-size: 22px; font-weight: 700; color: #0B0D17; letter-spacing: -0.02em; line-height: 1.25;">Saldo de créditos <span style="color: #0B0D17; border-bottom: 3px solid #CCFF00;">actualizado</span></h1>
              <p style="margin: 0 0 24px 0; font-size: 15px; color: #5E6579; line-height: 1.6;">Tus servidores deterministas de Flint ya tienen listos los nuevos créditos para seguir procesando tus extractos bancarios y facturación sin interrupciones.</p>
              
              <div style="background-color: #F7F8FA; border: 1px solid #E3E6EE; border-radius: 10px; padding: 22px 24px; margin-bottom: 24px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td style="padding-bottom: 12px; border-bottom: 1px solid #E3E6EE; color: #5E6579; font-size: 14px;">Créditos añadidos</td>
                    <td align="right" style="padding-bottom: 12px; border-bottom: 1px solid #E3E6EE; color: #0B0D17; font-weight: 700; font-size: 16px;">+{added_credits:,}</td>
                  </tr>
                  <tr>
                    <td style="padding-top: 14px; color: #5E6579; font-size: 14px;">Saldo disponible</td>
                    <td align="right" style="padding-top: 14px; color: #0B0D17; font-weight: 800; font-size: 20px;">
                      {new_balance:,} <span style="font-size: 14px; font-weight: 600; color: #5E6579;">créditos</span>
                    </td>
                  </tr>
                </table>
              </div>

              <div style="background-color: #FAFAFC; border-left: 3px solid #CCFF00; padding: 14px 18px; border-radius: 0 8px 8px 0; margin-bottom: 26px;">
                <p style="margin: 0; font-size: 13px; color: #2A3042; line-height: 1.55;">
                  <strong>Incentivo Flint:</strong> Consulta tu consumo detallado en vivo o automatiza la reconciliación procesando lotes de extractos bancarios en la nube con descarga inmediata en CSV y JSON.
                </p>
              </div>

              <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 24px;">
                <tr>
                  <td>
                    <a href="https://mcp.keyflint.dev/saldo/" style="display: inline-block; background-color: #0B0D17; color: #CCFF00; font-size: 14px; font-weight: 700; text-decoration: none; padding: 13px 24px; border-radius: 8px; letter-spacing: -0.01em;">Ver mi saldo en vivo &rarr;</a>
                  </td>
                  <td style="padding-left: 14px;">
                    <a href="https://mcp.keyflint.dev/lote/" style="display: inline-block; background-color: #CCFF00; color: #0B0D17; font-size: 14px; font-weight: 700; text-decoration: none; padding: 13px 20px; border-radius: 8px; letter-spacing: -0.01em;">Procesar en /lote/</a>
                  </td>
                </tr>
              </table>

              <p style="margin: 0 0 24px 0; font-size: 12px; color: #717791;">Licencia vinculada: <code style="font-family: ui-monospace, Menlo, Consolas, monospace; color: #0B0D17; background: #F2F4F8; padding: 3px 6px; border-radius: 4px; border: 1px solid #E3E6EE;">{html.escape(short)}</code></p>

              <div style="padding-top: 20px; border-top: 1px solid #E3E6EE; font-size: 12px; color: #717791; line-height: 1.6;">
                <p style="margin: 0 0 4px 0;"><strong>Flint by KeyFlint</strong> · Herramientas deterministas para IA</p>
                <p style="margin: 0;">Soporte humano: <a href="mailto:support@keyflint.dev" style="color: #0B0D17; text-decoration: underline; font-weight: 600;">support@keyflint.dev</a></p>
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
        return self._dispatch(
            recipient=recipient_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

    def send_credits_depleted(self, recipient_email: str, license_key: str, *, trial: bool, topup_url: str,
                              topup_eur: int, topup_credits: int) -> bool:
        """Retention email when an MCP license runs out of credits (ES first, short EN line)."""
        short = f"{license_key[:12]}..."
        if trial:
            subject = "Has usado tus 25 créditos de prueba de Flint"
            lead = "Has gastado los 25 créditos de la prueba gratuita."
            lead_en = "You've used the 25 free trial credits."
        else:
            subject = "Te has quedado sin créditos en Flint"
            lead = "Tu licencia se ha quedado sin créditos."
            lead_en = "Your license is out of credits."
        offer = (f"Recarga desde {topup_eur} € y suma {topup_credits:,} créditos a la misma licencia: "
                 "no tienes que tocar tu configuración.").replace(",", ".")
        offer_en = f"Top up from {topup_eur} EUR for {topup_credits:,} credits on the same key. No config changes."
        text_body = (
            f"Hola,\n\n{lead} ¿Te ha ahorrado tiempo?\n{offer}\n\n"
            f"Recargar ahora (1 clic): {topup_url}\n\n"
            f"Licencia: {short}\nDudas: support@keyflint.dev\n\n"
            f"--\n{lead_en} {offer_en}\nTop up: {topup_url}\n"
        )
        u = html.escape(topup_url, quote=True)
        html_body = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><meta name="color-scheme" content="light"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Créditos agotados · Flint</title></head>
<body style="margin: 0; padding: 40px 16px; background-color: #F7F8FA; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, Helvetica, Arial, sans-serif; color: #0B0D17; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #F7F8FA;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 580px; background-color: #FFFFFF; border: 1px solid #E3E6EE; border-radius: 14px; box-shadow: 0 4px 24px rgba(11, 13, 23, 0.05);" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding: 40px 36px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 28px;">
                <tr>
                  <td align="left" style="vertical-align: middle;">
                    <a href="https://mcp.keyflint.dev" target="_blank" style="text-decoration: none; display: inline-block;">
                      <img src="{_BRAND_LOGO_URL}" alt="Flint by KeyFlint" width="132" height="auto" style="display: block; border: 0; outline: none; text-decoration: none; max-width: 132px; height: auto;" />
                    </a>
                  </td>
                  <td align="right" style="vertical-align: middle;">
                    <span style="display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; background-color: #CCFF00; color: #0B0D17; padding: 4px 9px; border-radius: 5px;">Recarga Rápida</span>
                  </td>
                </tr>
              </table>
              <h1 style="margin: 0 0 12px 0; font-size: 22px; font-weight: 700; color: #0B0D17; letter-spacing: -0.02em; line-height: 1.25;">Has completado tus <span style="color: #0B0D17; border-bottom: 3px solid #CCFF00;">créditos de prueba</span></h1>
              <p style="margin: 0 0 16px 0; font-size: 15px; color: #5E6579; line-height: 1.6;">Esperamos que Flint te haya ahorrado tiempo automatizando tus extractos bancarios, facturas o datos contables.</p>
              <p style="margin: 0 0 24px 0; font-size: 14px; color: #2A3042; line-height: 1.55;">Tu configuración y tu licencia siguen listas: <strong>no tienes que volver a instalar nada ni cambiar de clave</strong> en Claude Desktop, Cursor ni en el navegador.</p>

              <div style="background-color: #F7F8FA; border: 1px solid #E3E6EE; border-radius: 10px; padding: 22px 24px; margin-bottom: 26px;">
                <div style="font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #5E6579; margin-bottom: 8px;">Recarga recomendada</div>
                <div style="font-size: 20px; font-weight: 800; color: #0B0D17; margin-bottom: 4px;">{topup_eur} € &rarr; <span style="background-color: #CCFF00; color: #0B0D17; padding: 2px 8px; border-radius: 5px;">{topup_credits:,} créditos</span></div>
                <div style="font-size: 12px; color: #7B829E;">Sin caducidad · IVA incluido · Pago seguro con Stripe</div>
              </div>

              <p style="margin: 0 0 24px 0;">
                <a href="{u}" style="display: inline-block; background-color: #0B0D17; color: #CCFF00; font-size: 15px; font-weight: 700; text-decoration: none; padding: 14px 28px; border-radius: 8px; letter-spacing: -0.01em;">Recargar {topup_eur} € en 1 clic &rarr;</a>
              </p>

              <p style="margin: 0 0 20px 0; font-size: 12px; color: #717791;">Licencia vinculada: <code style="font-family: ui-monospace, Menlo, Consolas, monospace; color: #0B0D17; background: #F2F4F8; padding: 3px 6px; border-radius: 4px; border: 1px solid #E3E6EE;">{html.escape(short)}</code></p>

              <p style="margin: 0 0 24px 0; padding-top: 16px; border-top: 1px solid #E3E6EE; font-size: 12px; color: #717791; line-height: 1.5;">{html.escape(lead_en)} {html.escape(offer_en)} <a href="{u}" style="color: #0B0D17; text-decoration: underline; font-weight: 700;">Top up &rarr;</a></p>

              <div style="padding-top: 20px; border-top: 1px solid #E3E6EE; font-size: 12px; color: #717791; line-height: 1.6;">
                <p style="margin: 0 0 4px 0;"><strong>Flint by KeyFlint</strong> · Herramientas deterministas para IA</p>
                <p style="margin: 0;">¿Dudas con tu configuración? Escríbenos a <a href="mailto:support@keyflint.dev" style="color: #0B0D17; text-decoration: underline; font-weight: 600;">support@keyflint.dev</a></p>
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
        return self._dispatch(recipient=recipient_email, subject=subject, text_body=text_body, html_body=html_body)

    def send_ops_alert(self, recipient_email: str, subject: str, text_body: str) -> bool:
        """Plain-text operator alert (billing incidents). Never raises."""
        safe = html.escape(text_body)
        return self._dispatch(
            recipient=recipient_email,
            subject=f"[KeyFlint alert] {subject}",
            text_body=text_body,
            html_body=f"<pre style=\"font-family:monospace;white-space:pre-wrap\">{safe}</pre>",
        )

    def send_portal_magic_link(self, recipient_email: str, link: str, ttl_minutes: int) -> bool:
        """Single-use sign-in link for the customer portal. Never raises."""
        safe_link = html.escape(link, quote=True)
        text_body = (
            "Hola,\n\n"
            "Alguien (probablemente tú) ha pedido ver sus licencias de KeyFlint.\n"
            f"Abre este enlace para entrar al portal. Caduca en {ttl_minutes} minutos y solo funciona una vez:\n\n"
            f"{link}\n\n"
            "Si no lo has pedido tú, ignora este correo: nadie puede ver tus licencias sin este enlace.\n\n"
            "KeyFlint · support@keyflint.dev"
        )
        html_body = f"""<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><meta name="color-scheme" content="light"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Tu portal de Flint</title></head>
<body style="margin: 0; padding: 40px 16px; background-color: #F7F8FA; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, Helvetica, Arial, sans-serif; color: #0B0D17; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #F7F8FA;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 580px; background-color: #FFFFFF; border: 1px solid #E3E6EE; border-radius: 14px; box-shadow: 0 4px 24px rgba(11, 13, 23, 0.05);" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding: 40px 36px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 28px;">
                <tr>
                  <td align="left">
                    <a href="https://mcp.keyflint.dev" target="_blank" style="text-decoration: none; display: inline-block;">
                      <img src="{_BRAND_LOGO_URL}" alt="Flint by KeyFlint" width="132" height="auto" style="display: block; border: 0; outline: none; text-decoration: none; max-width: 132px; height: auto;" />
                    </a>
                  </td>
                </tr>
              </table>
              <h1 style="margin: 0 0 12px 0; font-size: 22px; font-weight: 700; color: #0B0D17; letter-spacing: -0.02em; line-height: 1.25;">Acceso al portal de licencias</h1>
              <p style="margin: 0 0 16px 0; font-size: 15px; color: #5E6579; line-height: 1.6;">Alguien (probablemente tú) ha solicitado consultar sus licencias y saldo en Flint.</p>
              <p style="margin: 0 0 24px 0; font-size: 14px; color: #717791; line-height: 1.5;">Este enlace caduca en {ttl_minutes} minutos y solo funciona una vez para tu seguridad.</p>
              <p style="margin: 0 0 24px 0;">
                <a href="{safe_link}" style="display: inline-block; background-color: #0B0D17; color: #CCFF00; font-size: 14px; font-weight: 700; text-decoration: none; padding: 13px 26px; border-radius: 8px; letter-spacing: -0.01em;">Abrir mi portal &rarr;</a>
              </p>
              <p style="font-size: 13px; color: #717791; margin: 0 0 20px 0;">Si no lo has pedido tú, ignora este correo: nadie puede ver tus licencias sin este enlace.</p>
              <div style="padding-top: 20px; border-top: 1px solid #E3E6EE; font-size: 12px; color: #717791;">
                Flint by KeyFlint · <a href="mailto:support@keyflint.dev" style="color: #0B0D17; text-decoration: underline;">support@keyflint.dev</a>
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body></html>"""
        return self._dispatch(
            recipient=recipient_email,
            subject="Tu enlace de acceso al portal de KeyFlint",
            text_body=text_body,
            html_body=html_body,
        )

    def _dispatch(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: str,
    ) -> bool:
        """Transmits email. Returns False (never fakes success) when unconfigured or failing."""
        self.last_error = None
        provider = self.provider
        if provider == "resend":
            return self._send_via_resend(recipient, subject, text_body, html_body)
        if provider == "smtp":
            return self._send_via_smtp(recipient, subject, text_body, html_body)

        self.last_error = "no_email_provider_configured"
        logger.warning(
            "EMAIL NOT SENT: no provider configured (set RESEND_API_KEY or SMTP_HOST). "
            "Recipient: %s, Subject: '%s'",
            recipient,
            subject,
        )
        return False

    def _send_via_resend(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: str,
    ) -> bool:
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.post(
                        "https://api.resend.com/emails",
                        headers={
                            "Authorization": f"Bearer {self._resend_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "from": self._from_address,
                            "to": [recipient],
                            "subject": subject,
                            "text": text_body,
                            "html": html_body,
                        },
                    )
            except Exception as exc:
                self.last_error = f"resend_exception: {exc}"
                logger.error("Resend dispatch exception for %s (attempt %d/%d): %s", recipient, attempt, attempts, exc)
            else:
                if resp.status_code in (200, 201):
                    logger.info("Resend dispatch succeeded for %s", recipient)
                    return True
                self.last_error = f"resend_{resp.status_code}: {resp.text[:300]}"
                logger.error(
                    "Resend API error %s for %s (attempt %d/%d): %s%s",
                    resp.status_code,
                    recipient,
                    attempt,
                    attempts,
                    resp.text[:300],
                    f" | hint: {_RESEND_HINTS[resp.status_code]}" if resp.status_code in _RESEND_HINTS else "",
                )
                if resp.status_code not in _RESEND_RETRY_STATUSES:
                    return False
            if attempt < attempts:
                time.sleep(0.5 * attempt)
        return False

    def _send_via_smtp(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: str,
    ) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._from_address
            msg["To"] = recipient

            part1 = MIMEText(text_body, "plain", "utf-8")
            part2 = MIMEText(html_body, "html", "utf-8")
            msg.attach(part1)
            msg.attach(part2)

            with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10.0) as server:
                server.starttls()
                if self._smtp_username and self._smtp_password:
                    server.login(self._smtp_username, self._smtp_password)
                server.sendmail(self._from_address, [recipient], msg.as_string())

            logger.info("SMTP dispatch succeeded for %s", recipient)
            return True
        except Exception as exc:
            self.last_error = f"smtp_exception: {exc}"
            logger.error("SMTP dispatch exception for %s: %s", recipient, exc)
            return False

    # Plain and short on purpose: iCloud Mail silently drops mail that looks like credential
    # phishing (repeated opaque tokens, code blocks), even when Resend reports "delivered".
    def _render_license_text(self, p: LicenseEmailPayload) -> str:
        return f"""Your KeyFlint {p.tier.capitalize()} license is active.

License key:
{p.license_key}

Tier: {p.tier.capitalize()}
Seats: {p.seats}
Included credits: {p.credits:,}
Expires: {(p.expires_at or '')[:10] or 'Never (perpetual)'}
Gateway public key: {p.public_key_hex}

Setup guide (Python, JS, Go): {_DOCS_URL}

Questions? Reply to this email or write to support@keyflint.dev.
"""

    def _render_license_html(self, p: LicenseEmailPayload) -> str:
        cell = "padding: 10px 0; color: #5E6579; border-bottom: 1px solid #E3E6EE; font-size: 14px;"
        val_cell = "padding: 10px 0; color: #0B0D17; border-bottom: 1px solid #E3E6EE; font-size: 14px; font-weight: 600;"
        rows = "".join(
            f'<tr><td style="{cell}">{label}</td><td align="right" style="{val_cell}">{value}</td></tr>'
            for label, value in (
                ("Plan", p.tier.capitalize()),
                ("Equipos permitidos", p.seats),
                ("Créditos incluidos", f"{p.credits:,}"),
                ("Validez", (p.expires_at or "")[:10] or "Permanente (sin caducidad)"),
            )
        )
        return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><meta name="color-scheme" content="light"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Tu licencia de Flint</title></head>
<body style="margin: 0; padding: 40px 16px; background-color: #F7F8FA; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, Helvetica, Arial, sans-serif; color: #0B0D17; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #F7F8FA;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 580px; background-color: #FFFFFF; border: 1px solid #E3E6EE; border-radius: 14px; box-shadow: 0 4px 24px rgba(11, 13, 23, 0.05);" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding: 40px 36px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 28px;">
                <tr>
                  <td align="left" style="vertical-align: middle;">
                    <a href="https://mcp.keyflint.dev" target="_blank" style="text-decoration: none; display: inline-block;">
                      <img src="{_BRAND_LOGO_URL}" alt="Flint by KeyFlint" width="132" height="auto" style="display: block; border: 0; outline: none; text-decoration: none; max-width: 132px; height: auto;" />
                    </a>
                  </td>
                  <td align="right" style="vertical-align: middle;">
                    <span style="display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; background-color: #CCFF00; color: #0B0D17; padding: 4px 9px; border-radius: 5px;">Licencia Activa</span>
                  </td>
                </tr>
              </table>
              <h1 style="margin: 0 0 12px 0; font-size: 22px; font-weight: 700; color: #0B0D17; letter-spacing: -0.02em; line-height: 1.25;">Tu licencia <span style="color: #0B0D17; border-bottom: 3px solid #CCFF00;">{p.tier.capitalize()}</span> está lista</h1>
              <p style="margin: 0 0 20px 0; font-size: 15px; color: #5E6579; line-height: 1.6;">Ya tienes acceso completo a las herramientas deterministas de Flint para automatizar extractos bancarios y facturación en Claude Desktop, Cursor, VS Code o terminal.</p>
              
              <div style="background-color: #0B0D17; border: 1px solid #1E233D; border-radius: 10px; padding: 18px 20px; margin-bottom: 24px;">
                <div style="font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #8E95AF; margin-bottom: 8px;">Clave de licencia</div>
                <div style="font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; color: #CCFF00; word-break: break-all; line-height: 1.5; background: #111424; padding: 10px 12px; border-radius: 6px; border: 1px solid #1E233D;">{p.license_key}</div>
              </div>

              <div style="background-color: #F7F8FA; border: 1px solid #E3E6EE; border-radius: 10px; padding: 14px 20px; margin-bottom: 24px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>
              </div>

              <div style="background-color: #FAFAFC; border-left: 3px solid #CCFF00; padding: 14px 18px; border-radius: 0 8px 8px 0; margin-bottom: 26px;">
                <p style="margin: 0; font-size: 13px; color: #2A3042; line-height: 1.55;">
                  <strong>¿Cómo empezar ahora?</strong> Sigue la guía de configuración en 2 minutos para tu cliente de IA preferido o procesa directamente ficheros bancarios Norma 43 (.n43, .c43) desde el navegador en nuestro procesador por lotes.
                </p>
              </div>

              <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 28px;">
                <tr>
                  <td>
                    <a href="{_DOCS_URL}" style="display: inline-block; background-color: #0B0D17; color: #CCFF00; font-size: 14px; font-weight: 700; text-decoration: none; padding: 13px 24px; border-radius: 8px; letter-spacing: -0.01em;">Guía de instalación rápida &rarr;</a>
                  </td>
                  <td style="padding-left: 14px;">
                    <a href="https://mcp.keyflint.dev/lote/" style="display: inline-block; background-color: #CCFF00; color: #0B0D17; font-size: 14px; font-weight: 700; text-decoration: none; padding: 13px 20px; border-radius: 8px; letter-spacing: -0.01em;">Procesar en /lote/</a>
                  </td>
                </tr>
              </table>

              <div style="padding-top: 20px; border-top: 1px solid #E3E6EE; font-size: 12px; color: #717791; line-height: 1.6;">
                <p style="margin: 0 0 4px 0;"><strong>Flint by KeyFlint</strong> · Herramientas deterministas para IA</p>
                <p style="margin: 0;">Soporte humano: <a href="mailto:support@keyflint.dev" style="color: #0B0D17; text-decoration: underline; font-weight: 600;">support@keyflint.dev</a> · <a href="https://mcp.keyflint.dev/saldo/" style="color: #717791; text-decoration: underline;">Consultar saldo</a></p>
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
