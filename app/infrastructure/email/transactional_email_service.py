"""Infrastructure adapter for transactional email dispatching via Resend or SMTP."""

from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import smtplib
from typing import Optional

import httpx

from app.config import get_settings
from app.domain.interfaces.email_sender import IEmailSender, LicenseEmailPayload

logger = logging.getLogger("keyflint.email")


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

    def send_license_issued(self, payload: LicenseEmailPayload) -> bool:
        """Dispatches license activation email with signed Ed25519 token."""
        subject = f"Your KeyFlint {payload.tier.upper()} License & Cryptographic Key"
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
        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; color: #141311; background: #FAF9F6; border: 1px solid #E5E3DC; border-radius: 8px;">
            <h2 style="color: #A63D12; margin-top: 0;">KeyFlint Quota Replenished</h2>
            <p>Your license <code>{license_key[:12]}...</code> quota has been refilled successfully.</p>
            <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                <tr><td style="padding: 8px 0; border-bottom: 1px solid #E5E3DC;">Added Credits:</td><td style="font-weight: bold; text-align: right; border-bottom: 1px solid #E5E3DC;">+{added_credits:,}</td></tr>
                <tr><td style="padding: 8px 0;">New Balance:</td><td style="font-weight: bold; text-align: right; color: #15803D;">{new_balance:,} credits</td></tr>
            </table>
        </div>
        """
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
        """Transmits email or falls back to structured logging when offline/unconfigured."""
        if not self._enabled:
            logger.info(
                "Transactional email disabled/mocked. "
                "Recipient: %s, Subject: '%s'",
                recipient,
                subject,
            )
            return True

        if self._resend_api_key:
            return self._send_via_resend(recipient, subject, text_body, html_body)

        if self._smtp_host:
            return self._send_via_smtp(recipient, subject, text_body, html_body)

        logger.info(
            "No email provider credentials configured (RESEND_API_KEY or SMTP_HOST). "
            "Simulating dispatch to: %s",
            recipient,
        )
        return True

    def _send_via_resend(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: str,
    ) -> bool:
        try:
            with httpx.Client(timeout=10.0) as client:
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
                if resp.status_code in (200, 201):
                    logger.info("Resend dispatch succeeded for %s", recipient)
                    return True
                logger.error("Resend API error (%s): %s", resp.status_code, resp.text)
                return False
        except Exception as exc:
            logger.error("Resend dispatch exception for %s: %s", recipient, exc)
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
            logger.error("SMTP dispatch exception for %s: %s", recipient, exc)
            return False

    def _render_license_text(self, p: LicenseEmailPayload) -> str:
        return f"""Welcome to KeyFlint!

Your {p.tier.upper()} license has been generated and activated.

----------------------------------------------------------------------
LICENSE DETAILS
----------------------------------------------------------------------
License Key:     {p.license_key}
Tier:            {p.tier.upper()}
Max Seats/Nodes: {p.seats}
Initial Credits: {p.credits:,}
Expiration:      {p.expires_at or 'Perpetual (No Expiration)'}

----------------------------------------------------------------------
SIGNED ED25519 OFFLINE TOKEN (RFC 8032)
----------------------------------------------------------------------
{p.token}

Gateway Public Key (Hex):
{p.public_key_hex}

----------------------------------------------------------------------
QUICKSTART: OFFLINE VERIFICATION IN 30 SECONDS
----------------------------------------------------------------------
In Python:
  pip install keyflint-verify
  from keyflint_verify import verify_license
  payload = verify_license("{p.token}", "{p.public_key_hex}")
  print(payload.is_valid, payload.tier)

In TypeScript / Node:
  npm i keyflint-verify
  import {{ verifyLicense }} from "keyflint-verify";
  const result = await verifyLicense("{p.token}", "{p.public_key_hex}");
  console.log(result.isValid, result.tier);

MCP Tool Metering:
  from keyflint_verify.mcp import metered
  @metered(credits=5)
  async def my_ai_tool(): ...

Commercial Source & Docs:
  https://github.com/ArceeDev/keyflint

Need help or enterprise integration? Reply to this email.
"""

    def _render_license_html(self, p: LicenseEmailPayload) -> str:
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #F6F5F1; margin: 0; padding: 24px; color: #141311; }}
  .box {{ max-width: 620px; margin: 0 auto; background: #FFFFFF; border: 1px solid #E2DFD8; border-radius: 8px; padding: 32px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }}
  .header {{ border-bottom: 2px solid #A63D12; padding-bottom: 16px; margin-bottom: 24px; }}
  .header h1 {{ margin: 0; font-size: 22px; color: #141311; letter-spacing: -0.5px; }}
  .header p {{ margin: 4px 0 0; color: #6E6D66; font-size: 14px; }}
  .badge {{ display: inline-block; background: #FAF0EB; color: #A63D12; font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 4px 8px; border-radius: 4px; margin-bottom: 12px; }}
  .specs {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  .specs td {{ padding: 8px 0; border-bottom: 1px solid #EFECE6; font-size: 14px; }}
  .specs td.val {{ text-align: right; font-weight: 600; font-family: monospace; color: #141311; }}
  .token-box {{ background: #FAF9F6; border: 1px solid #E2DFD8; border-radius: 6px; padding: 12px; font-family: monospace; font-size: 12px; word-break: break-all; margin: 12px 0 20px; line-height: 1.4; color: #141311; }}
  .code {{ background: #141311; color: #F6F5F1; border-radius: 6px; padding: 12px; font-family: monospace; font-size: 12px; overflow-x: auto; }}
  .footer {{ margin-top: 32px; font-size: 12px; color: #8C8A82; text-align: center; border-top: 1px solid #EFECE6; padding-top: 16px; }}
</style>
</head>
<body>
  <div class="box">
    <div class="header">
      <span class="badge">KeyFlint Cryptographic Gateway</span>
      <h1>Your {p.tier.upper()} License is Active</h1>
      <p>Thank you for purchasing KeyFlint. Your asymmetric Ed25519 token is ready.</p>
    </div>

    <table class="specs">
      <tr><td>License Key</td><td class="val">{p.license_key}</td></tr>
      <tr><td>Tier</td><td class="val">{p.tier.upper()}</td></tr>
      <tr><td>Authorized Nodes / Seats</td><td class="val">{p.seats}</td></tr>
      <tr><td>Included Metered Credits</td><td class="val">{p.credits:,}</td></tr>
      <tr><td>Expiration</td><td class="val">{p.expires_at or 'Perpetual (No Expiration)'}</td></tr>
    </table>

    <h3 style="font-size: 14px; margin: 20px 0 6px;">Signed Ed25519 Token</h3>
    <div class="token-box">{p.token}</div>

    <h3 style="font-size: 14px; margin: 20px 0 6px;">Gateway Public Key (Hex)</h3>
    <div class="token-box">{p.public_key_hex}</div>

    <h3 style="font-size: 14px; margin: 20px 0 6px;">Zero-Dependency Verification</h3>
    <pre class="code">pip install keyflint-verify   # Python
npm i keyflint-verify         # TypeScript</pre>

    <div class="footer">
      KeyFlint v1.1.0 · Self-Hosted Ed25519 Licensing &amp; Quota-Metering Gateway<br>
      Need assistance? Reply directly to this confirmation email.
    </div>
  </div>
</body>
</html>"""
