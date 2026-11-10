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
_BRAND_LOGO_WHITE_URL = "https://mcp.keyflint.dev/assets/flint-brand-badge.png"
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
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="dark only">
  <meta name="supported-color-schemes" content="dark only">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Saldo actualizado · Flint</title>
</head>
<body bgcolor="#0B0D17" style="margin: 0; padding: 0; width: 100% !important; background-color: #0B0D17; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, Helvetica, Arial, sans-serif; color: #FFFFFF; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#0B0D17" style="background-color: #0B0D17; width: 100%; margin: 0; padding: 24px 0;">
    <tr>
      <td align="center" style="padding: 0 10px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#111424" style="max-width: 560px; width: 100%; background-color: #111424; border: 1px solid #1E233D; border-radius: 14px;">
          <tr>
            <td bgcolor="#111424" style="padding: 36px 24px; background-color: #111424;">
              <div style="text-align: center; margin-bottom: 28px;">
                <a href="https://mcp.keyflint.dev" target="_blank" style="text-decoration: none; display: inline-block;">
                  <img src="{_BRAND_LOGO_WHITE_URL}" alt="Flint" width="156" height="auto" style="display: block; margin: 0 auto; border: 0; outline: none; text-decoration: none; max-width: 144px; height: auto;" />
                </a>
              </div>

              <h1 style="margin: 0 0 12px 0; font-size: 24px; font-weight: 700; color: #FFFFFF; letter-spacing: -0.02em; line-height: 1.25; text-align: center;">Saldo de créditos <span style="color: #CCFF00;">actualizado</span></h1>
              <p style="margin: 0 0 28px 0; font-size: 14px; color: #B2B8D0; line-height: 1.6; text-align: center;">Tu cuenta de Flint ya dispone de los nuevos créditos para seguir procesando extractos bancarios Norma 43 y facturación contable sin interrupciones.</p>
              
              <div style="background-color: #171B30; border: 1px solid #282F50; border-radius: 12px; padding: 22px 20px; margin-bottom: 24px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td style="padding-bottom: 12px; border-bottom: 1px solid #232944; color: #8E95AF; font-size: 14px;">Créditos añadidos</td>
                    <td align="right" style="padding-bottom: 12px; border-bottom: 1px solid #232944; color: #FFFFFF; font-weight: 700; font-size: 16px;">+{added_credits:,}</td>
                  </tr>
                  <tr>
                    <td style="padding-top: 14px; color: #8E95AF; font-size: 14px;">Saldo disponible</td>
                    <td align="right" style="padding-top: 14px; color: #CCFF00; font-weight: 800; font-size: 22px;">
                      {new_balance:,} <span style="font-size: 14px; font-weight: 600; color: #8E95AF;">créditos</span>
                    </td>
                  </tr>
                </table>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 18px;">
                  <tr>
                    <td>
                      <a href="https://mcp.keyflint.dev/saldo/#licencia={html.escape(license_key)}" style="display: block; text-align: center; background-color: #CCFF00; color: #0B0D17; font-size: 14px; font-weight: 700; text-decoration: none; padding: 13px 20px; border-radius: 8px; letter-spacing: -0.01em;">Ver mi saldo en vivo y copiar clave &rarr;</a>
                    </td>
                  </tr>
                </table>
              </div>

              <p style="margin: 0 0 20px 0; font-size: 12px; color: #717791; text-align: center;">Licencia vinculada: <code style="font-family: ui-monospace, Menlo, Consolas, monospace; color: #CCFF00; background: #0B0D17; padding: 4px 8px; border-radius: 5px; border: 1px solid #1E233D; -webkit-user-select: all; user-select: all;">{html.escape(short)}</code></p>

              <div style="background-color: #171B30; border-left: 3px solid #CCFF00; padding: 14px 16px; border-radius: 0 8px 8px 0; margin-bottom: 24px;">
                <p style="margin: 0; font-size: 13px; color: #D1D5E4; line-height: 1.55;">
                  <strong style="color: #FFFFFF;">Incentivo Flint:</strong> Consulta tu consumo en vivo o automatiza la conciliación bancaria procesando lotes de extractos en <a href="https://mcp.keyflint.dev/lote/" style="color: #CCFF00; text-decoration: underline; font-weight: 600;">nuestro procesador web en el navegador &rarr;</a>
                </p>
              </div>

              <div style="padding-top: 20px; border-top: 1px solid #1E233D; font-size: 12px; color: #6F7693; line-height: 1.6; text-align: center;">
                <p style="margin: 0 0 4px 0;"><strong style="color: #FFFFFF;">Flint by KeyFlint</strong> · Herramientas contables y bancarias verificadas para IA</p>
                <p style="margin: 0;">Soporte humano directo: <a href="mailto:support@keyflint.dev" style="color: #CCFF00; text-decoration: none; font-weight: 600;">support@keyflint.dev</a></p>
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
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="dark only">
  <meta name="supported-color-schemes" content="dark only">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Créditos agotados · Flint</title>
