"""Signal history (council votes, AI score, reasons), trade journal
(notes/emotion/screenshots), analytics page."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import current_user
from app.models.trading import Signal, SignalEvent, Trade
from app.models.user import User
from app.services import analytics
from app.templating import templates

router = APIRouter(tags=["trading"])
PAGE_SIZE = 25


def _page(request: Request, name: str, user: User, active: str, **ctx):
    return templates.TemplateResponse(request, f"dash/{name}.html", {"user": user, "active": active, **ctx})


@router.get("/signals")
def signals_page(
    request: Request,
    page: int = 1,
    status: str = "",
    symbol: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = db.query(Signal)
    if status:
        q = q.filter(Signal.status == status)
    if symbol:
        q = q.filter(Signal.symbol == symbol.upper())
    total = q.count()
    rows = q.order_by(Signal.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return _page(request, "signals", user, "signals", signals=rows, page=page, total=total,
                 pages=max(1, -(-total // PAGE_SIZE)), status=status, symbol=symbol)


@router.get("/signals/{sig_id}")
def signal_detail(sig_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sig = db.get(Signal, sig_id)
    if sig is None:
        raise HTTPException(404)
    events = db.query(SignalEvent).filter_by(signal_id=sig.id).order_by(SignalEvent.created_at).all()
    import json

    raw_alert = json.dumps(sig.raw_payload, indent=2) if sig.raw_payload else ""
    return _page(request, "signal_detail", user, "signals", sig=sig, events=events, raw_alert=raw_alert)


@router.get("/journal")
def journal_page(request: Request, page: int = 1, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(Trade).filter_by(user_id=user.id)
    total = q.count()
    trades = q.order_by(Trade.open_time.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return _page(request, "journal", user, "journal", trades=trades, page=page, total=total,
                 pages=max(1, -(-total // PAGE_SIZE)))


@router.get("/journal/{trade_id}")
def journal_detail(trade_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    trade = db.get(Trade, trade_id)
    if trade is None or trade.user_id != user.id:
        raise HTTPException(404)
    return _page(request, "journal_detail", user, "journal", t=trade)


@router.post("/journal/{trade_id}/notes")
def journal_notes(
    trade_id: int,
    notes: str = Form(""),
    emotion: str = Form(""),
    screenshot_url: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    trade = db.get(Trade, trade_id)
    if trade is None or trade.user_id != user.id:
        raise HTTPException(404)
    trade.notes = notes
    trade.emotion = emotion
    trade.screenshot_url = screenshot_url
    db.commit()
    return RedirectResponse(f"/journal/{trade_id}", status_code=302)


@router.get("/analytics")
def analytics_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    report = analytics.full_report(db, user.id)
    return _page(request, "analytics", user, "analytics", report=report)
