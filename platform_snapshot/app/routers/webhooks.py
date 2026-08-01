"""Inbound read-only mirror from the v18 brain (and market context feeds).

The brain POSTs a copy of every council decision here for display, journaling
and notifications. APPEND-ONLY contract (Iron Rule 2): the raw payload is
stored verbatim; known fields are indexed, unknown fields pass through.
Nothing received here is ever forwarded to an executor."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.platform import WebhookLog
from app.models.trading import EconomicEvent, MarketBias, Signal, SignalEvent
from app.models.user import utcnow
from app.services.notify import format_signal_message, notify_user

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _check_secret(secret: str | None) -> None:
    expected = get_settings().brain_webhook_secret
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(401, "Bad webhook secret")


@router.post("/brain/signal")
async def brain_signal(
    request: Request,
    db: Session = Depends(get_db),
    x_brain_secret: str | None = Header(None),
):
    _check_secret(x_brain_secret)
    payload = await request.json()

    def num(key):
        try:
            return float(payload[key]) if payload.get(key) not in (None, "") else None
        except (TypeError, ValueError):
            return None

    signal_id = str(payload.get("signal_id", ""))
    if not signal_id:
        raise HTTPException(422, "signal_id required")

    sig = db.query(Signal).filter_by(signal_id=signal_id).first()
    created = sig is None
    if created:
        sig = Signal(signal_id=signal_id)
        db.add(sig)
    prev_status = None if created else sig.status

    sig.system = str(payload.get("system", sig.system or "v18"))
    sig.symbol = str(payload.get("symbol", sig.symbol or "")).upper()
    sig.tf = str(payload.get("tf", sig.tf or ""))
    sig.direction = str(payload.get("direction", payload.get("signal", sig.direction or ""))).upper()
    sig.entry, sig.sl = num("entry"), num("sl")
    sig.tp1 = num("tp1") if payload.get("tp1") is not None else num("tp")
    sig.tp2, sig.rr = num("tp2"), num("rr")
    sig.grade = str(payload.get("grade", sig.grade or ""))
    sig.ai_score = num("ai_score")
    sig.confidence = num("confidence")
    if isinstance(payload.get("council"), dict):
        sig.council_votes = payload["council"]
    if payload.get("status") in ("pending", "approved", "rejected", "cancelled", "executed"):
        sig.status = payload["status"]
    sig.reason = str(payload.get("reason", sig.reason or ""))
    sig.market_structure = str(payload.get("market_structure", sig.market_structure or ""))
    if payload.get("outcome") in ("win", "loss", "be", "open"):
        sig.outcome = payload["outcome"]
    sig.raw_payload = payload  # verbatim, append-only

    db.add(WebhookLog(source="brain", endpoint="/webhooks/brain/signal", payload=payload))
    db.flush()

    # Decision-replay timeline (append-only).
    if created:
        db.add(SignalEvent(signal_id=sig.id, stage="alert_received",
                           detail=f"{sig.system} alert for {sig.symbol} {sig.direction}", payload=payload))
        db.add(SignalEvent(
            signal_id=sig.id, stage="council_decision",
            detail=f"{sig.status} — council {sig.council_votes.get('approve', '?')}/"
                   f"{sig.council_votes.get('total', '?')}; {sig.reason[:200]}",
            payload={"council": sig.council_votes, "ai_score": sig.ai_score,
                     "confidence": sig.confidence, "grade": sig.grade,
                     "macro": payload.get("macro"), "truth_layer": payload.get("truth_layer")},
        ))
    elif prev_status != sig.status:
        db.add(SignalEvent(signal_id=sig.id, stage="status_change",
                           detail=f"{prev_status} → {sig.status}", payload=payload))
    if payload.get("outcome") in ("win", "loss", "be"):
        db.add(SignalEvent(signal_id=sig.id, stage="outcome", detail=payload["outcome"]))
    db.commit()

    # Fan out Telegram alerts to users who opted in, on approved signals only.
    if created and sig.status == "approved":
        from app.models.user import User

        event = "buy" if sig.direction == "BUY" else "sell"
        recipients = db.query(User).filter_by(is_banned=False, is_suspended=False).all()
        for u in recipients:
            notify_user(db, u.id, "trade_opened", f"{sig.direction} {sig.symbol}",
                        format_signal_message(sig), telegram_event=event, commit=False)
        db.add(SignalEvent(signal_id=sig.id, stage="telegram_sent",
                           detail=f"alert fan-out to {len(recipients)} users"))
        db.commit()

    return {"ok": True, "signal_id": signal_id, "stored": True}


@router.post("/brain/bias")
async def brain_bias(request: Request, db: Session = Depends(get_db),
                     x_brain_secret: str | None = Header(None)):
    _check_secret(x_brain_secret)
    payload = await request.json()
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        symbol = str(item.get("symbol", "")).upper()
        if not symbol:
            continue
        bias = db.query(MarketBias).filter_by(symbol=symbol).first()
        if bias is None:
            bias = MarketBias(symbol=symbol)
            db.add(bias)
        bias.trend = str(item.get("trend", bias.trend))
        bias.confidence = float(item.get("confidence", bias.confidence) or 0)
        bias.council_decision = str(item.get("council_decision", bias.council_decision))
        bias.risk_level = str(item.get("risk_level", bias.risk_level))
        bias.updated_at = utcnow()
    db.commit()
    return {"ok": True, "updated": len(items)}


@router.post("/brain/news")
async def brain_news(request: Request, db: Session = Depends(get_db),
                     x_brain_secret: str | None = Header(None)):
    _check_secret(x_brain_secret)
    payload = await request.json()
    items = payload if isinstance(payload, list) else [payload]
    stored = 0
    for item in items:
        title = str(item.get("title", ""))
        when = item.get("event_time")
        if not title or not when:
            continue
        from datetime import datetime

        try:
            event_time = datetime.fromisoformat(when)
        except ValueError:
            continue
        exists = db.query(EconomicEvent).filter_by(title=title, event_time=event_time).first()
        if exists:
            continue
        db.add(EconomicEvent(
            title=title,
            impact=str(item.get("impact", "medium")),
            currency=str(item.get("currency", "USD")),
            affected_symbols=item.get("affected_symbols", []),
            event_time=event_time,
        ))
        stored += 1
    db.commit()
    return {"ok": True, "stored": stored}