</head>
<body bgcolor="#0B0D17" style="margin: 0; padding: 0; width: 100% !important; background-color: #0B0D17; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, Helvetica, Arial, sans-serif; color: #FFFFFF; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#0B0D17" style="background-color: #0B0D17; width: 100%; margin: 0; padding: 24px 0;">
    <tr>
      <td align="center" style="padding: 0 10px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#111424" style="max-width: 560px; width: 100%; background-color: #111424; border: 1px solid #1E233D; border-radius: 14px;">
          <tr>
            <td bgcolor="#111424" style="padding: 36px 24px; background-color: #111424;">
              <div style="text-align: center; margin-bottom: 28px;">
                <a href="https://mcp.keyflint.dev" target="_blank" style="text-decoration: none; display: inline-block;">
                  <img src="{_BRAND_LOGO_WHITE_URL}" alt="Flint" width="156" height="auto" style="display: block; margin: 0 auto; border: 0; outline: none; text-decoration: none; max-width: 144px; height: auto;" />
                </a>
              </div>

              <h1 style="margin: 0 0 12px 0; font-size: 24px; font-weight: 700; color: #FFFFFF; letter-spacing: -0.02em; line-height: 1.25; text-align: center;">Has completado tus <span style="color: #CCFF00;">créditos de prueba</span></h1>
              <p style="margin: 0 0 16px 0; font-size: 14px; color: #B2B8D0; line-height: 1.6; text-align: center;">Esperamos que Flint te haya ahorrado tiempo automatizando tus extractos bancarios o facturación contable.</p>
              <p style="margin: 0 0 28px 0; font-size: 13px; color: #8E95AF; line-height: 1.6; text-align: center;">Tu configuración y tu licencia siguen listas: <strong>no tienes que volver a instalar nada ni cambiar de clave</strong> en Claude Desktop, Cursor ni en el navegador.</p>

              <div style="background-color: #171B30; border: 1px solid #282F50; border-radius: 12px; padding: 22px 20px; margin-bottom: 24px; text-align: center;">
                <div style="font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #8E95AF; margin-bottom: 6px;">Recarga Recomendada</div>
                <div style="font-size: 22px; font-weight: 800; color: #FFFFFF; margin-bottom: 4px;">{topup_eur} € &rarr; <span style="color: #CCFF00;">{topup_credits:,} créditos</span></div>
                <div style="font-size: 12px; color: #7B829E; margin-bottom: 16px;">Sin caducidad · IVA incluido · Pago seguro con Stripe</div>
                <a href="{u}" style="display: block; text-align: center; background-color: #CCFF00; color: #0B0D17; font-size: 14px; font-weight: 700; text-decoration: none; padding: 13px 20px; border-radius: 8px; letter-spacing: -0.01em;">Recargar {topup_eur} € en 1 clic &rarr;</a>
              </div>

              <p style="margin: 0 0 20px 0; font-size: 12px; color: #717791; text-align: center;">Licencia vinculada: <code style="font-family: ui-monospace, Menlo, Consolas, monospace; color: #CCFF00; background: #0B0D17; padding: 4px 8px; border-radius: 5px; border: 1px solid #1E233D; -webkit-user-select: all; user-select: all;">{html.escape(short)}</code></p>

              <p style="margin: 0 0 24px 0; padding-top: 16px; border-top: 1px solid #1E233D; font-size: 12px; color: #717791; line-height: 1.5; text-align: center;">{html.escape(lead_en)} {html.escape(offer_en)} <a href="{u}" style="color: #CCFF00; text-decoration: none; font-weight: 600;">Top up &rarr;</a></p>

              <div style="padding-top: 20px; border-top: 1px solid #1E233D; font-size: 12px; color: #6F7693; line-height: 1.6; text-align: center;">
                <p style="margin: 0 0 4px 0;"><strong style="color: #FFFFFF;">Flint by KeyFlint</strong> · Herramientas contables y bancarias verificadas para IA</p>
                <p style="margin: 0;">¿Dudas con tu configuración? Escríbenos a <a href="mailto:support@keyflint.dev" style="color: #CCFF00; text-decoration: none; font-weight: 600;">support@keyflint.dev</a></p>
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

    def send_trial_nurture(self, recipient_email: str, *, step: int, consumed: int, balance: int,
                           unsubscribe_url: str) -> bool:
        """Follow-up of the free trial (days 1, 3 and 7). Spanish, one action per email, unsubscribe link."""
        hub = "https://mcp.keyflint.dev"
        if step == 1 and consumed == 0:
            subject = "Tu primer extracto con Flint, en 1 minuto"
            title = "Prueba Flint con un extracto real"
            paras = ["Tu licencia de prueba aún no ha procesado nada. La forma más rápida de verlo:",
                     "Abre el procesador, arrastra un extracto Norma 43 (.n43 o .c43) que hayas descargado del banco "
                     "y pega tu licencia. En segundos tienes movimientos, saldos comprobados y un resumen para Excel.",
                     "No hay que instalar nada. Si el fichero falla, no se cobra."]
            cta, url = "Abrir el procesador", f"{hub}/lote/"
        elif step == 1:
            subject = "Siguiente paso: que los extractos se procesen solos"
            title = "Deja una carpeta vigilada"
            paras = [f"Ya has usado {consumed} créditos. Para no repetirlo cada mes:",
                     "Con un comando, Flint crea la carpeta «Flint Extractos». Cada extracto que dejes en la "
                     "subcarpeta de un cliente se procesa solo y genera su informe y su resumen para Excel, "
                     "también después de reiniciar el ordenador."]
            cta, url = "Activar la carpeta vigilada", f"{hub}/asesorias/#alta"
        elif step == 3:
            subject = "Norma 43 directo a A3, Sage o ContaSol"
            title = "Del extracto al programa contable, sin picar"
            paras = ["Además de leer y conciliar, Flint convierte el extracto en un fichero que importas en tu "
                     "programa de contabilidad. Los importes y las fechas salen del fichero del banco: Flint nunca "
                     "se los inventa, y lo que no encaja se marca para revisarlo.",
                     "Con la instalación local, los ficheros de tus clientes no salen del despacho. "
                     f"Te lo explicamos en {hub}/confianza/."]
            cta, url = "Ver la conversión a ContaSol", f"{hub}/norma43-a-contasol/"
        else:
            subject = "Plan Despacho: una cuota fija para todo el despacho"
            title = "Cuando quieras pasar del piloto al día a día"
            paras = [f"Te quedan {balance} créditos de prueba.",
                     "El Plan Despacho Básico cuesta 49 €/mes y trae 2.500 créditos cada mes: unos 625 extractos "
                     "leídos y conciliados, 3 puestos y factura con NIF. Sin permanencia.",
                     "Si contratas con este mismo correo, tu licencia actual se convierte en la del plan: "
                     "no tienes que cambiar nada en tu ordenador."]
            cta, url = "Ver el Plan Despacho", f"{hub}/precios/#despacho"
        text_body = (f"Hola,\n\n" + "\n\n".join(paras) + f"\n\n{cta}: {url}\n\n"
                     "Dudas: responde a este correo o escribe a support@keyflint.dev\n\n"
                     f"--\nRecibes este correo porque pediste una licencia de prueba de Flint. "
                     f"Darte de baja: {unsubscribe_url}\n")
        esc = html.escape
        body = "".join(f'<p style="margin: 0 0 14px 0; font-size: 14px; color: #B2B8D0; line-height: 1.6;">{esc(x)}</p>'
                       for x in paras)
        html_body = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="color-scheme" content="dark only">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{esc(subject)}</title></head>
