"""Bot settings, symbol management, risk manager (with one-click emergency
stop). Every change is audited — risk is never widened silently (Iron Rule 3)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import current_user
from app.models.trading import BotSettings, RiskLimits, SymbolSetting
from app.models.user import User, utcnow
from app.services.audit import audit
from app.services.notify import notify_user
from app.templating import templates

router = APIRouter(tags=["bot-settings"])


def _page(request: Request, name: str, user: User, active: str, **ctx):
    return templates.TemplateResponse(request, f"dash/{name}.html", {"user": user, "active": active, **ctx})


@router.get("/bot")
def bot_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    settings = db.query(BotSettings).filter_by(user_id=user.id).first()
    if settings is None:
        settings = BotSettings(user_id=user.id)
        db.add(settings)
        db.commit()
    return _page(request, "bot", user, "bot", s=settings)


@router.post("/bot/save")
async def bot_save(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    s = db.query(BotSettings).filter_by(user_id=user.id).first() or BotSettings(user_id=user.id)
    db.add(s)

    changes = []

    def set_field(field, value):
        old = getattr(s, field)
        if old != value:
            changes.append(f"{field}: {old} -> {value}")
            setattr(s, field, value)

    set_field("trading_mode", form.get("trading_mode", "demo"))
    set_field("risk_level", form.get("risk_level", "low"))
    set_field("lot_size", float(form.get("lot_size", 0.01) or 0.01))
    set_field("max_trades", int(form.get("max_trades", 5) or 5))
    set_field("max_daily_loss", float(form.get("max_daily_loss", 3) or 3))
    set_field("max_daily_profit", float(form.get("max_daily_profit", 0) or 0))
    set_field("max_drawdown", float(form.get("max_drawdown", 10) or 10))
    set_field("max_open_positions", int(form.get("max_open_positions", 3) or 3))
    set_field("max_slippage", float(form.get("max_slippage", 2) or 2))
    set_field("sessions", {
        "asia": "session_asia" in form,
        "london": "session_london" in form,
        "newyork": "session_newyork" in form,
        "weekend_crypto": "session_weekend" in form,
    })
    for flag in ("news_filter", "spread_filter", "auto_close_friday", "trailing_stop", "break_even", "partial_close"):
        set_field(flag, flag in form)

    if changes:
        audit(db, "setting_change", "bot: " + "; ".join(changes), user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/bot", status_code=302)


# --- symbols ---------------------------------------------------------------


@router.get("/symbols")
def symbols_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    symbols = db.query(SymbolSetting).filter_by(user_id=user.id).order_by(SymbolSetting.is_custom, SymbolSetting.id).all()
    return _page(request, "symbols", user, "symbols", symbols=symbols)


@router.post("/symbols/save")
async def symbols_save(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    for row in db.query(SymbolSetting).filter_by(user_id=user.id).all():
        row.enabled = f"sym_{row.id}" in form
    audit(db, "setting_change", "symbol toggles", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/symbols", status_code=302)


@router.post("/symbols/add")
def symbols_add(request: Request, symbol: str = Form(...), db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    sym = symbol.strip().upper()[:20]
    if sym and not db.query(SymbolSetting).filter_by(user_id=user.id, symbol=sym).first():
        db.add(SymbolSetting(user_id=user.id, symbol=sym, is_custom=True))
        audit(db, "setting_change", f"custom symbol {sym}", user_id=user.id, request=request, commit=False)
        db.commit()
    return RedirectResponse("/symbols", status_code=302)


@router.post("/symbols/{sid}/delete")
def symbols_delete(sid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.get(SymbolSetting, sid)
    if row and row.user_id == user.id and row.is_custom:
        db.delete(row)
        db.commit()
    return RedirectResponse("/symbols", status_code=302)


# --- risk manager ----------------------------------------------------------


@router.get("/risk")
def risk_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    limits = db.query(RiskLimits).filter_by(user_id=user.id).first()
    if limits is None:
        limits = RiskLimits(user_id=user.id)
        db.add(limits)
        db.commit()
    return _page(request, "risk", user, "risk", r=limits)


@router.post("/risk/save")
def risk_save(
    request: Request,
    daily_loss_limit: float = Form(...),
    weekly_loss_limit: float = Form(...),
    monthly_loss_limit: float = Form(...),
    max_consecutive_losses: int = Form(...),
    max_exposure: float = Form(...),
    max_lots: float = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    r = db.query(RiskLimits).filter_by(user_id=user.id).first() or RiskLimits(user_id=user.id)
    db.add(r)
    changes = []
    for field, value in [
        ("daily_loss_limit", daily_loss_limit), ("weekly_loss_limit", weekly_loss_limit),
        ("monthly_loss_limit", monthly_loss_limit), ("max_consecutive_losses", max_consecutive_losses),
        ("max_exposure", max_exposure), ("max_lots", max_lots),
    ]:
        old = getattr(r, field)
        if old != value:
            changes.append(f"{field}: {old} -> {value}")
            setattr(r, field, value)
    if changes:
        audit(db, "risk_change", "; ".join(changes), user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/risk", status_code=302)


@router.post("/risk/emergency-stop")
def emergency_stop(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.query(RiskLimits).filter_by(user_id=user.id).first() or RiskLimits(user_id=user.id)
    db.add(r)
    r.emergency_stop = True
    r.emergency_stop_at = utcnow()
    audit(db, "risk_change", "EMERGENCY STOP engaged", user_id=user.id, request=request, commit=False)
    notify_user(db, user.id, "system", "Emergency stop engaged",
                "All trading halted. Re-enable from the Risk Manager.", commit=False)
    db.commit()
    return RedirectResponse("/risk", status_code=302)


@router.post("/risk/resume")
def risk_resume(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.query(RiskLimits).filter_by(user_id=user.id).first()
    if r:
        r.emergency_stop = False
        audit(db, "risk_change", "emergency stop released", user_id=user.id, request=request, commit=False)
        db.commit()
    return RedirectResponse("/risk", status_code=302)
