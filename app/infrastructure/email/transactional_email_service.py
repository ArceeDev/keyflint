"""Infrastructure adapter for transactional email dispatching via Resend or SMTP."""

from __future__ import annotations

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
        subject = f"KeyFlint Quota Replenished: +{added_credits:,} Credits"
        text_body = (
            f"Hello,\n\n"
            f"Your KeyFlint license ({license_key[:12]}...) has been replenished.\n"
            f"- Added credits: +{added_credits:,}\n"
            f"- Current total balance: {new_balance:,} credits\n\n"
            f"Thank you for using KeyFlint.\n"
        )
        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark"></head>
<body style="margin: 0; padding: 32px 16px; background-color: #0B0D17; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #FFFFFF;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0B0D17;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 620px; background-color: #0B0D17; border: 1px solid #1F2438; border-radius: 8px;" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding: 32px;">
              <h1 style="margin: 0 0 12px 0; font-size: 22px; font-weight: 600; color: #FFFFFF;">Quota <span style="color: #CCFF00;">replenished</span></h1>
              <p style="margin: 0 0 20px 0; font-size: 14px; color: #FFFFFF; line-height: 1.5;">Your license <code style="font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;">{license_key[:12]}...</code> has been refilled for the new billing cycle.</p>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="font-size: 14px;">
                <tr>
                  <td style="padding: 8px 0; color: #FFFFFF; border-bottom: 1px solid #1F2438;">Added credits</td>
                  <td align="right" style="padding: 8px 0; color: #FFFFFF; font-weight: 600; border-bottom: 1px solid #1F2438;">+{added_credits:,}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #FFFFFF;">New balance</td>
                  <td align="right" style="padding: 8px 0; color: #CCFF00; font-weight: 600;">{new_balance:,} credits</td>
                </tr>
              </table>
              <p style="margin: 24px 0 0 0; font-size: 12px; color: #FFFFFF;">Support: <a href="mailto:support@keyflint.dev" style="color: #FFFFFF;">support@keyflint.dev</a></p>
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
        cell = "padding: 8px 0; color: #FFFFFF; border-bottom: 1px solid #1F2438;"
        rows = "".join(
            f'<tr><td style="{cell}">{label}</td><td align="right" style="{cell} font-weight: 600;">{value}</td></tr>'
            for label, value in (
                ("Tier", p.tier.capitalize()),
                ("Seats", p.seats),
                ("Included credits", f"{p.credits:,}"),
                ("Expires", (p.expires_at or "")[:10] or "Never (perpetual)"),
            )
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Your KeyFlint license</title></head>
<body style="margin: 0; padding: 32px 16px; background-color: #0B0D17; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #FFFFFF;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #0B0D17;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 620px; background-color: #0B0D17; border: 1px solid #1F2438; border-radius: 8px;" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding: 32px;">
              <h1 style="margin: 0 0 12px 0; font-size: 22px; font-weight: 600; color: #FFFFFF;">Your <span style="color: #CCFF00;">{p.tier.capitalize()}</span> license is active</h1>
              <p style="margin: 0 0 8px 0; font-size: 14px; color: #FFFFFF;">License key:</p>
              <p style="margin: 0 0 24px 0; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: #FFFFFF; word-break: break-all; line-height: 1.5;">{p.license_key}</p>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="font-size: 14px;">{rows}</table>
              <p style="margin: 24px 0 0 0; font-size: 14px; color: #FFFFFF; line-height: 1.5;">Set it up with the Python, JS or Go SDK: <a href="{_DOCS_URL}" style="color: #CCFF00;">setup guide</a>.</p>
              <p style="margin: 8px 0 0 0; font-size: 12px; color: #FFFFFF; word-break: break-all;">Gateway public key: {p.public_key_hex}</p>
              <p style="margin: 24px 0 0 0; font-size: 12px; color: #FFFFFF;">Questions? Reply to this email or write to <a href="mailto:support@keyflint.dev" style="color: #FFFFFF;">support@keyflint.dev</a>.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
