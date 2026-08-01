"""Outbound email. Providers:

- console (default): prints the mail — development only.
- smtp: any SMTP relay (Brevo/Mailjet/Gmail SMTP creds via BB_SMTP_*).
- brevo: Brevo (ex-Sendinblue) HTTP API — free tier ~300 mails/day,
  no SMTP port needed (useful on VPSes that block port 25/587).

Sends are best-effort: failures are logged, never raised into request paths.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr

import httpx

from app.config import get_settings

log = logging.getLogger("brotherbot.mailer")


def _send_smtp(to: str, subject: str, body: str) -> bool:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if s.smtp_port == 465:
        server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15)
    else:
        server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
        server.starttls()
    try:
        if s.smtp_user:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)
        return True
    finally:
        server.quit()


def _send_brevo(to: str, subject: str, body: str) -> bool:
    s = get_settings()
    from_name, from_email = parseaddr(s.email_from)
    resp = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": s.brevo_api_key, "content-type": "application/json"},
        json={
            "sender": {"name": from_name or "Brother Bot", "email": from_email},
            "to": [{"email": to}],
            "subject": subject,
            "textContent": body,
        },
        timeout=15,
    )
    if resp.status_code >= 300:
        log.warning("brevo send failed %s: %s", resp.status_code, resp.text[:200])
        return False
    return True


def send_email(to: str, subject: str, body: str) -> bool:
    s = get_settings()
    try:
        if s.email_provider == "smtp" and s.smtp_host:
            return _send_smtp(to, subject, body)
        if s.email_provider == "brevo" and s.brevo_api_key:
            return _send_brevo(to, subject, body)
        if s.is_production:
            log.warning("email provider not configured; mail to %s dropped", to)
            return False
        print(f"[EMAIL→{to}] {subject}\n{body}")
        return True
    except Exception as exc:  # never break a request over a mail failure
        log.warning("email send to %s failed: %s", to, exc)
        return False
