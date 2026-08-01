"""Trading analytics computed from closed trades: win rate, profit factor,
expectancy, drawdown, equity/balance curves, per-symbol/session/day breakdowns.
Everything derives from the Trade table — nothing is remembered, only measured."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.trading import MT5Account, Trade


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def closed_trades(db: Session, user_id: int) -> list[Trade]:
    return (
        db.query(Trade)
        .filter(Trade.user_id == user_id, Trade.status == "closed")
        .order_by(Trade.close_time.asc())
        .all()
    )


def core_stats(trades: list[Trade]) -> dict:
    wins = [t for t in trades if t.net_profit > 0]
    losses = [t for t in trades if t.net_profit <= 0]
    gross_win = sum(t.net_profit for t in wins)
    gross_loss = abs(sum(t.net_profit for t in losses))
    n = len(trades)
    win_rate = (len(wins) / n * 100) if n else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss else (float("inf") if gross_win else 0.0)
    expectancy = (sum(t.net_profit for t in trades) / n) if n else 0.0
    rrs = [t.rr for t in trades if t.rr is not None]
    return {
        "count": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "expectancy": round(expectancy, 2),
        "avg_rr": round(sum(rrs) / len(rrs), 2) if rrs else None,
        "total_profit": round(sum(t.net_profit for t in trades), 2),
    }


def equity_curve(trades: list[Trade], starting_balance: float = 0.0) -> list[dict]:
    points, bal = [], starting_balance
    for t in trades:
        bal += t.net_profit
        points.append({"t": _aware(t.close_time).strftime("%Y-%m-%d %H:%M"), "balance": round(bal, 2)})
    return points


def max_drawdown(trades: list[Trade], starting_balance: float = 0.0) -> float:
    peak, bal, mdd = starting_balance, starting_balance, 0.0
    for t in trades:
        bal += t.net_profit
        peak = max(peak, bal)
        if peak > 0:
            mdd = max(mdd, (peak - bal) / peak * 100)
    return round(mdd, 2)


def profit_in_window(trades: list[Trade], days: int) -> float:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return round(sum(t.net_profit for t in trades if t.close_time and _aware(t.close_time) >= cutoff), 2)


def bucket_profit(trades: list[Trade], key_fn) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for t in trades:
        out[key_fn(t)] += t.net_profit
    return {k: round(v, 2) for k, v in sorted(out.items(), key=lambda kv: kv[1], reverse=True)}


def monthly_returns(trades: list[Trade]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for t in trades:
        if t.close_time:
            out[_aware(t.close_time).strftime("%Y-%m")] += t.net_profit
    return {k: round(v, 2) for k, v in sorted(out.items())}


def consecutive_losses(trades: list[Trade]) -> int:
    worst = run = 0
    for t in trades:
        run = run + 1 if t.net_profit < 0 else 0
        worst = max(worst, run)
    return worst


def portfolio_totals(db: Session, user_id: int) -> dict:
    accounts = db.query(MT5Account).filter_by(user_id=user_id).all()
    return {
        "balance": round(sum(a.balance for a in accounts), 2),
        "equity": round(sum(a.equity for a in accounts), 2),
        "free_margin": round(sum(a.free_margin for a in accounts), 2),
        "floating_pnl": round(sum(a.floating_pnl for a in accounts), 2),
        "accounts": len(accounts),
        "online": sum(1 for a in accounts if a.is_online),
    }


def full_report(db: Session, user_id: int) -> dict:
    trades = closed_trades(db, user_id)
    stats = core_stats(trades)
    by_symbol = bucket_profit(trades, lambda t: t.symbol)
    by_session = bucket_profit(trades, lambda t: t.session or "unknown")
    by_weekday = bucket_profit(trades, lambda t: _aware(t.close_time).strftime("%A") if t.close_time else "?")
    return {
        **stats,
        "today_profit": profit_in_window(trades, 1),
        "weekly_profit": profit_in_window(trades, 7),
        "monthly_profit": profit_in_window(trades, 30),
        "max_drawdown": max_drawdown(trades),
        "consecutive_losses": consecutive_losses(trades),
        "equity_curve": equity_curve(trades),
        "monthly_returns": monthly_returns(trades),
        "by_symbol": by_symbol,
        "by_session": by_session,
        "by_weekday": by_weekday,
        "best_symbol": next(iter(by_symbol), None),
        "worst_symbol": next(reversed(by_symbol), None) if by_symbol else None,
        "best_session": next(iter(by_session), None),
        "worst_session": next(reversed(by_session), None) if by_session else None,
        "best_day": next(iter(by_weekday), None),
        "worst_day": next(reversed(by_weekday), None) if by_weekday else None,
    }
