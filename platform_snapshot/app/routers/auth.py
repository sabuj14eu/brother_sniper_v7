"""Auth — email-first registration with a verification code, optional phone
(SMS OTP once a provider is configured), login by email OR phone (+TOTP),
account recovery via emailed code. Consent to terms + risk disclaimer is
recorded (compliance)."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import SESSION_COOKIE, optional_user
from app.models.platform import NotificationPrefs, TelegramSettings
from app.models.trading import DEFAULT_SYMBOLS, BotSettings, RiskLimits, SymbolSetting, VPSStatus
from app.models.user import ConsentLog, User, UserSession, utcnow
from app.security import (
    create_session_token,
    hash_password,
    verify_password,
    verify_totp,
)
from app.services import ratelimit
from app.services.audit import audit, client_meta
from app.services.billing import generate_referral_code
from app.services.otp import issue_otp, verify_otp

router = APIRouter(tags=["auth"])


def _norm_phone(phone: str) -> str:
    p = phone.strip().replace(" ", "").replace("-", "")
    return p if p.startswith("+") else "+" + p


def _norm_identifier(value: str) -> str:
    """Email → lowercased; anything else → normalized phone."""
    value = value.strip()
    return value.lower() if "@" in value else _norm_phone(value)


def _find_user(db: Session, identifier: str) -> User | None:
    if "@" in identifier:
        return db.query(User).filter_by(email=identifier).first()
    return db.query(User).filter_by(phone=identifier).first()


def _render(request: Request, name: str, **ctx):
    from app.templating import templates

    return templates.TemplateResponse(request, f"public/{name}.html", {"user": None, **ctx})


def _start_session(db: Session, request: Request, user: User) -> RedirectResponse:
    sid = secrets.token_hex(24)
    meta = client_meta(request)
    db.add(UserSession(session_id=sid, user_id=user.id, **meta))
    user.last_login_at = utcnow()
    audit(db, "login", "session started", user_id=user.id, request=request, commit=False)
    db.commit()
    dest = "/admin" if user.is_admin else "/dashboard"
    # [SEC 08-01] open-redirect guard: only honor a local path for ?next=
    # (single leading slash, no scheme, no protocol-relative //host).
    _nxt = request.query_params.get("next") or ""
    if not (_nxt.startswith("/") and not _nxt.startswith("//")):
        _nxt = dest
    resp = RedirectResponse(_nxt, status_code=302)
    resp.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.id, user.role, sid),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )
    return resp


def _send_verification(db: Session, user: User) -> str:
    """Sends a registration code to the user's best channel; returns the
    destination it went to (email preferred — SMS needs a configured provider)."""
    if user.email:
        issue_otp(db, user.email, "register", channel="email")
        return user.email
    issue_otp(db, user.phone, "register", channel="sms")
    return user.phone


# --- registration ----------------------------------------------------------


@router.get("/register")
def register_form(request: Request, ref: str = ""):
    return _render(request, "register", ref=ref, error=None)


@router.post("/register")
def register(
    request: Request,
    email: str = Form(""),
    phone: str = Form(""),
    password: str = Form(...),
    name: str = Form(""),
    country: str = Form(""),
    timezone: str = Form("UTC"),
    language: str = Form("en"),
    referral_code: str = Form(""),
    accept_terms: str = Form(None),
    accept_risk: str = Form(None),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    phone = _norm_phone(phone) if phone.strip() else None
    ip = request.client.host if request.client else "?"
    if not ratelimit.allow("register", ip):
        return _render(request, "register", ref=referral_code,
                       error="Too many registrations from this address — try again later.")
    if not email and not phone:
        return _render(request, "register", ref=referral_code,
                       error="An email address is required (it's how we verify your account).")
    if email and "@" not in email:
        return _render(request, "register", ref=referral_code, error="That email address doesn't look valid.")
    if not accept_terms or not accept_risk:
        return _render(request, "register", ref=referral_code,
                       error="You must accept the Terms and the Risk Disclaimer.")
    if len(password) < 8:
        return _render(request, "register", ref=referral_code, error="Password must be at least 8 characters.")
    if email and db.query(User).filter_by(email=email).first():
        return _render(request, "register", ref=referral_code, error="This email is already registered.")
    if phone and db.query(User).filter_by(phone=phone).first():
        return _render(request, "register", ref=referral_code, error="This phone number is already registered.")

    referrer = db.query(User).filter_by(referral_code=referral_code).first() if referral_code else None
    user = User(
        email=email or None,
        phone=phone,
        password_hash=hash_password(password),
        name=name,
        country=country,
        timezone=timezone,
        language=language,
        referral_code=generate_referral_code(),
        referred_by_id=referrer.id if referrer else None,
    )
    db.add(user)
    db.flush()

    # Provision per-user defaults so every module works from first login.
    db.add(BotSettings(user_id=user.id))
    db.add(RiskLimits(user_id=user.id))
    db.add(TelegramSettings(user_id=user.id))
    db.add(NotificationPrefs(user_id=user.id))
    db.add(VPSStatus(user_id=user.id))
    for sym in DEFAULT_SYMBOLS:
        db.add(SymbolSetting(user_id=user.id, symbol=sym, enabled=sym in ("GOLD", "SILVER", "US100", "EURUSD")))
    meta = client_meta(request)
    for doc in ("terms", "risk"):
        db.add(ConsentLog(user_id=user.id, document=doc, ip=meta["ip"]))
    audit(db, "register", f"email={email or '-'} phone={phone or '-'}",
          user_id=user.id, request=request, commit=False)
    db.commit()

    dest = _send_verification(db, user)
    return RedirectResponse(f"/verify?dest={dest}", status_code=302)


@router.get("/verify")
def verify_form(request: Request, dest: str = "", phone: str = ""):
    # `phone` kept for old links/bookmarks.
    return _render(request, "verify", dest=dest or phone, error=None)


@router.post("/verify")
def verify(request: Request, dest: str = Form(...), code: str = Form(...), db: Session = Depends(get_db)):
    dest = _norm_identifier(dest)
    user = _find_user(db, dest)
    if user is None:
        return RedirectResponse("/register", status_code=302)
    if not verify_otp(db, dest, "register", code.strip()):
        return _render(request, "verify", dest=dest, error="Invalid or expired code.")
    if "@" in dest:
        user.email_verified = True
        audit(db, "email_verified", dest, user_id=user.id, request=request, commit=False)
    else:
        user.phone_verified = True
        audit(db, "phone_verified", dest, user_id=user.id, request=request, commit=False)
    db.commit()
    return _start_session(db, request, user)


@router.post("/verify/resend")
def verify_resend(dest: str = Form(...), db: Session = Depends(get_db)):
    dest = _norm_identifier(dest)
    if ratelimit.allow("otp_send", dest):
        issue_otp(db, dest, "register", channel="email" if "@" in dest else "sms")
    return RedirectResponse(f"/verify?dest={dest}", status_code=302)


# --- login -----------------------------------------------------------------


@router.get("/login")
def login_form(request: Request, next: str = "", user=Depends(optional_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return _render(request, "login", error=None, next=next)


@router.post("/login")
def login(
    request: Request,
    phone: str = Form(...),  # field carries email OR phone (kept name for compat)
    password: str = Form(...),
    totp: str = Form(""),
    db: Session = Depends(get_db),
):
    identifier = _norm_identifier(phone)
    ip = request.client.host if request.client else "?"
    if not ratelimit.allow("login", f"{identifier}:{ip}") or ratelimit.is_locked("login_fail", identifier):
        audit(db, "login_blocked", f"rate-limited id={identifier}", request=request)
        return _render(request, "login",
                       error="Too many attempts. This account is temporarily locked — try again in 15 minutes.",
                       next="")
    user = _find_user(db, identifier)
    if user is None or not verify_password(password, user.password_hash):
        ratelimit.record("login_fail", identifier)
        audit(db, "login_failed", f"id={identifier}", request=request)
        return _render(request, "login", error="Invalid email/phone or password.", next="")
    if user.is_banned:
        return _render(request, "login", error="This account is banned.", next="")
    if user.is_suspended:
        return _render(request, "login", error="This account is suspended — contact support.", next="")
    if not user.is_verified:
        _send_verification(db, user)
        return RedirectResponse(f"/verify?dest={user.primary_contact}", status_code=302)
    if user.totp_enabled:
        if not totp:
            return _render(request, "login", error=None, next="", needs_totp=True, phone=identifier)
        if not verify_totp(user.totp_secret, totp.strip()):
            ratelimit.record("login_fail", identifier)
            return _render(request, "login", error="Invalid 2FA code.", next="", needs_totp=True, phone=identifier)
    ratelimit.clear("login_fail", identifier)
    return _start_session(db, request, user)


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        from app.security import decode_session_token

        payload = decode_session_token(token)
        if payload:
            sess = db.query(UserSession).filter_by(session_id=payload.get("sid", "")).first()
            if sess:
                sess.revoked = True
                db.commit()
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# --- account recovery (forgot password) ------------------------------------


@router.get("/forgot")
def forgot_form(request: Request):
    return _render(request, "forgot", stage="identifier", error=None, dest="")


@router.post("/forgot")
def forgot_send(request: Request, dest: str = Form(...), db: Session = Depends(get_db)):
    dest = _norm_identifier(dest)
    ip = request.client.host if request.client else "?"
    if not ratelimit.allow("forgot", ip) or not ratelimit.allow("otp_send", dest):
        return _render(request, "forgot", stage="code", error=None, dest=dest)
    user = _find_user(db, dest)
    if user:
        # Recovery codes go to the address the user typed — email preferred.
        issue_otp(db, dest, "reset", channel="email" if "@" in dest else "sms")
    # Same response either way — don't leak which accounts exist.
    return _render(request, "forgot", stage="code", error=None, dest=dest)


@router.post("/forgot/reset")
def forgot_reset(
    request: Request,
    dest: str = Form(...),
    code: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    dest = _norm_identifier(dest)
    user = _find_user(db, dest)
    if user is None or not verify_otp(db, dest, "reset", code.strip()):
        return _render(request, "forgot", stage="code", error="Invalid or expired code.", dest=dest)
    if len(password) < 8:
        return _render(request, "forgot", stage="code", error="Password must be at least 8 characters.", dest=dest)
    user.password_hash = hash_password(password)
    if "@" in dest:
        user.email_verified = True  # proving the emailed code also confirms the address
    audit(db, "password_reset", f"via code to {dest}", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/login", status_code=302)
