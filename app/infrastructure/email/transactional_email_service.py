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

    def _render_license_text(self, p: LicenseEmailPayload) -> str:
        return f"""======================================================================
KEYFLINT // CRYPTOGRAPHIC GATEWAY
======================================================================

Your {p.tier.upper()} license has been generated and provisioned.

----------------------------------------------------------------------
1. LICENSE METRICS & CREDENTIALS
----------------------------------------------------------------------
License Key:      {p.license_key}
Tier:             {p.tier.upper()}
Hardware Nodes:   {p.seats}
Initial Credits:  {p.credits:,}
Expiration:       {p.expires_at or 'Perpetual (No Expiration)'}

----------------------------------------------------------------------
2. SIGNED ED25519 OFFLINE TOKEN (RFC 8032)
----------------------------------------------------------------------
{p.token}

Gateway Public Key (Hex):
{p.public_key_hex}

----------------------------------------------------------------------
3. ZERO-LATENCY OFFLINE VERIFICATION (<1ms)
----------------------------------------------------------------------
[Python]
  pip install keyflint-verify
  from keyflint_verify import verify_license
  result = verify_license("{p.token}", "{p.public_key_hex}")
  print(result.is_valid, result.tier)

[TypeScript / Node]
  npm install keyflint-verify
  import {{ verifyLicense }} from "keyflint-verify";
  const result = await verifyLicense("{p.token}", "{p.public_key_hex}");
  console.log(result.isValid, result.tier);

[Go]
  go get github.com/ArceeDev/keyflint/sdks/go-verify
  result, err := keyflint.VerifyLicense("{p.token}", "{p.public_key_hex}")

[MCP Tool Quota Guard]
  from keyflint_verify.mcp import metered
  @metered(credits=5)
  async def run_ai_tool(): ...

----------------------------------------------------------------------
Documentation: https://keyflint.dev
Repository:    https://github.com/ArceeDev/keyflint
Support:       support@keyflint.dev (or reply directly to this email)
======================================================================
"""

    def _render_license_html(self, p: LicenseEmailPayload) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Your KeyFlint License</title>
