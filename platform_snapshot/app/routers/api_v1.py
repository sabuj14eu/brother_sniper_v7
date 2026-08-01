"""REST API v1 — API-key authenticated (Authorization: Bearer bb_...).
Read endpoints for account/portfolio/trades/signals; heartbeat write
endpoints for the user's own executor/VPS agent. NO endpoint here can
place, modify, or dispatch a trade or signal (Iron Rule 1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import api_user
from app.models.trading import MT5Account, Signal, Trade, VPSStatus
from app.models.user import User, utcnow
from app.services import analytics

router = APIRouter(prefix="/api/v1", tags=["api"])


@router.get("/me")
def me(user: User = Depends(api_user)):
    return {"id": user.id, "phone": user.phone, "name": user.name, "role": user.role,
            "kyc_status": user.kyc_status}


@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db), user: User = Depends(api_user)):
    return analytics.portfolio_totals(db, user.id)


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(api_user)):
    report = analytics.full_report(db, user.id)
    report.pop("equity_curve", None)
    return report


@router.get("/trades")
def trades(status: str = "", limit: int = 50, db: Session = Depends(get_db), user: User = Depends(api_user)):
    q = db.query(Trade).filter_by(user_id=user.id)
    if status:
        q = q.filter_by(status=status)
    rows = q.order_by(Trade.open_time.desc()).limit(min(limit, 200)).all()
    return [
        {
            "id": t.id, "symbol": t.symbol, "direction": t.direction, "lots": t.lots,
            "entry": t.entry_price, "exit": t.exit_price, "sl": t.sl, "tp": t.tp,
            "status": t.status, "profit": t.net_profit, "session": t.session,
            "open_time": t.open_time.isoformat() if t.open_time else None,
            "close_time": t.close_time.isoformat() if t.close_time else None,
        }
        for t in rows
    ]


@router.get("/signals")
def signals(limit: int = 50, db: Session = Depends(get_db), user: User = Depends(api_user)):
    rows = db.query(Signal).order_by(Signal.created_at.desc()).limit(min(limit, 200)).all()
    return [
        {
            "signal_id": s.signal_id, "system": s.system, "symbol": s.symbol, "tf": s.tf,
            "direction": s.direction, "entry": s.entry, "sl": s.sl, "tp1": s.tp1, "tp2": s.tp2,
            "rr": s.rr, "grade": s.grade, "status": s.status, "confidence": s.confidence,
            "council": s.council_votes, "created_at": s.created_at.isoformat(),
        }
        for s in rows
    ]


# --- executor/VPS agent write-backs (own data only) ------------------------


class AccountHeartbeat(BaseModel):
    account_login: str
    balance: float = 0.0
    equity: float = 0.0
    free_margin: float = 0.0
    floating_pnl: float = 0.0
    status: str = Field("active", pattern="^(active|inactive|error)$")


@router.post("/heartbeat/account")
def account_heartbeat(hb: AccountHeartbeat, db: Session = Depends(get_db), user: User = Depends(api_user)):
    acc = db.query(MT5Account).filter_by(user_id=user.id, login=hb.account_login).first()
    if acc is None:
        raise HTTPException(404, "No such MT5 account for this user")
    acc.balance, acc.equity = hb.balance, hb.equity
    acc.free_margin, acc.floating_pnl = hb.free_margin, hb.floating_pnl
    acc.status = hb.status
    acc.last_heartbeat_at = utcnow()
    db.commit()
    return {"ok": True}


class VPSHeartbeat(BaseModel):
    cpu_pct: float = 0.0
    ram_pct: float = 0.0
    disk_pct: float = 0.0
    latency_ms: float = 0.0
    internet_ok: bool = True
    ea_running: bool = False
    mt5_running: bool = False
    # Executor monitor extras (all optional for older agents)
    mt5_version: str = ""
    ea_version: str = ""
    trade_latency_ms: float = 0.0
    queue_length: int = 0
    symbols_synced: bool = False
    auto_reconnect: bool = True


@router.post("/heartbeat/vps")
def vps_heartbeat(hb: VPSHeartbeat, db: Session = Depends(get_db), user: User = Depends(api_user)):
    vps = db.query(VPSStatus).filter_by(user_id=user.id).first()
    if vps is None:
        vps = VPSStatus(user_id=user.id)
        db.add(vps)
    for field in VPSHeartbeat.model_fields:
        setattr(vps, field, getattr(hb, field))
    vps.updated_at = utcnow()
    db.commit()
    return {"ok": True}


class TradeReport(BaseModel):
    """Executor reports fills/closes it made — the platform only records them."""

    account_login: str
    ticket: str
    symbol: str
    direction: str = Field(pattern="^(BUY|SELL)$")
    lots: float
    entry_price: float
    exit_price: float | None = None
    sl: float | None = None
    tp: float | None = None
    status: str = Field("open", pattern="^(open|pending|closed|cancelled)$")
    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    session: str = ""
    signal_id: str | None = None
    execution_ok: bool = True
    execution_error: str = ""
    execution_latency_ms: float = 0.0


@router.post("/heartbeat/trade")
def trade_report(tr: TradeReport, db: Session = Depends(get_db), user: User = Depends(api_user)):
    acc = db.query(MT5Account).filter_by(user_id=user.id, login=tr.account_login).first()
    if acc is None:
        raise HTTPException(404, "No such MT5 account for this user")
    sig = db.query(Signal).filter_by(signal_id=tr.signal_id).first() if tr.signal_id else None
    trade = db.query(Trade).filter_by(user_id=user.id, account_id=acc.id, ticket=tr.ticket).first()
    if trade is None:
        trade = Trade(user_id=user.id, account_id=acc.id, ticket=tr.ticket, symbol=tr.symbol,
                      direction=tr.direction, lots=tr.lots, entry_price=tr.entry_price)
        db.add(trade)
    trade.exit_price, trade.sl, trade.tp = tr.exit_price, tr.sl, tr.tp
    trade.profit, trade.commission, trade.swap = tr.profit, tr.commission, tr.swap
    trade.session = tr.session
    trade.signal_id = sig.id if sig else None
    if tr.status == "closed" and trade.status != "closed":
        trade.close_time = utcnow()
    trade.status = tr.status

    # Executor monitor: last order outcome + latency.
    vps = db.query(VPSStatus).filter_by(user_id=user.id).first()
    if vps:
        if tr.execution_ok:
            vps.last_order_ok_at = utcnow()
        else:
            vps.last_order_fail_at = utcnow()
            vps.last_order_fail_reason = tr.execution_error[:250]
        if tr.execution_latency_ms:
            vps.trade_latency_ms = tr.execution_latency_ms

    # Decision replay: link the MT5 execution to the signal timeline.
    if sig:
        from app.models.trading import SignalEvent

        db.add(SignalEvent(
            signal_id=sig.id, stage="mt5_execution",
            detail=f"{tr.status} ticket {tr.ticket} on {tr.account_login}"
                   + ("" if tr.execution_ok else f" FAILED: {tr.execution_error[:120]}"),
            payload={"ticket": tr.ticket, "lots": tr.lots, "entry": tr.entry_price,
                     "exit": tr.exit_price, "profit": tr.profit, "ok": tr.execution_ok,
                     "latency_ms": tr.execution_latency_ms},
        ))
    db.commit()
    return {"ok": True, "trade_id": trade.id}