<body bgcolor="#0B0D17" style="margin: 0; padding: 0; background-color: #0B0D17; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, Helvetica, Arial, sans-serif; color: #FFFFFF;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#0B0D17" style="padding: 24px 0;"><tr><td align="center" style="padding: 0 10px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#111424" style="max-width: 560px; background-color: #111424; border: 1px solid #1E233D; border-radius: 14px;"><tr><td style="padding: 36px 24px;">
<div style="margin-bottom: 24px;"><img src="{_BRAND_LOGO_WHITE_URL}" alt="Flint" width="144" style="display: block; border: 0; max-width: 144px; height: auto;" /></div>
<h1 style="margin: 0 0 16px 0; font-size: 22px; font-weight: 700; color: #FFFFFF; line-height: 1.3;">{esc(title)}</h1>
{body}
<a href="{esc(url, quote=True)}" style="display: inline-block; margin: 8px 0 24px 0; background-color: #CCFF00; color: #0B0D17; font-size: 14px; font-weight: 700; text-decoration: none; padding: 12px 20px; border-radius: 8px;">{esc(cta)}</a>
<p style="margin: 0; padding-top: 16px; border-top: 1px solid #1E233D; font-size: 12px; color: #6F7693; line-height: 1.6;">¿Dudas? Responde a este correo o escribe a <a href="mailto:support@keyflint.dev" style="color: #CCFF00; text-decoration: none;">support@keyflint.dev</a>.<br>
Recibes este correo porque pediste una licencia de prueba de Flint. <a href="{esc(unsubscribe_url, quote=True)}" style="color: #8E95AF;">Darme de baja</a></p>
</td></tr></table></td></tr></table></body></html>"""
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
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="dark only">
  <meta name="supported-color-schemes" content="dark only">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tu portal de Flint</title>
</head>
<body bgcolor="#0B0D17" style="margin: 0; padding: 0; width: 100% !important; background-color: #0B0D17; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, Helvetica, Arial, sans-serif; color: #FFFFFF; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#0B0D17" style="background-color: #0B0D17; width: 100%; margin: 0; padding: 24px 0;">
    <tr>
      <td align="center" style="padding: 0 10px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#111424" style="max-width: 560px; width: 100%; background-color: #111424; border: 1px solid #1E233D; border-radius: 14px;">
          <tr>
            <td bgcolor="#111424" style="padding: 36px 24px; background-color: #111424;">
              <div style="text-align: center; margin-bottom: 28px;">
                <a href="https://mcp.keyflint.dev" target="_blank" style="text-decoration: none; display: inline-block;">
                  <img src="{_BRAND_LOGO_WHITE_URL}" alt="Flint" width="156" height="auto" style="display: block; margin: 0 auto; border: 0; outline: none; text-decoration: none; max-width: 144px; height: auto;" />
                </a>
              </div>
              <h1 style="margin: 0 0 12px 0; font-size: 24px; font-weight: 700; color: #FFFFFF; letter-spacing: -0.02em; line-height: 1.25; text-align: center;">Acceso al portal de licencias</h1>
              <p style="margin: 0 0 16px 0; font-size: 14px; color: #B2B8D0; line-height: 1.6; text-align: center;">Alguien (probablemente tú) ha solicitado consultar sus licencias y saldo en Flint.</p>
              <p style="margin: 0 0 24px 0; font-size: 13px; color: #8E95AF; line-height: 1.6; text-align: center;">Este enlace caduca en {ttl_minutes} minutos y solo funciona una vez para tu seguridad.</p>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 24px;">
                <tr>
                  <td>
                    <a href="{safe_link}" style="display: block; text-align: center; background-color: #CCFF00; color: #0B0D17; font-size: 14px; font-weight: 700; text-decoration: none; padding: 13px 20px; border-radius: 8px; letter-spacing: -0.01em;">Abrir mi portal &rarr;</a>
                  </td>
                </tr>
              </table>
              <p style="font-size: 12px; color: #6F7693; margin: 0 0 20px 0; text-align: center;">Si no lo has pedido tú, ignora este correo: nadie puede ver tus licencias sin este enlace.</p>
              <div style="padding-top: 20px; border-top: 1px solid #1E233D; font-size: 12px; color: #6F7693; text-align: center;">
                Flint by KeyFlint · <a href="mailto:support@keyflint.dev" style="color: #CCFF00; text-decoration: none; font-weight: 600;">support@keyflint.dev</a>
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
        tier_title = p.tier.replace("_", " ").replace("-", " ").title()
        return f"""Your KeyFlint {tier_title} license is active.

