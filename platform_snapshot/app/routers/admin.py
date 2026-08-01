"""Admin back office: live dashboard, user management (suspend/ban/reset/
impersonate), broker management, finance, AI control panel, trading engine
monitor, server management, notifications centre, CMS, reports, compliance,
and super-admin tools (feature flags, system settings, maintenance mode)."""
from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import SESSION_COOKIE, admin_user, superadmin_user
from app.models.billing import Invoice, Plan, Subscription, WalletTransaction
from app.models.platform import (
    ApiKey,
    Broker,
    CMSPost,
    FeatureFlag,
    Notification,
    ServerNode,
    SystemSetting,
    Ticket,
    WebhookLog,
)
from app.models.trading import MarketBias, MT5Account, Signal, Trade
from app.models.user import AuditLog, ConsentLog, User, UserSession, utcnow
from app.security import create_session_token, hash_password
from app.services.audit import audit
from app.services.notify import notify_user
from app.templating import templates

router = APIRouter(prefix="/admin", tags=["admin"])


def _page(request: Request, name: str, user: User, active: str, **ctx):
    return templates.TemplateResponse(request, f"admin/{name}.html", {"user": user, "active": active, **ctx})


# --- dashboard -------------------------------------------------------------


@router.get("")
def admin_dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    now = utcnow()
    online_cutoff = now - timedelta(minutes=5)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stats = {
        "users": db.query(User).count(),
        "live_users": db.query(UserSession).filter(UserSession.last_seen_at >= online_cutoff,
                                                   UserSession.revoked.is_(False)).count(),
        "mt5_total": db.query(MT5Account).count(),
        "mt5_online": db.query(MT5Account).filter(MT5Account.last_heartbeat_at >= online_cutoff).count(),
        "trades_today": db.query(Trade).filter(Trade.open_time >= today).count(),
        "open_positions": db.query(Trade).filter_by(status="open").count(),
        "revenue": db.query(func.sum(Invoice.amount)).filter_by(status="paid").scalar() or 0.0,
        "subscribers": db.query(Subscription).filter_by(status="active").count(),
        "open_tickets": db.query(Ticket).filter_by(status="open").count(),
        "signals_today": db.query(Signal).filter(Signal.created_at >= today).count(),
    }
    nodes = db.query(ServerNode).all()
    recent_signals = db.query(Signal).order_by(Signal.created_at.desc()).limit(8).all()
    return _page(request, "dashboard", user, "dashboard", stats=stats, nodes=nodes,
                 recent_signals=recent_signals)


# --- user management -------------------------------------------------------


