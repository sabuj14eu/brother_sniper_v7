"""Background sweeper — the platform's watchdog. Runs every minute:

1. Bot-offline detection: active MT5 accounts whose heartbeat went stale get
   one 'bot_offline' notification per outage (Iron Rule 5: silence is the
   signal, not a green endpoint).
2. Risk enforcement: daily-loss limit and max-consecutive-losses breaches
   engage the emergency stop automatically, audited and notified. Executors
   poll /api/v1 for the stop flag.
3. Subscriptions: expiry reminders 3 days out; auto-renew from wallet at
   expiry (one retry per sweep while past_due); downgrade to expired when
   renewal cannot be paid.

Called from the app lifespan task; also callable directly (tests, cron).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.billing import Plan, Subscription
from app.models.trading import MT5Account, RiskLimits, Trade
from app.models.user import AuditLog, User, utcnow
from app.services.notify import notify_user

log = logging.getLogger("brotherbot.sweeper")

HEARTBEAT_STALE_SECONDS = 600


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def sweep_offline_bots(db: Session) -> int:
    now = utcnow()
    flagged = 0
    for acc in db.query(MT5Account).filter(MT5Account.status == "active").all():
        stale = acc.last_heartbeat_at is None or (
            (now - _aware(acc.last_heartbeat_at)).total_seconds() > HEARTBEAT_STALE_SECONDS
        )
        if stale and not acc.offline_notified and acc.last_heartbeat_at is not None:
            acc.offline_notified = True
            flagged += 1
            notify_user(db, acc.user_id, "bot_offline", f"Bot offline: {acc.account_name}",
                        "No heartbeat for 10+ minutes. Check your VPS/executor.",
                        telegram_event="system_alert", commit=False)
        elif not stale and acc.offline_notified:
            acc.offline_notified = False
            notify_user(db, acc.user_id, "system", f"Bot back online: {acc.account_name}",
                        "Heartbeats resumed.", telegram_event="system_alert", commit=False)
    db.commit()
    return flagged


def sweep_risk(db: Session) -> int:
    """Engage emergency stop on daily-loss or consecutive-loss breaches."""
    stopped = 0
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    for limits in db.query(RiskLimits).filter(RiskLimits.emergency_stop.is_(False)).all():
        accounts = db.query(MT5Account).filter_by(user_id=limits.user_id).all()
        baseline = sum(a.balance for a in accounts)
        if baseline <= 0:
            continue
        closed_today = (
            db.query(Trade)
            .filter(Trade.user_id == limits.user_id, Trade.status == "closed", Trade.close_time >= today)
            .order_by(Trade.close_time)
            .all()
        )
        day_pnl = sum(t.net_profit for t in closed_today)
        streak = 0
        for t in reversed(closed_today):
            if t.net_profit < 0:
                streak += 1
            else:
                break

        reason = None
        if day_pnl <= -(limits.daily_loss_limit / 100 * baseline):
            reason = f"daily loss limit hit ({day_pnl:.2f} vs {limits.daily_loss_limit}% of {baseline:.0f})"
        elif limits.max_consecutive_losses and streak >= limits.max_consecutive_losses:
            reason = f"{streak} consecutive losses (limit {limits.max_consecutive_losses})"

        if reason:
            limits.emergency_stop = True
            limits.emergency_stop_at = utcnow()
            stopped += 1
            db.add(AuditLog(user_id=limits.user_id, actor="system", action="risk_change",
                            detail=f"AUTO EMERGENCY STOP: {reason}"))
            notify_user(db, limits.user_id, "margin_warning", "🛑 Auto emergency stop",
                        f"Trading halted automatically: {reason}. Review and resume from the Risk Manager.",
                        telegram_event="system_alert", commit=False)
    db.commit()
    return stopped


def sweep_subscriptions(db: Session) -> int:
    now = utcnow()
    touched = 0
    for sub in db.query(Subscription).filter(Subscription.status == "active").all():
        if not sub.expires_at:
            continue
        expires = _aware(sub.expires_at)
        if timedelta(0) < expires - now <= timedelta(days=3):
            already = (
                db.query(AuditLog)
                .filter(AuditLog.user_id == sub.user_id, AuditLog.action == "subscription_reminder",
                        AuditLog.created_at >= now - timedelta(days=1))
                .first()
            )
            if not already:
                db.add(AuditLog(user_id=sub.user_id, actor="system", action="subscription_reminder",
                                detail=f"expires {expires:%Y-%m-%d}"))
                notify_user(db, sub.user_id, "subscription_expiry", "Subscription expiring soon",
                            f"Your plan renews/expires on {expires:%Y-%m-%d}. Top up your wallet to avoid downgrade.",
                            telegram_event="subscription_reminder", commit=False)
                touched += 1
        elif expires <= now:
            user = db.get(User, sub.user_id)
            plan = db.get(Plan, sub.plan_id)
            renewed = False
            if sub.auto_renew and user and plan and plan.price_monthly > 0:
                from app.services.billing import subscribe

                try:
                    db.commit()  # flush reminder state before nested commit inside subscribe()
                    subscribe(db, user, plan)
                    renewed = True
                    notify_user(db, sub.user_id, "system", "Subscription renewed",
                                f"{plan.name} renewed from your wallet.", commit=False)
                except ValueError:
                    pass  # insufficient balance — falls through to expiry
            if not renewed:
                sub.status = "expired"
                notify_user(db, sub.user_id, "subscription_expiry", "Subscription expired",
                            "Auto-renewal failed (insufficient wallet balance). You are on the Free plan.",
                            telegram_event="subscription_reminder", commit=False)
            touched += 1
    db.commit()
    return touched


def run_sweep(db: Session) -> dict:
    result = {
        "offline_flagged": sweep_offline_bots(db),
        "auto_stops": sweep_risk(db),
        "subscriptions": sweep_subscriptions(db),
    }
    if any(result.values()):
        log.info("sweep: %s", result)
    return result
