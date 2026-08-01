"""Subscription plans, wallet (deposit/withdrawal/history), invoices,
affiliate program (link, clicks, signups, commission, leaderboard)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import current_user
from app.models.billing import Invoice, Plan, ReferralClick, Subscription, WalletTransaction
from app.models.user import User
from app.services.audit import audit
from app.services.billing import active_subscription, current_plan, subscribe, wallet_balance
from app.templating import templates

router = APIRouter(tags=["billing"])


def _page(request: Request, name: str, user: User, active: str, **ctx):
    return templates.TemplateResponse(request, f"dash/{name}.html", {"user": user, "active": active, **ctx})


@router.get("/subscription")
def subscription_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    plans = db.query(Plan).filter_by(is_public=True).order_by(Plan.sort_order).all()
    sub = active_subscription(db, user.id)
    invoices = db.query(Invoice).filter_by(user_id=user.id).order_by(Invoice.id.desc()).limit(20).all()
    return _page(request, "subscription", user, "subscription", plans=plans, sub=sub,
                 plan=current_plan(db, user.id), invoices=invoices,
                 balance=wallet_balance(db, user.id), error=request.query_params.get("error"))


@router.post("/subscription/subscribe")
def do_subscribe(
    request: Request,
    plan_slug: str = Form(...),
    coupon: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    plan = db.query(Plan).filter_by(slug=plan_slug).first()
    if plan is None:
        return RedirectResponse("/subscription?error=Unknown plan", status_code=302)
    try:
        subscribe(db, user, plan, coupon_code=coupon)
    except ValueError as exc:
        return RedirectResponse(f"/subscription?error={exc}", status_code=302)
    audit(db, "subscription", f"subscribed to {plan.slug}", user_id=user.id, request=request)
    return RedirectResponse("/subscription", status_code=302)


@router.post("/subscription/cancel")
def cancel_subscription(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = active_subscription(db, user.id)
    if sub:
        sub.auto_renew = False
        audit(db, "subscription", "auto-renew disabled", user_id=user.id, request=request, commit=False)
        db.commit()
    return RedirectResponse("/subscription", status_code=302)


@router.get("/invoices/{invoice_id}")
def invoice_page(invoice_id: int, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    """Printable VAT invoice (browser print → PDF)."""
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or (invoice.user_id != user.id and not user.is_admin):
        from fastapi import HTTPException

        raise HTTPException(404)
    buyer = db.get(User, invoice.user_id)
    return _page(request, "invoice", user, "subscription", invoice=invoice, buyer=buyer,
                 company=get_settings())


# --- wallet ----------------------------------------------------------------


@router.get("/wallet")
def wallet_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.services.payments import available_providers

    txs = (
        db.query(WalletTransaction).filter_by(user_id=user.id)
        .order_by(WalletTransaction.id.desc()).limit(50).all()
    )
    return _page(request, "wallet", user, "wallet", balance=wallet_balance(db, user.id), txs=txs,
                 providers=available_providers(), error=request.query_params.get("error"))


@router.post("/wallet/deposit")
def wallet_deposit(request: Request, amount: float = Form(...), provider: str = Form("manual"),
                   db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.services.payments import create_checkout

    if amount <= 0:
        return RedirectResponse("/wallet?error=Amount must be positive", status_code=302)
    try:
        checkout_url = create_checkout(provider, amount, user.id)
    except ValueError as exc:
        return RedirectResponse(f"/wallet?error={exc}", status_code=302)
    # [SEC 08-01] C2: deposits are PENDING unless the explicit dev-sandbox flag is
    # set. Previously any non-production env auto-completed a client-supplied
    # amount -> a user could self-credit unlimited spendable balance. Real money
    # in production must be completed by an admin/payment-webhook, never here.
    _s = get_settings()
    status = "completed" if (_s.wallet_autocredit_dev and not _s.is_production) else "pending"
    db.add(WalletTransaction(user_id=user.id, kind="deposit", amount=round(amount, 2), status=status,
                             reference=f"{provider} deposit"))
    audit(db, "wallet", f"deposit {amount} via {provider}", user_id=user.id, request=request, commit=False)
    db.commit()
    if checkout_url:
        return RedirectResponse(checkout_url, status_code=302)
    return RedirectResponse("/wallet", status_code=302)


@router.post("/wallet/withdraw")
def wallet_withdraw(request: Request, amount: float = Form(...), db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    if amount <= 0:
        return RedirectResponse("/wallet?error=Amount must be positive", status_code=302)
    if wallet_balance(db, user.id) < amount:
        return RedirectResponse("/wallet?error=Insufficient balance", status_code=302)
    db.add(WalletTransaction(user_id=user.id, kind="withdrawal", amount=-round(amount, 2), status="pending",
                             reference="withdrawal request"))
    audit(db, "wallet", f"withdrawal request {amount}", user_id=user.id, request=request, commit=False)
    db.commit()
    return RedirectResponse("/wallet", status_code=302)


# --- affiliate -------------------------------------------------------------


@router.get("/affiliate")
def affiliate_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    clicks = db.query(ReferralClick).filter_by(referral_code=user.referral_code).count()
    signups = db.query(User).filter_by(referred_by_id=user.id).count()
    commission = (
        db.query(func.sum(WalletTransaction.amount))
        .filter_by(user_id=user.id, kind="referral_bonus", status="completed").scalar() or 0.0
    )
    # Leaderboard: top referrers by signups (anonymised).
    referrer_counts = (
        db.query(User.referred_by_id, func.count().label("n"))
        .filter(User.referred_by_id.isnot(None))
        .group_by(User.referred_by_id)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )
    board = []
    for uid, n in referrer_counts:
        ref_user = db.get(User, uid)
        if ref_user:
            label = ref_user.name or f"user-{ref_user.referral_code[:4]}"
            board.append({"name": label, "signups": n, "me": uid == user.id})

    link = f"{get_settings().base_url}/?ref={user.referral_code}"
    return _page(request, "affiliate", user, "affiliate", link=link, clicks=clicks, signups=signups,
                 commission=round(commission, 2), board=board)
