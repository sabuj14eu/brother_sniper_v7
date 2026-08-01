"""Support tickets, downloads, API keys & webhooks, audit log viewer,
security (2FA, sessions, password), user profile."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import current_user
from app.models.platform import ApiKey, CMSPost, Ticket, TicketMessage, WebhookLog
from app.models.user import AuditLog, User, UserSession, utcnow
from app.security import (
    generate_api_key,
    generate_totp_secret,
    hash_password,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.services.audit import audit
from app.templating import templates

router = APIRouter(tags=["account"])


def _page(request: Request, name: str, user: User, active: str, **ctx):
    return templates.TemplateResponse(request, f"dash/{name}.html", {"user": user, "active": active, **ctx})


# --- support ---------------------------------------------------------------


@router.get("/support")
def support_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    tickets = db.query(Ticket).filter_by(user_id=user.id).order_by(Ticket.updated_at.desc()).all()
    kb = db.query(CMSPost).filter(CMSPost.type.in_(["faq", "tutorial", "documentation"]), CMSPost.published).limit(10).all()
    return _page(request, "support", user, "support", tickets=tickets, kb=kb)


@router.post("/support/new")
def ticket_new(
    request: Request,
    subject: str = Form(...),
    category: str = Form("support"),
    body: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    ticket = Ticket(user_id=user.id, subject=subject, category=category)
    db.add(ticket)
    db.flush()
    db.add(TicketMessage(ticket_id=ticket.id, author_id=user.id, body=body))
    db.commit()
    return RedirectResponse(f"/support/{ticket.id}", status_code=302)


@router.get("/support/{ticket_id}")
def ticket_view(ticket_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or (ticket.user_id != user.id and not user.is_admin):
        raise HTTPException(404)
    return _page(request, "ticket", user, "support", ticket=ticket)


@router.post("/support/{ticket_id}/reply")
def ticket_reply(ticket_id: int, body: str = Form(...), db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or (ticket.user_id != user.id and not user.is_admin):
        raise HTTPException(404)
    db.add(TicketMessage(ticket_id=ticket.id, author_id=user.id, is_staff=user.is_admin, body=body))
    ticket.status = "answered" if user.is_admin else "open"
    ticket.updated_at = utcnow()
    db.commit()
    return RedirectResponse(f"/support/{ticket_id}", status_code=302)


# --- downloads -------------------------------------------------------------


@router.get("/downloads/app")
def downloads_page(request: Request, user: User = Depends(current_user)):
    return _page(request, "downloads", user, "downloads")


# --- API keys & webhooks ---------------------------------------------------


@router.get("/api-access")
def api_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    keys = db.query(ApiKey).filter_by(user_id=user.id).order_by(ApiKey.id.desc()).all()
    logs = (
        db.query(WebhookLog).filter_by(user_id=user.id)
        .order_by(WebhookLog.id.desc()).limit(30).all()
    )
    return _page(request, "api", user, "api", keys=keys, logs=logs,
                 new_key=request.query_params.get("new_key"))


@router.post("/api-access/keys/new")
def api_key_new(request: Request, label: str = Form(""), permissions: str = Form("read"),
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    full, prefix, key_hash = generate_api_key()
    db.add(ApiKey(user_id=user.id, label=label or "API key", prefix=prefix, key_hash=key_hash,
                  permissions=["read", "write"] if permissions == "write" else ["read"]))
    audit(db, "api_key_created", label, user_id=user.id, request=request, commit=False)
    db.commit()
    # Shown once — only the hash is stored.
    return RedirectResponse(f"/api-access?new_key={full}", status_code=302)


@router.post("/api-access/keys/{key_id}/revoke")
def api_key_revoke(key_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    key = db.get(ApiKey, key_id)
    if key and key.user_id == user.id:
        key.active = False
        audit(db, "api_key_revoked", key.label, user_id=user.id, request=request, commit=False)
        db.commit()
    return RedirectResponse("/api-access", status_code=302)


# --- audit logs ------------------------------------------------------------


@router.get("/audit")
def audit_page(request: Request, page: int = 1, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(AuditLog).filter_by(user_id=user.id).order_by(AuditLog.id.desc())
    total = q.count()
    logs = q.offset((page - 1) * 50).limit(50).all()
    return _page(request, "audit", user, "audit", logs=logs, page=page, pages=max(1, -(-total // 50)))


# --- security --------------------------------------------------------------


@router.get("/security")
def security_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sessions = (
        db.query(UserSession).filter_by(user_id=user.id, revoked=False)
        .order_by(UserSession.last_seen_at.desc()).all()
    )
    logins = (
        db.query(AuditLog)
        .filter(AuditLog.user_id == user.id, AuditLog.action.in_(["login", "login_failed"]))
        .order_by(AuditLog.id.desc()).limit(20).all()
    )
    pending_secret = request.query_params.get("totp_setup", "")
    return _page(request, "security", user, "security", sessions=sessions, logins=logins,
                 pending_secret=pending_secret,
                 pending_uri=totp_uri(pending_secret, user.primary_contact) if pending_secret else "",
                 msg=request.query_params.get("msg"))


@router.post("/security/password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not verify_password(current_password, user.password_hash):
        return RedirectResponse("/security?msg=Current password is wrong", status_code=302)
    if len(new_password) < 8:
        return RedirectResponse("/security?msg=New password too short (min 8)", status_code=302)
    user.password_hash = hash_password(new_password)
    audit(db, "password_change", "", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/security?msg=Password changed", status_code=302)


@router.post("/security/2fa/start")
def totp_start(user: User = Depends(current_user)):
    return RedirectResponse(f"/security?totp_setup={generate_totp_secret()}", status_code=302)


@router.post("/security/2fa/confirm")
def totp_confirm(
    request: Request,
    secret: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not verify_totp(secret, code.strip()):
        return RedirectResponse(f"/security?totp_setup={secret}&msg=Wrong code, try again", status_code=302)
    user.totp_secret = secret
    user.totp_enabled = True
    audit(db, "2fa_enabled", "TOTP", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/security?msg=2FA enabled", status_code=302)


@router.post("/security/2fa/disable")
def totp_disable(request: Request, code: str = Form(...), db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    if not user.totp_enabled or not verify_totp(user.totp_secret, code.strip()):
        return RedirectResponse("/security?msg=Wrong 2FA code", status_code=302)
    user.totp_enabled = False
    user.totp_secret = ""
    audit(db, "2fa_disabled", "TOTP", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/security?msg=2FA disabled", status_code=302)


@router.post("/security/sessions/{sid}/revoke")
def revoke_session(sid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sess = db.get(UserSession, sid)
    if sess and sess.user_id == user.id:
        sess.revoked = True
        audit(db, "session_revoked", sess.device[:80], user_id=user.id, request=request, commit=False)
        db.commit()
    return RedirectResponse("/security", status_code=302)


# --- profile ---------------------------------------------------------------


@router.get("/profile")
def profile_page(request: Request, user: User = Depends(current_user)):
    return _page(request, "profile", user, "profile", saved=request.query_params.get("saved"))


@router.post("/profile/save")
def profile_save(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    country: str = Form(""),
    timezone: str = Form("UTC"),
    language: str = Form("en"),
    currency: str = Form("USD"),
    broker: str = Form(""),
    trading_experience: str = Form(""),
    risk_profile: str = Form("medium"),
    photo_url: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    user.name = name
    new_email = email.strip().lower() or None
    if new_email != user.email:
        if new_email and db.query(User).filter(User.email == new_email, User.id != user.id).first():
            return RedirectResponse("/profile?saved=0", status_code=302)
        user.email = new_email
        user.email_verified = False  # changed address must be re-verified
        if new_email:
            from app.services.otp import issue_otp

            issue_otp(db, new_email, "register", channel="email")
    user.country = country
    user.timezone = timezone
    user.language = language
    user.currency = currency
    user.broker = broker
    user.trading_experience = trading_experience
    user.risk_profile = risk_profile
    user.photo_url = photo_url
    audit(db, "setting_change", "profile updated", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/profile?saved=1", status_code=302)
