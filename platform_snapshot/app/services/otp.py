"""One-time verification codes, deliverable by email (default) or SMS.
Codes are stored hashed (Iron Rule 4); the console providers print them
in development only.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import OTPCode, utcnow
from app.security import generate_otp, hash_otp
from app.services.mailer import send_email

log = logging.getLogger("brotherbot.otp")


def _send_sms(phone: str, message: str) -> None:
    s = get_settings()
    if s.sms_provider == "twilio" and s.twilio_sid:
        import httpx

        httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_sid}/Messages.json",
            auth=(s.twilio_sid, s.twilio_token),
            data={"From": s.twilio_from, "To": phone, "Body": message},
            timeout=10,
        )
    elif s.is_production:
        log.warning("SMS provider not configured; OTP for %s dropped", phone)
    else:
        print(f"[SMS→{phone}] {message}")


def issue_otp(db: Session, destination: str, purpose: str, channel: str = "email") -> None:
    """destination is an email address (channel='email') or phone number
    (channel='sms')."""
    s = get_settings()
    code = generate_otp()
    db.add(
        OTPCode(
            destination=destination,
            code_hash=hash_otp(destination, code),
            purpose=purpose,
            expires_at=utcnow() + timedelta(minutes=s.otp_ttl_minutes),
        )
    )
    db.commit()
    text = f"Brother Bot verification code: {code}. Valid {s.otp_ttl_minutes} min. Never share it."
    if channel == "email":
        send_email(destination, "Your Brother Bot verification code", text)
    else:
        _send_sms(destination, text)


def verify_otp(db: Session, destination: str, purpose: str, code: str) -> bool:
    s = get_settings()
    row = db.execute(
        select(OTPCode)
        .where(OTPCode.destination == destination, OTPCode.purpose == purpose, OTPCode.used.is_(False))
        .order_by(OTPCode.id.desc())
    ).scalars().first()
    if row is None:
        return False
    expires = row.expires_at
    if expires.tzinfo is None:
        from datetime import timezone
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < utcnow() or row.attempts >= s.otp_max_attempts:
        return False
    row.attempts += 1
    ok = row.code_hash == hash_otp(destination, code)
    if ok:
        row.used = True
    db.commit()
    return ok
