"""MT5 account management (multiple accounts per user, plan-capped),
Telegram connection, SMS preferences, VPS monitor, trade copier."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import current_user
from app.models.platform import Broker, NotificationPrefs, TelegramSettings
from app.models.trading import CopierLink, MT5Account, VPSStatus
from app.models.user import User, utcnow
from app.security import decrypt_secret, encrypt_secret
from app.services.audit import audit
from app.services.billing import current_plan
from app.services.notify import send_telegram
from app.templating import templates

router = APIRouter(tags=["accounts"])


def _page(request: Request, name: str, user: User, active: str, **ctx):
    return templates.TemplateResponse(request, f"dash/{name}.html", {"user": user, "active": active, **ctx})


def _own_account(db: Session, user: User, account_id: int) -> MT5Account:
    acc = db.get(MT5Account, account_id)
    if acc is None or acc.user_id != user.id:
        raise HTTPException(404, "Account not found")
    return acc


# --- MT5 -------------------------------------------------------------------


@router.get("/mt5")
def mt5_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    accounts = db.query(MT5Account).filter_by(user_id=user.id).all()
    brokers = db.query(Broker).filter_by(active=True).all()
    plan = current_plan(db, user.id)
    return _page(request, "mt5", user, "mt5", accounts=accounts, brokers=brokers, plan=plan,
                 error=request.query_params.get("error"))


@router.post("/mt5/add")
def mt5_add(
    request: Request,
    broker: str = Form(...),
    server: str = Form(...),
    login: str = Form(...),
    password: str = Form(...),
    password_kind: str = Form("investor"),
    account_name: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    plan = current_plan(db, user.id)
    count = db.query(MT5Account).filter_by(user_id=user.id).count()
    if plan and count >= plan.max_mt5_accounts:
        return RedirectResponse(
            f"/mt5?error=Your {plan.name} plan allows {plan.max_mt5_accounts} MT5 account(s). Upgrade to add more.",
            status_code=302,
        )
    acc = MT5Account(
        user_id=user.id, broker=broker, server=server, login=login,
        password_enc=encrypt_secret(password), password_kind=password_kind,
        account_name=account_name or f"{broker} {login}",
    )
    db.add(acc)
    audit(db, "mt5_connect", f"add {broker}/{login}", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/mt5", status_code=302)


@router.post("/mt5/{account_id}/{action}")
def mt5_action(
    account_id: int,
    action: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    acc = _own_account(db, user, account_id)
    if action == "activate":
        acc.status = "active"
    elif action == "deactivate":
        acc.status = "inactive"
    elif action == "reconnect":
        # Real connectivity is proven only by executor heartbeats (Iron Rule 5);
        # this clears the error state and asks the agent to retry.
        acc.status = "active"
        acc.last_heartbeat_at = None
    elif action == "test":
        # Mark a pending test; the executor agent reports back via heartbeat.
        acc.status = "active" if acc.password_enc else "error"
    elif action == "delete":
        db.delete(acc)
    else:
        raise HTTPException(400, "Unknown action")
    audit(db, "mt5_connect", f"{action} account #{account_id}", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/mt5", status_code=302)


@router.get("/mt5/{account_id}/logs")
def mt5_logs(account_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    acc = _own_account(db, user, account_id)
    from app.models.user import AuditLog

    logs = (
        db.query(AuditLog)
        .filter(AuditLog.user_id == user.id, AuditLog.action == "mt5_connect")
        .order_by(AuditLog.id.desc())
        .limit(100)
        .all()
    )
    return _page(request, "mt5_logs", user, "mt5", account=acc, logs=logs)


# --- Telegram --------------------------------------------------------------


@router.get("/telegram")
def telegram_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    tg = db.query(TelegramSettings).filter_by(user_id=user.id).first()
    return _page(request, "telegram", user, "telegram", tg=tg,
                 msg=request.query_params.get("msg"))


@router.post("/telegram/save")
def telegram_save(
    request: Request,
    bot_token: str = Form(""),
    chat_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    tg = db.query(TelegramSettings).filter_by(user_id=user.id).first()
    if tg is None:
        tg = TelegramSettings(user_id=user.id)
        db.add(tg)
    if bot_token:
        tg.bot_token_enc = encrypt_secret(bot_token.strip())
        tg.verified = False
    tg.chat_id = chat_id.strip()
    audit(db, "setting_change", "telegram settings", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/telegram", status_code=302)


@router.post("/telegram/events")
async def telegram_events(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.models.platform import TELEGRAM_EVENTS

    form = await request.form()
    tg = db.query(TelegramSettings).filter_by(user_id=user.id).first()
    if tg:
        tg.events = {e: (e in form) for e in TELEGRAM_EVENTS}
        db.commit()
    return RedirectResponse("/telegram", status_code=302)


@router.post("/telegram/test")
def telegram_test(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    tg = db.query(TelegramSettings).filter_by(user_id=user.id).first()
    if not tg or not tg.bot_token_enc or not tg.chat_id:
        return RedirectResponse("/telegram?msg=Set bot token and chat ID first.", status_code=302)
    ok = send_telegram(decrypt_secret(tg.bot_token_enc), tg.chat_id, "✅ Brother Bot connected. Test message OK.")
    tg.verified = ok
    user.telegram_connected = ok
    db.commit()
    return RedirectResponse(f"/telegram?msg={'Test message sent ✅' if ok else 'Send failed — check token/chat ID.'}",
                            status_code=302)


# --- SMS preferences -------------------------------------------------------


@router.get("/sms")
def sms_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    prefs = db.query(NotificationPrefs).filter_by(user_id=user.id).first()
    return _page(request, "sms", user, "sms", prefs=prefs)


@router.post("/sms/save")
async def sms_save(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    prefs = db.query(NotificationPrefs).filter_by(user_id=user.id).first()
    if prefs is None:
        prefs = NotificationPrefs(user_id=user.id)
        db.add(prefs)
    for field in ("sms_enabled", "sms_trade_alerts", "sms_security_alerts",
                  "sms_login_alerts", "sms_subscription_reminders"):
        setattr(prefs, field, field in form)
    audit(db, "setting_change", "sms preferences", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/sms", status_code=302)


# --- VPS monitor -----------------------------------------------------------


@router.get("/vps")
def vps_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    vps = db.query(VPSStatus).filter_by(user_id=user.id).first()
    return _page(request, "vps", user, "vps", vps=vps, now=utcnow())


@router.post("/vps/restart")
def vps_restart(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    # Queues a restart request for the user's agent; recorded, never silent.
    audit(db, "vps_restart_requested", "", user_id=user.id, request=request)
    return RedirectResponse("/vps", status_code=302)


# --- Trade copier ----------------------------------------------------------


@router.get("/copier")
def copier_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    accounts = db.query(MT5Account).filter_by(user_id=user.id).all()
    links = db.query(CopierLink).filter_by(user_id=user.id).all()
    acc_map = {a.id: a for a in accounts}
    return _page(request, "copier", user, "copier", accounts=accounts, links=links, acc_map=acc_map)


@router.post("/copier/add")
def copier_add(
    request: Request,
    master_account_id: int = Form(...),
    slave_account_id: int = Form(...),
    copy_ratio: float = Form(1.0),
    risk_multiplier: float = Form(1.0),
    reverse_copy: str = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _own_account(db, user, master_account_id)
    _own_account(db, user, slave_account_id)
    if master_account_id == slave_account_id:
        raise HTTPException(400, "Master and slave must differ")
    db.add(CopierLink(
        user_id=user.id, master_account_id=master_account_id, slave_account_id=slave_account_id,
        copy_ratio=copy_ratio, risk_multiplier=risk_multiplier, reverse_copy=bool(reverse_copy),
    ))
    audit(db, "setting_change", f"copier link {master_account_id}->{slave_account_id}",
          user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/copier", status_code=302)


@router.post("/copier/{link_id}/delete")
def copier_delete(link_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    link = db.get(CopierLink, link_id)
    if link and link.user_id == user.id:
        db.delete(link)
        audit(db, "setting_change", f"copier link #{link_id} removed", user_id=user.id, request=request, commit=False)
        db.commit()
    return RedirectResponse("/copier", status_code=302)