License key:
{p.license_key}

Tier: {tier_title}
Seats: {p.seats}
Included credits: {p.credits:,}
Expires: {(p.expires_at or '')[:10] or 'Never (perpetual)'}
Gateway public key: {p.public_key_hex}

Setup guide (Python, JS, Go): {_DOCS_URL}

Questions? Reply to this email or write to support@keyflint.dev.
"""

    def _render_license_html(self, p: LicenseEmailPayload) -> str:
        cell = "padding: 10px 0; color: #8E95AF; border-bottom: 1px solid #232944; font-size: 13px;"
        val_cell = "padding: 10px 0; color: #FFFFFF; border-bottom: 1px solid #232944; font-size: 13px; font-weight: 600;"
        rows = "".join(
            f'<tr><td style="{cell}">{label}</td><td align="right" style="{val_cell}">{value}</td></tr>'
            for label, value in (
                ("Plan", p.tier.replace("_", " ").replace("-", " ").title()),
                ("Equipos permitidos", p.seats),
                ("Créditos incluidos", f"{p.credits:,}"),
                ("Validez", (p.expires_at or "")[:10] or "Permanente (sin caducidad)"),
            )
        )
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="dark only">
  <meta name="supported-color-schemes" content="dark only">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tu licencia de Flint</title>
</head>
<body bgcolor="#0B0D17" style="margin: 0; padding: 0; width: 100% !important; background-color: #0B0D17; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, Helvetica, Arial, sans-serif; color: #FFFFFF; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#0B0D17" style="background-color: #0B0D17; width: 100%; margin: 0; padding: 24px 0;">
    <tr>
      <td align="center" style="padding: 0 10px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#111424" style="max-width: 560px; width: 100%; background-color: #111424; border: 1px solid #1E233D; border-radius: 14px;">
          <tr>
            <td bgcolor="#111424" style="padding: 36px 24px; background-color: #111424;">
              <div style="text-align: center; margin-bottom: 28px;">
                <a href="https://mcp.keyflint.dev" target="_blank" style="text-decoration: none; display: inline-block;">
                  <img src="{_BRAND_LOGO_WHITE_URL}" alt="Flint" width="156" height="auto" style="display: block; margin: 0 auto; border: 0; outline: none; text-decoration: none; max-width: 144px; height: auto;" />
                </a>
              </div>

              <h1 style="margin: 0 0 12px 0; font-size: 24px; font-weight: 700; color: #FFFFFF; letter-spacing: -0.02em; line-height: 1.25; text-align: center;">Tu licencia <span style="color: #CCFF00;">{p.tier.replace("_", " ").replace("-", " ").title()}</span> está activa</h1>
              <p style="margin: 0 0 28px 0; font-size: 14px; color: #B2B8D0; line-height: 1.6; text-align: center;">Herramientas para extractos bancarios Norma 43 y facturación electrónica Facturae / Veri*factu listas para conciliar con cuadre exacto y sin alucinaciones.</p>
              
              <div style="background-color: #171B30; border: 1px solid #282F50; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
                <div style="font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #8E95AF; margin-bottom: 8px;">Clave de Licencia</div>
                <div style="font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; color: #CCFF00; word-break: break-all; line-height: 1.5; background-color: #0B0D17; padding: 12px 14px; border-radius: 8px; border: 1px solid #1E233D; -webkit-user-select: all; user-select: all;">{p.license_key}</div>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 14px;">
                  <tr>
                    <td>
                      <a href="https://mcp.keyflint.dev/saldo/" target="_blank" style="display: block; text-align: center; background-color: #CCFF00; color: #0B0D17; font-size: 13px; font-weight: 700; text-decoration: none; padding: 12px 16px; border-radius: 8px; letter-spacing: -0.01em;">Consultar saldo y copiar clave &rarr;</a>
                    </td>
                  </tr>
                </table>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 18px; font-size: 13px;">{rows}</table>
              </div>

              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 16px;">
                <tr>
                  <td>
                    <a href="{_DOCS_URL}" style="display: block; text-align: center; background-color: #0B0D17; color: #CCFF00; border: 1px solid #282F50; font-size: 14px; font-weight: 700; text-decoration: none; padding: 13px 20px; border-radius: 8px; letter-spacing: -0.01em;">Guía de instalación rápida (Claude, Cursor, VS Code) &rarr;</a>
                  </td>
                </tr>
              </table>

              <p style="margin: 0 0 24px 0; font-size: 13px; color: #8E95AF; line-height: 1.5; text-align: center;">
                ¿Prefieres procesar sin terminal? <a href="https://mcp.keyflint.dev/lote/" style="color: #CCFF00; text-decoration: underline; font-weight: 600;">Procesar en /lote/ en el navegador &rarr;</a>
              </p>

              <div style="background-color: #171B30; border-left: 3px solid #CCFF00; padding: 14px 16px; border-radius: 0 8px 8px 0; margin-bottom: 24px;">
                <p style="margin: 0; font-size: 13px; color: #D1D5E4; line-height: 1.55;">
                  <strong style="color: #FFFFFF;">Incentivo Flint:</strong> Automatiza la conciliación bancaria arrastrando ficheros Norma 43 (.n43, .c43) o facturas electrónicas con descarga inmediata en formato CSV y JSON estructurado.
                </p>
              </div>

              <div style="padding-top: 20px; border-top: 1px solid #1E233D; font-size: 12px; color: #6F7693; line-height: 1.6; text-align: center;">
                <p style="margin: 0 0 4px 0;"><strong style="color: #FFFFFF;">Flint by KeyFlint</strong> · Cuadre bancario certificado y rigor contable para despachos y empresas.</p>
                <p style="margin: 0;">Soporte humano: <a href="mailto:support@keyflint.dev" style="color: #CCFF00; text-decoration: none; font-weight: 600;">support@keyflint.dev</a> · <a href="https://mcp.keyflint.dev/terminos/" style="color: #8E95AF; text-decoration: none;">Términos</a> · <a href="https://mcp.keyflint.dev/reembolsos/" style="color: #8E95AF; text-decoration: none;">Reembolsos</a></p>
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
