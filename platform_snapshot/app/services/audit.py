from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.user import AuditLog


def client_meta(request: Request | None) -> dict:
    if request is None:
        return {"ip": "", "device": "", "country": ""}
    return {
        "ip": request.client.host if request.client else "",
        "device": request.headers.get("user-agent", "")[:250],
        "country": request.headers.get("cf-ipcountry", ""),
    }


def audit(
    db: Session,
    action: str,
    detail: str = "",
    user_id: int | None = None,
    actor: str = "user",
    request: Request | None = None,
    commit: bool = True,
) -> None:
    db.add(AuditLog(user_id=user_id, actor=actor, action=action, detail=detail, **client_meta(request)))
    if commit:
        db.commit()