@router.get("/users")
def users_page(request: Request, q: str = "", page: int = 1, db: Session = Depends(get_db),
               user: User = Depends(admin_user)):
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter((User.phone.like(like)) | (User.name.like(like)) | (User.email.like(like)))
    total = query.count()
    rows = query.order_by(User.id.desc()).offset((page - 1) * 25).limit(25).all()
    return _page(request, "users", user, "users", rows=rows, q=q, page=page,
                 pages=max(1, -(-total // 25)), total=total)


@router.get("/users/{uid}")
def user_detail(uid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    target = db.get(User, uid)
    if target is None:
        raise HTTPException(404)
    accounts = db.query(MT5Account).filter_by(user_id=uid).all()
    subs = db.query(Subscription).filter_by(user_id=uid).order_by(Subscription.id.desc()).limit(5).all()
    logs = db.query(AuditLog).filter_by(user_id=uid).order_by(AuditLog.id.desc()).limit(30).all()
    plans = db.query(Plan).order_by(Plan.sort_order).all()
    return _page(request, "user_detail", user, "users", target=target, accounts=accounts,
                 subs=subs, logs=logs, plans=plans, msg=request.query_params.get("msg"))


@router.post("/users/{uid}/action")
def user_action(
    uid: int,
    request: Request,
    action: str = Form(...),
    value: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    target = db.get(User, uid)
    if target is None:
        raise HTTPException(404)
    if target.role == "superadmin" and user.role != "superadmin":
        raise HTTPException(403, "Cannot modify a super-admin")

    msg = "Done"
    if action == "suspend":
        target.is_suspended = True
    elif action == "unsuspend":
        target.is_suspended = False
    elif action == "ban":
        target.is_banned = True
    elif action == "unban":
        target.is_banned = False
    elif action == "reset_password":
        temp = secrets.token_urlsafe(8)
        target.password_hash = hash_password(temp)
        msg = f"Temporary password: {temp} (share it over a secure channel)"
    elif action == "reset_2fa":
        target.totp_enabled = False
        target.totp_secret = ""
    elif action == "assign_plan":
        plan = db.query(Plan).filter_by(slug=value).first()
        if plan is None:
            raise HTTPException(400, "Unknown plan")
        for s in db.query(Subscription).filter_by(user_id=uid, status="active").all():
            s.status = "cancelled"
        db.add(Subscription(user_id=uid, plan_id=plan.id, status="active",
                            expires_at=utcnow() + timedelta(days=30)))
    elif action == "kyc":
        target.kyc_status = value or "approved"
    else:
        raise HTTPException(400, "Unknown action")

    audit(db, "admin_user_action", f"{action} {value}".strip(), user_id=uid,
          actor=f"admin:{user.id}", request=request, commit=False)
    db.commit()
    return RedirectResponse(f"/admin/users/{uid}?msg={msg}", status_code=302)


@router.post("/users/{uid}/impersonate")
def impersonate(uid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    target = db.get(User, uid)
    if target is None:
        raise HTTPException(404)
    if target.is_admin:
        raise HTTPException(403, "Cannot impersonate another admin")
    sid = secrets.token_hex(24)
    db.add(UserSession(session_id=sid, user_id=target.id, device=f"impersonated by admin {user.id}"))
    audit(db, "admin_impersonate", f"admin {user.id} -> user {uid}", user_id=uid,
          actor=f"admin:{user.id}", request=request, commit=False)
    db.commit()
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(SESSION_COOKIE, create_session_token(target.id, target.role, sid),
                    httponly=True, samesite="lax", max_age=3600)
    return resp


# --- brokers ---------------------------------------------------------------


@router.get("/brokers")
def brokers_page(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    brokers = db.query(Broker).all()
    return _page(request, "brokers", user, "brokers", brokers=brokers)


@router.post("/brokers/save")
def broker_save(
    request: Request,
    name: str = Form(...),
    servers: str = Form(""),
    symbols: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    broker = db.query(Broker).filter_by(name=name).first()
    if broker is None:
        broker = Broker(name=name)
        db.add(broker)
    broker.servers = [s.strip() for s in servers.split(",") if s.strip()]
    broker.supported_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    audit(db, "admin_broker", f"save {name}", actor=f"admin:{user.id}", request=request, commit=False)
    db.commit()
    return RedirectResponse("/admin/brokers", status_code=302)


@router.post("/brokers/{bid}/toggle")
def broker_toggle(bid: int, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    broker = db.get(Broker, bid)
    if broker:
        broker.active = not broker.active
        db.commit()
    return RedirectResponse("/admin/brokers", status_code=302)


# --- finance ---------------------------------------------------------------


@router.get("/finance")
def finance_page(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    revenue = db.query(func.sum(Invoice.amount)).filter_by(status="paid").scalar() or 0.0
    monthly = (
        db.query(func.strftime("%Y-%m", Invoice.created_at).label("m"), func.sum(Invoice.amount))
        .filter_by(status="paid").group_by("m").order_by("m").all()
        if db.bind.dialect.name == "sqlite"
        else []
    )
    invoices = db.query(Invoice).order_by(Invoice.id.desc()).limit(30).all()
    pending_withdrawals = (
        db.query(WalletTransaction).filter_by(kind="withdrawal", status="pending")
        .order_by(WalletTransaction.id.desc()).all()
    )
    payouts = (
        db.query(WalletTransaction).filter_by(kind="referral_bonus")
        .order_by(WalletTransaction.id.desc()).limit(20).all()
    )
    subs_by_plan = (
        db.query(Plan.name, func.count(Subscription.id))
        .join(Subscription, Subscription.plan_id == Plan.id)
        .filter(Subscription.status == "active")
        .group_by(Plan.name).all()
    )
    return _page(request, "finance", user, "finance", revenue=revenue, monthly=monthly,
                 invoices=invoices, pending_withdrawals=pending_withdrawals, payouts=payouts,
                 subs_by_plan=subs_by_plan)


@router.post("/finance/withdrawals/{tx_id}/{decision}")
def withdrawal_decision(tx_id: int, decision: str, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(admin_user)):
    tx = db.get(WalletTransaction, tx_id)
    if tx is None or tx.kind != "withdrawal" or tx.status != "pending":
        raise HTTPException(404)
    if decision not in ("approve", "reject"):
        raise HTTPException(400)
    tx.status = "completed" if decision == "approve" else "rejected"
    audit(db, "admin_finance", f"withdrawal #{tx_id} {decision}", user_id=tx.user_id,
          actor=f"admin:{user.id}", request=request, commit=False)
    notify_user(db, tx.user_id, "system", f"Withdrawal {tx.status}",
                f"Your withdrawal of {abs(tx.amount):.2f} was {tx.status}.", commit=False)
    db.commit()
    return RedirectResponse("/admin/finance", status_code=302)


# --- AI control panel ------------------------------------------------------

AI_SETTINGS = [
    ("ai_council_members", "6", "Number of council members"),
    ("ai_approval_threshold", "5", "Approvals required to pass"),
    ("ai_risk_threshold", "0.7", "Max risk score allowed"),
    ("ai_news_weight", "0.2", "News weight in scoring"),
    ("ai_macro_weight", "0.3", "Macro weight in scoring"),
    ("ai_truth_layer", "on", "Truth layer enabled"),
    ("ai_min_confidence", "70", "Minimum signal confidence %"),
    ("ai_emergency_disable", "off", "EMERGENCY: disable all AI approvals"),
]


def _get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(SystemSetting).filter_by(key=key).first()
    return row.value if row else default


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(SystemSetting).filter_by(key=key).first()
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value


@router.get("/ai")
def ai_panel(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    values = {key: _get_setting(db, key, default) for key, default, _ in AI_SETTINGS}
    biases = db.query(MarketBias).all()
    return _page(request, "ai", user, "ai", settings_def=AI_SETTINGS, values=values, biases=biases)


@router.post("/ai/save")
async def ai_save(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    form = await request.form()
    changes = []
    for key, default, _ in AI_SETTINGS:
        new = str(form.get(key, default))
        old = _get_setting(db, key, default)
        if new != old:
            changes.append(f"{key}: {old} -> {new}")
            _set_setting(db, key, new)
    if changes:
        # These knobs shape live risk: full audit trail, no silent changes.
        audit(db, "admin_ai_change", "; ".join(changes), actor=f"admin:{user.id}", request=request, commit=False)
    db.commit()
    return RedirectResponse("/admin/ai", status_code=302)


# --- trading engine monitor ------------------------------------------------


@router.get("/engine")
def engine_page(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    counts = {
        status: db.query(Signal).filter_by(status=status).count()
        for status in ("pending", "approved", "rejected", "cancelled", "executed")
    }
    total = sum(counts.values())
    success = counts["approved"] + counts["executed"]
    queue = db.query(Signal).filter_by(status="pending").order_by(Signal.created_at).limit(20).all()
    recent = db.query(Signal).order_by(Signal.created_at.desc()).limit(30).all()
    webhook_logs = db.query(WebhookLog).order_by(WebhookLog.id.desc()).limit(20).all()
    return _page(request, "engine", user, "engine", counts=counts, total=total,
                 success_rate=round(success / total * 100, 1) if total else 0,
                 queue=queue, recent=recent, webhook_logs=webhook_logs)


# --- servers ---------------------------------------------------------------


@router.get("/servers")
def servers_page(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    nodes = db.query(ServerNode).order_by(ServerNode.role).all()
    return _page(request, "servers", user, "servers", nodes=nodes, now=utcnow())


@router.post("/servers/save")
def server_save(request: Request, name: str = Form(...), role: str = Form(...),
                db: Session = Depends(get_db), user: User = Depends(admin_user)):
    node = db.query(ServerNode).filter_by(name=name).first()
    if node is None:
        db.add(ServerNode(name=name, role=role))
    else:
        node.role = role
    db.commit()
    return RedirectResponse("/admin/servers", status_code=302)


# --- notifications centre --------------------------------------------------


@router.get("/notify")
def notify_page(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _page(request, "notify", user, "notify", sent=request.query_params.get("sent"))


@router.post("/notify/broadcast")
def notify_broadcast(
    request: Request,
    title: str = Form(...),
    body: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    count = 0
    for target in db.query(User).filter_by(is_banned=False).all():
        notify_user(db, target.id, "system", title, body, telegram_event="system_alert", commit=False)
        count += 1
    audit(db, "admin_broadcast", f"'{title}' to {count} users", actor=f"admin:{user.id}",
          request=request, commit=False)
    db.commit()
    return RedirectResponse(f"/admin/notify?sent={count}", status_code=302)


# --- CMS -------------------------------------------------------------------

CMS_TYPES = ["blog", "news", "tutorial", "faq", "documentation", "changelog", "announcement", "banner"]


@router.get("/cms")
def cms_page(request: Request, type: str = "", db: Session = Depends(get_db), user: User = Depends(admin_user)):
    q = db.query(CMSPost)
    if type:
        q = q.filter_by(type=type)
    posts = q.order_by(CMSPost.id.desc()).limit(100).all()
    return _page(request, "cms", user, "cms", posts=posts, types=CMS_TYPES, current_type=type)


@router.post("/cms/save")
def cms_save(
    request: Request,
    post_id: int = Form(0),
    type: str = Form(...),
    title: str = Form(...),
    slug: str = Form(""),
    body: str = Form(""),
    published: str = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    if type not in CMS_TYPES:
        raise HTTPException(400, "Unknown content type")
    post = db.get(CMSPost, post_id) if post_id else None
    if post is None:
        post = CMSPost(type=type, title=title, author_id=user.id,
                       slug=slug or title.lower().replace(" ", "-")[:200])
        db.add(post)
    post.type, post.title, post.body = type, title, body
    if slug:
        post.slug = slug
    post.published = bool(published)
    post.updated_at = utcnow()
    db.commit()
    return RedirectResponse(f"/admin/cms?type={type}", status_code=302)


@router.post("/cms/{post_id}/delete")
def cms_delete(post_id: int, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    post = db.get(CMSPost, post_id)
    if post:
        db.delete(post)
        db.commit()
    return RedirectResponse("/admin/cms", status_code=302)


# --- reports ---------------------------------------------------------------


@router.get("/reports")
def reports_page(request: Request, window: str = "monthly", db: Session = Depends(get_db),
                 user: User = Depends(admin_user)):
    days = {"daily": 1, "weekly": 7, "monthly": 30, "yearly": 365}.get(window, 30)
    cutoff = utcnow() - timedelta(days=days)
    trades = db.query(Trade).filter(Trade.status == "closed", Trade.close_time >= cutoff).all()
    profit = round(sum(t.profit + t.commission + t.swap for t in trades), 2)
    wins = sum(1 for t in trades if t.profit + t.commission + t.swap > 0)
    revenue = db.query(func.sum(Invoice.amount)).filter(Invoice.status == "paid",
                                                        Invoice.created_at >= cutoff).scalar() or 0.0
    new_users = db.query(User).filter(User.created_at >= cutoff).count()
    signals = db.query(Signal).filter(Signal.created_at >= cutoff).count()
    return _page(request, "reports", user, "reports", window=window, profit=profit,
                 trades=len(trades), wins=wins, revenue=revenue, new_users=new_users, signals=signals)


# --- compliance ------------------------------------------------------------


@router.get("/compliance")
def compliance_page(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    consents = db.query(ConsentLog).order_by(ConsentLog.id.desc()).limit(50).all()
    counts = dict(db.query(ConsentLog.document, func.count()).group_by(ConsentLog.document).all())
    legal_posts = db.query(CMSPost).filter(CMSPost.slug.like("legal-%")).all()
    return _page(request, "compliance", user, "compliance", consents=consents, counts=counts,
                 legal_posts=legal_posts)


# --- super admin -----------------------------------------------------------


@router.get("/system")
def system_page(request: Request, db: Session = Depends(get_db), user: User = Depends(superadmin_user)):
    flags = db.query(FeatureFlag).all()
    settings_rows = db.query(SystemSetting).filter(~SystemSetting.key.like("ai_%")).all()
    maintenance = _get_setting(db, "maintenance_mode", "off")
    errors = db.query(WebhookLog).filter(WebhookLog.status_code >= 400).order_by(WebhookLog.id.desc()).limit(20).all()
    api_keys = db.query(ApiKey).filter_by(active=True).count()
    return _page(request, "system", user, "system", flags=flags, settings_rows=settings_rows,
                 maintenance=maintenance, errors=errors, api_keys=api_keys)


@router.post("/system/flags/save")
def flag_save(request: Request, key: str = Form(...), description: str = Form(""),
              db: Session = Depends(get_db), user: User = Depends(superadmin_user)):
    flag = db.query(FeatureFlag).filter_by(key=key).first()
    if flag is None:
        db.add(FeatureFlag(key=key, description=description, enabled=False))
        db.commit()
    return RedirectResponse("/admin/system", status_code=302)


@router.post("/system/flags/{fid}/toggle")
def flag_toggle(fid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(superadmin_user)):
    flag = db.get(FeatureFlag, fid)
    if flag:
        flag.enabled = not flag.enabled
        audit(db, "admin_flag", f"{flag.key} -> {flag.enabled}", actor=f"admin:{user.id}",
              request=request, commit=False)
        db.commit()
    return RedirectResponse("/admin/system", status_code=302)


@router.post("/system/maintenance")
def maintenance_toggle(request: Request, db: Session = Depends(get_db), user: User = Depends(superadmin_user)):
    current = _get_setting(db, "maintenance_mode", "off")
    _set_setting(db, "maintenance_mode", "on" if current == "off" else "off")
    audit(db, "admin_maintenance", f"maintenance -> {'on' if current == 'off' else 'off'}",
          actor=f"admin:{user.id}", request=request, commit=False)
    db.commit()
    return RedirectResponse("/admin/system", status_code=302)


@router.post("/system/settings/save")
def system_setting_save(request: Request, key: str = Form(...), value: str = Form(""),
                        db: Session = Depends(get_db), user: User = Depends(superadmin_user)):
    _set_setting(db, key, value)
    audit(db, "admin_system_setting", key, actor=f"admin:{user.id}", request=request, commit=False)
    db.commit()
    return RedirectResponse("/admin/system", status_code=302)
