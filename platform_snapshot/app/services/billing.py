from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.billing import Coupon, Invoice, Plan, Subscription, WalletTransaction
from app.models.user import User, utcnow

REFERRAL_COMMISSION_PCT = 20.0


def active_subscription(db: Session, user_id: int) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id, Subscription.status == "active")
        .order_by(Subscription.id.desc())
        .first()
    )


def current_plan(db: Session, user_id: int) -> Plan | None:
    sub = active_subscription(db, user_id)
    if sub:
        return sub.plan
    return db.query(Plan).filter_by(slug="free").first()


def wallet_balance(db: Session, user_id: int) -> float:
    total = (
        db.query(func.sum(WalletTransaction.amount))
        .filter(WalletTransaction.user_id == user_id, WalletTransaction.status == "completed")
        .scalar()
    )
    return round(total or 0.0, 2)


def next_invoice_number(db: Session) -> str:
    count = db.query(func.count(Invoice.id)).scalar() or 0
    return f"INV-{utcnow():%Y%m}-{count + 1:05d}"


def apply_coupon(db: Session, code: str, amount: float) -> tuple[float, Coupon | None]:
    if not code:
        return amount, None
    coupon = db.query(Coupon).filter_by(code=code.upper(), active=True).first()
    if coupon is None:
        return amount, None
    if coupon.valid_until:
        expiry = coupon.valid_until
        if expiry.tzinfo is None:
            from datetime import timezone
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry < utcnow():
            return amount, None
    if coupon.max_uses and coupon.uses >= coupon.max_uses:
        return amount, None
    return round(amount * (1 - coupon.percent_off / 100), 2), coupon


def subscribe(db: Session, user: User, plan: Plan, coupon_code: str = "", months: int = 1) -> Subscription:
    """Charges the wallet, writes the invoice, activates the plan, and pays
    referral commission. Raises ValueError on insufficient wallet balance."""
    price, coupon = apply_coupon(db, coupon_code, plan.price_monthly * months)

    if price > 0:
        if wallet_balance(db, user.id) < price:
            raise ValueError("Insufficient wallet balance — deposit first.")
        db.add(WalletTransaction(user_id=user.id, kind="subscription", amount=-price,
                                 reference=f"{plan.slug} x{months}mo"))

    for sub in db.query(Subscription).filter_by(user_id=user.id, status="active").all():
        sub.status = "cancelled"

    sub = Subscription(
        user_id=user.id, plan_id=plan.id, status="active",
        expires_at=utcnow() + timedelta(days=30 * months),
        coupon_code=coupon.code if coupon else "",
    )
    db.add(sub)
    db.flush()

    from app.config import get_settings

    invoice = Invoice(
        number=next_invoice_number(db), user_id=user.id, subscription_id=sub.id,
        amount=price, vat_rate=get_settings().vat_rate if price > 0 else 0.0,
        status="paid" if price >= 0 else "unpaid",
        description=f"{plan.name} plan — {months} month(s)", paid_at=utcnow(),
    )
    db.add(invoice)
    if coupon:
        coupon.uses += 1

    if price > 0 and user.referred_by_id:
        commission = round(price * REFERRAL_COMMISSION_PCT / 100, 2)
        db.add(WalletTransaction(user_id=user.referred_by_id, kind="referral_bonus",
                                 amount=commission, reference=f"sub #{sub.id} of user #{user.id}"))

    db.commit()
    return sub


def generate_referral_code() -> str:
    return secrets.token_hex(4)
