# FILE: backend/services/email_service.py
# Send invite emails (SMTP or Resend free)

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from config import settings

# Try Resend first, fall back to SMTP
try:
    import httpx as _httpx
    _has_httpx = True
except ImportError:
    _has_httpx = False


async def send_invite_email(
    to_email: str,
    candidate_name: str,
    session_title: str,
    invite_link: str,
    proctor_name: str = "Proctor",
) -> bool:
    """
    Send an invitation email to a candidate.
    Uses Resend API if configured, otherwise falls back to SMTP.
    Returns True if sent successfully, False otherwise.
    """
    subject = f"SENTINEL — You're invited to: {session_title}"
    html_body = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1a1a2e;">SENTINEL Proctoring Platform</h2>
        <p>Hello {candidate_name},</p>
        <p>{proctor_name} has invited you to participate in: <strong>{session_title}</strong></p>
        <p>Click the link below to join:</p>
        <a href="{invite_link}"
           style="display: inline-block; padding: 12px 24px; background: #4361ee;
                  color: white; text-decoration: none; border-radius: 6px; margin: 16px 0;">
            Join Session
        </a>
        <p style="color: #666; font-size: 12px;">
            If you did not expect this invitation, please ignore this email.
        </p>
    </div>
    """

    # Try Resend API first
    if settings.resend_api_key and _has_httpx:
        try:
            async with _httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                    json={
                        "from": settings.email_from,
                        "to": [to_email],
                        "subject": subject,
                        "html": html_body,
                    },
                    timeout=10.0,
                )
                return resp.status_code == 200
        except Exception:
            pass

    # Fall back to SMTP
    if settings.smtp_host and settings.smtp_user:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.email_from
            msg["To"] = to_email
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_pass)
                server.send_message(msg)
            return True
        except Exception:
            pass

    return False