</head>
<body style="margin: 0; padding: 32px 16px; background-color: #0B0D17; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', Helvetica, Arial, sans-serif; color: #E5E7EB; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr>
      <td align="center">
        <!-- Main Card Container -->
        <table role="presentation" width="100%" style="max-width: 620px; background-color: #121420; border: 1px solid #1F2438; border-radius: 8px; overflow: hidden; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);" cellpadding="0" cellspacing="0" border="0">
          
          <!-- Top Accent Bar -->
          <tr>
            <td height="3" style="background-color: #CCFF00; line-height: 3px; font-size: 3px;">&nbsp;</td>
          </tr>

          <!-- Header -->
          <tr>
            <td style="padding: 32px 32px 24px 32px; border-bottom: 1px solid #1F2438;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td>
                    <span style="display: inline-block; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #CCFF00; background-color: rgba(204, 255, 0, 0.08); border: 1px solid rgba(204, 255, 0, 0.25); padding: 4px 10px; border-radius: 4px;">
                      KEYFLINT // CRYPTOGRAPHIC GATEWAY
                    </span>
                    <h1 style="margin: 16px 0 8px 0; font-size: 24px; font-weight: 600; color: #FFFFFF; letter-spacing: -0.02em; line-height: 1.2;">
                      Your <span style="color: #CCFF00;">{p.tier.upper()}</span> License is Active
                    </h1>
                    <p style="margin: 0; font-size: 14px; color: #9CA3AF; line-height: 1.5;">
                      Asymmetric RFC 8032 Ed25519 cryptographic token signed and ready for sub-millisecond offline verification.
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- License Specs Table -->
          <tr>
            <td style="padding: 24px 32px; border-bottom: 1px solid #1F2438;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="font-size: 13.5px;">
                <tr>
                  <td style="padding: 8px 0; color: #9CA3AF; border-bottom: 1px dashed #1F2438;">License Key</td>
                  <td align="right" style="padding: 8px 0; color: #FFFFFF; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-weight: 600; border-bottom: 1px dashed #1F2438;">{p.license_key}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #9CA3AF; border-bottom: 1px dashed #1F2438;">Tier</td>
                  <td align="right" style="padding: 8px 0; color: #CCFF00; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-weight: 600; text-transform: uppercase; border-bottom: 1px dashed #1F2438;">{p.tier.upper()}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #9CA3AF; border-bottom: 1px dashed #1F2438;">Authorized Nodes / Seats</td>
                  <td align="right" style="padding: 8px 0; color: #FFFFFF; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-weight: 600; border-bottom: 1px dashed #1F2438;">{p.seats}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #9CA3AF; border-bottom: 1px dashed #1F2438;">Included Metered Credits</td>
                  <td align="right" style="padding: 8px 0; color: #FFFFFF; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-weight: 600; border-bottom: 1px dashed #1F2438;">{p.credits:,}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; color: #9CA3AF;">Expiration</td>
                  <td align="right" style="padding: 8px 0; color: #FFFFFF; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-weight: 600;">{p.expires_at or 'Perpetual (No Expiration)'}</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Signed Token Section -->
          <tr>
            <td style="padding: 24px 32px 12px 32px;">
              <div style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: #9CA3AF; margin-bottom: 8px;">
                SIGNED ED25519 TOKEN (RFC 8032)
              </div>
              <div style="background-color: #090A12; border: 1px solid #1F2438; border-radius: 6px; padding: 14px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 11.5px; color: #F3F4F6; word-break: break-all; line-height: 1.5; user-select: all;">
                {p.token}
              </div>
            </td>
          </tr>

          <!-- Gateway Public Key Section -->
          <tr>
            <td style="padding: 12px 32px;">
              <div style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: #9CA3AF; margin-bottom: 8px;">
                GATEWAY PUBLIC KEY (HEX)
              </div>
              <div style="background-color: #090A12; border: 1px solid #1F2438; border-radius: 6px; padding: 14px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 11.5px; color: #9CA3AF; word-break: break-all; line-height: 1.5; user-select: all;">
                {p.public_key_hex}
              </div>
            </td>
          </tr>

          <!-- Quickstart Verification Section -->
          <tr>
            <td style="padding: 16px 32px 28px 32px;">
              <div style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: #9CA3AF; margin-bottom: 8px;">
                QUICKSTART VERIFICATION (&lt;1ms)
              </div>
              <div style="background-color: #090A12; border: 1px solid #1F2438; border-radius: 6px; padding: 14px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; color: #E5E7EB; line-height: 1.6; overflow-x: auto;">
                <span style="color: #6B7280;"># Python</span><br>
                pip install keyflint-verify<br>
                <span style="color: #CCFF00;">from</span> keyflint_verify <span style="color: #CCFF00;">import</span> verify_license<br>
                res = verify_license(<span style="color: #9CA3AF;">"{p.token[:20]}..."</span>, <span style="color: #9CA3AF;">"{p.public_key_hex}"</span>)<br>
                <br>
                <span style="color: #6B7280;"># TypeScript / Node</span><br>
                npm install keyflint-verify<br>
                <span style="color: #CCFF00;">import</span> {{ verifyLicense }} <span style="color: #CCFF00;">from</span> <span style="color: #9CA3AF;">"keyflint-verify"</span>;<br>
                <span style="color: #CCFF00;">const</span> res = <span style="color: #CCFF00;">await</span> verifyLicense(<span style="color: #9CA3AF;">"{p.token[:20]}..."</span>, <span style="color: #9CA3AF;">"{p.public_key_hex}"</span>);
              </div>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding: 24px 32px; background-color: #0E101A; border-top: 1px solid #1F2438; text-align: center; font-size: 12px; color: #6B7280; line-height: 1.6;">
              KeyFlint v1.1.0 · Self-Hosted Ed25519 Cryptographic Licensing &amp; Quota Gateway<br>
              <a href="https://keyflint.dev" style="color: #9CA3AF; text-decoration: none; margin: 0 8px;">Documentation</a> ·
              <a href="https://github.com/ArceeDev/keyflint" style="color: #9CA3AF; text-decoration: none; margin: 0 8px;">GitHub</a> ·
              <a href="mailto:support@keyflint.dev" style="color: #9CA3AF; text-decoration: none; margin: 0 8px;">Support</a>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
