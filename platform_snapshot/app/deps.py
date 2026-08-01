"""Auth & tenancy dependencies. Session cookie → User; role gates for
admin/superadmin; API-key auth for /api/v1."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.platform import ApiKey
from app.models.user import User, UserSession, utcnow
from app.security import decode_session_token, hash_api_key

SESSION_COOKIE = "bb_session"


class LoginRequired(Exception):
    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def login_redirect_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(f"/login?next={exc.next_url}", status_code=302)


def _resolve_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = decode_session_token(token)
    if not payload:
        return None
    sess = db.query(UserSession).filter_by(session_id=payload.get("sid", ""), revoked=False).first()
    if sess is None:
        return None
    sess.last_seen_at = utcnow()
    user = db.get(User, int(payload["sub"]))
    if user is None or user.is_banned or user.is_suspended:
        return None
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    return _resolve_user(request, db)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _resolve_user(request, db)
    if user is None:
        raise LoginRequired(next_url=str(request.url.path))
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


def superadmin_user(user: User = Depends(current_user)) -> User:
    if user.role != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super-admin access required")
    return user


def api_user(request: Request, db: Session = Depends(get_db)) -> User:
    """API-key auth: Authorization: Bearer bb_xxx"""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")
    key = db.query(ApiKey).filter_by(key_hash=hash_api_key(auth[7:].strip()), active=True).first()
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    key.last_used_at = utcnow()
    user = db.get(User, key.user_id)
    if user is None or user.is_banned or user.is_suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account unavailable")
    db.commit()
    return user
