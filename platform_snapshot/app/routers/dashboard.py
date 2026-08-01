"""User dashboard — everything on one page: account status, portfolio,
trading stats, performance graphs, AI panel, latest signals, economic news,
notifications."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import current_user
from app.models.platform import Notification
from app.models.trading import EconomicEvent, MarketBias, MT5Account, Signal, Trade, VPSStatus
from app.models.user import User, utcnow
from app.services import analytics
from app.services.billing import current_plan
from app.templating import templates

router = APIRouter(tags=["dashboard"])

BIAS_SYMBOLS = ["GOLD", "SILVER", "US100", "EURUSD", "BTC", "ETH", "DXY", "OIL"]


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.models.platform import TelegramSettings

    report = analytics.full_report(db, user.id)
    portfolio = analytics.portfolio_totals(db, user.id)
    open_trades = db.query(Trade).filter_by(user_id=user.id, status="open").order_by(Trade.open_time.desc()).all()
    pending_orders = db.query(Trade).filter_by(user_id=user.id, status="pending").all()
    signals = db.query(Signal).order_by(Signal.created_at.desc()).limit(8).all()
    biases = {b.symbol: b for b in db.query(MarketBias).all()}
    news = (
        db.query(EconomicEvent)
        .filter(EconomicEvent.event_time >= utcnow())
        .order_by(EconomicEvent.event_time)
        .limit(6)
        .all()
    )
    notifications = (
        db.query(Notification).filter_by(user_id=user.id).order_by(Notification.id.desc()).limit(10).all()
    )
    unread = db.query(Notification).filter_by(user_id=user.id, read=False).count()
    vps = db.query(VPSStatus).filter_by(user_id=user.id).first()
    tg = db.query(TelegramSettings).filter_by(user_id=user.id).first()
    accounts = db.query(MT5Account).filter_by(user_id=user.id).all()
    plan = current_plan(db, user.id)

    return templates.TemplateResponse(
        request,
        "dash/dashboard.html",
        {
            "user": user,
            "active": "dashboard",
            "report": report,
            "portfolio": portfolio,
            "open_trades": open_trades,
            "pending_orders": pending_orders,
            "signals": signals,
            "bias_symbols": BIAS_SYMBOLS,
            "biases": biases,
            "news": news,
            "notifications": notifications,
            "unread": unread,
            "vps": vps,
            "telegram_ok": bool(tg and tg.verified),
            "accounts": accounts,
            "plan": plan,
            "now": utcnow(),
        },
    )


@router.post("/notifications/read-all")
def mark_notifications_read(db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.query(Notification).filter_by(user_id=user.id, read=False).update({"read": True})
    db.commit()
    return RedirectResponse("/dashboard", status_code=302)
