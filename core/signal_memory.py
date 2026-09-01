"""
signal_memory.py — Brother Sniper Bot v7+ Signal Memory & Analytics
═══════════════════════════════════════════════════════════════════════════
Step 1 of World-Class Brain:
  Collects ALL signals from TradingView v17 (BUY/SELL/INFO/WARN/SCALP)
  Stores structured events in RAM with future-price tracking
  Provides live counters per symbol/session
  Enables Step 2 data analysis for real-performance brain building

Author: Claude + Shyam
"""
import time
import json
import threading
import logging
from collections import deque, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import os

log = logging.getLogger()  # use root logger so it shows in gunicorn logs

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════
MAX_SIGNALS_PER_SYMBOL = 100      # Keep last 100 signals per symbol
MEMORY_WINDOW_MINUTES  = 120      # 2h window (London + NY overlap)
FUTURE_CHECK_POINTS    = [5, 15, 30, 60]  # Minutes to check future price
PERSIST_FILE           = "/home/shyam/brother_sniper_v7/signal_memory.json"
PERSIST_INTERVAL_SEC   = 30      # Save every 5 min (backup only)

# Session windows (UTC hours)
SESSION_ASIAN    = (22, 7)   # 22:00 UTC to 07:00 UTC
SESSION_LONDON   = (7, 13)   # 07:00 UTC to 13:00 UTC
SESSION_OVERLAP  = (13, 16)  # 13:00 UTC to 16:00 UTC (London+NY)
SESSION_NY       = (13, 22)  # 13:00 UTC to 22:00 UTC

# ═══════════════════════════════════════════════════════════════════════════
# STATE (RAM)
# ═══════════════════════════════════════════════════════════════════════════
_lock = threading.RLock()
_signals: Dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_SIGNALS_PER_SYMBOL))
_last_save = 0

# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _get_session(dt: datetime) -> str:
    """Return session name based on UTC time."""
    h = dt.hour
    if 13 <= h < 16:
        return "OVERLAP"    # London + NY overlap - best session
    elif 7 <= h < 13:
        return "LONDON"
    elif 13 <= h < 22:
        return "NEW_YORK"
    else:
        return "ASIAN"

def _normalize_symbol(sym: str) -> str:
    """Strip exchange prefix (e.g. TVC:SILVER -> SILVER)."""
    if not sym:
        return ""
    sym = sym.upper().strip()
    if ":" in sym:
        sym = sym.split(":")[-1]
    # Normalize common aliases
    alias = {"XAUUSD": "GOLD", "XAGUSD": "SILVER", "BTCUSD": "BITCOIN", "ETHUSD": "ETHEREUM"}
    return alias.get(sym, sym)


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API — Record incoming signal
# ═══════════════════════════════════════════════════════════════════════════
def record_signal(payload: dict, raw_entry_price: Optional[float] = None) -> dict:
    """
    Records a signal event with full structured data.

    Returns the structured event that was stored (for debug/logging).
    """
    now = _now_utc()
    symbol = _normalize_symbol(payload.get("symbol", ""))
    if not symbol:
        return {}

    # Extract fields from v17 / v7 payloads
    system    = payload.get("system", "UNKNOWN")          # BSv17 / BSv16 / etc
    signal    = (payload.get("signal") or payload.get("direction") or payload.get("action") or "").upper()
    sigtype   = payload.get("type", "").upper()           # MICRO / SCALP / INFO / WARN / ALL_TF_BULL / LIQ_SWEEP etc
    entry     = float(payload.get("entry") or raw_entry_price or 0)
    sl        = float(payload.get("sl") or 0)
    tp        = float(payload.get("tp") or payload.get("tp2") or payload.get("tp1") or 0)
    score     = int(payload.get("score") or 0)
    rsi       = int(payload.get("rsi") or 0)
    adx       = int(payload.get("adx") or 0)
    session   = payload.get("session") or _get_session(now)
    zone      = payload.get("zone", "")
    action    = payload.get("action", "")
    # [C2 2026-09-01] Pine emits htf_align (verified in source); htf_agree
    # never arrives — reading it alone stored False on every record.
    htf_agree = bool(payload.get("htf_align", payload.get("htf_agree", False)))

    # Determine signal category for analytics
    category = _categorize(signal, sigtype)

    event = {
        "ts":         now.isoformat(),
        "ts_unix":    now.timestamp(),
        "symbol":     symbol,
        "system":     system,
        "signal":     signal,        # BUY / SELL / INFO / WARN / ""
        "type":       sigtype,       # MICRO / SCALP / ALL_TF_BULL etc
        "category":   category,      # TRADE_BUY / TRADE_SELL / BIAS_BULL / BIAS_BEAR / WARN / NEUTRAL
        "entry":      entry,
        "sl":         sl,
        "tp":         tp,
        "score":      score,
        "rsi":        rsi,
        "adx":        adx,
        "session":    session,
        "zone":       zone,
        "action":     action,
        "htf_agree":  htf_agree,
        # Future price tracking - filled in later
        "future_5m":  None,
        "future_15m": None,
        "future_30m": None,
        "future_60m": None,
        # Outcome - filled when trade closes
        "traded":     False,
        "trade_win":  None,
        "trade_pnl":  None,
    }

    with _lock:
        _signals[symbol].append(event)
        _maybe_persist()

    log.info(f"[MEM] Stored {symbol} {category} score={score} session={session}")
    return event


def _categorize(signal: str, sigtype: str) -> str:
    """Convert raw signal/type into clean category."""
    s = (signal or "").upper()
    t = (sigtype or "").upper()

    if s == "BUY":
        return "TRADE_BUY" if t in ("MICRO", "SWING", "") else f"SCALP_BUY" if t == "SCALP" else "TRADE_BUY"
    if s == "SELL":
        return "TRADE_SELL" if t in ("MICRO", "SWING", "") else f"SCALP_SELL" if t == "SCALP" else "TRADE_SELL"
    if s == "INFO":
        if "BULL" in t:
            return "BIAS_BULL"
        if "BEAR" in t:
            return "BIAS_BEAR"
        return "INFO"
    if s == "WARN":
        if "BULL" in t or "BUY" in t:
            return "WARN_BULL"     # Warning that bullish move may be trap
        if "BEAR" in t or "SELL" in t:
            return "WARN_BEAR"
        return "WARN"
    return "NEUTRAL"


# ═══════════════════════════════════════════════════════════════════════════
# FUTURE PRICE TRACKING
# ═══════════════════════════════════════════════════════════════════════════
def update_future_prices(symbol: str, current_price: float):
    """
    Called periodically (e.g. every minute) with latest price.
    Fills in future_5m / future_15m / future_30m / future_60m for past signals
    where the relevant time has now passed.
    """
    if not symbol or current_price <= 0:
        return
    symbol = _normalize_symbol(symbol)
    now = _now_utc()

    with _lock:
        events = _signals.get(symbol)
        if not events:
            return

        for ev in events:
            if not ev.get("entry") or ev["entry"] <= 0:
                continue
            ev_ts = datetime.fromisoformat(ev["ts"])
            age_min = (now - ev_ts).total_seconds() / 60.0
            entry = ev["entry"]

            for minutes in FUTURE_CHECK_POINTS:
                key = f"future_{minutes}m"
                if ev.get(key) is None and age_min >= minutes:
                    # Store % change from entry
                    pct = ((current_price - entry) / entry) * 100.0
                    ev[key] = round(pct, 4)


# ═══════════════════════════════════════════════════════════════════════════
# LIVE COUNTERS (for Step 3 brain decision-making)
# ═══════════════════════════════════════════════════════════════════════════
def get_counters(symbol: str, window_min: int = 60) -> dict:
    """Returns counts of each signal category within `window_min` minutes."""
    symbol = _normalize_symbol(symbol)
    now = _now_utc()
    cutoff = now.timestamp() - (window_min * 60)

    counts = {
        "buy": 0, "sell": 0,
        "scalp_buy": 0, "scalp_sell": 0,
        "bias_bull": 0, "bias_bear": 0,
        "warn_bull": 0, "warn_bear": 0,
        "warn": 0,
        "total": 0,
    }

    with _lock:
        for ev in _signals.get(symbol, []):
            if ev["ts_unix"] < cutoff:
                continue
            counts["total"] += 1
            cat = ev["category"]
            if cat == "TRADE_BUY": counts["buy"] += 1
            elif cat == "TRADE_SELL": counts["sell"] += 1
            elif cat == "SCALP_BUY": counts["scalp_buy"] += 1
            elif cat == "SCALP_SELL": counts["scalp_sell"] += 1
            elif cat == "BIAS_BULL": counts["bias_bull"] += 1
            elif cat == "BIAS_BEAR": counts["bias_bear"] += 1
            elif cat == "WARN_BULL": counts["warn_bull"] += 1
            elif cat == "WARN_BEAR": counts["warn_bear"] += 1
            elif cat == "WARN": counts["warn"] += 1

    return counts


def get_last_signal(symbol: str, category: Optional[str] = None, max_age_min: int = 15) -> Optional[dict]:
    """Returns most recent signal of `category` within max_age_min, or None."""
    symbol = _normalize_symbol(symbol)
    now = _now_utc()
    cutoff = now.timestamp() - (max_age_min * 60)

    with _lock:
        for ev in reversed(_signals.get(symbol, [])):
            if ev["ts_unix"] < cutoff:
                return None
            if category is None or ev["category"] == category:
                return dict(ev)
    return None


def get_all_recent(symbol: str, window_min: int = 60) -> List[dict]:
    """Returns all signals within window (most recent first)."""
    symbol = _normalize_symbol(symbol)
    now = _now_utc()
    cutoff = now.timestamp() - (window_min * 60)

    with _lock:
        return [dict(ev) for ev in reversed(_signals.get(symbol, [])) if ev["ts_unix"] >= cutoff]


# ═══════════════════════════════════════════════════════════════════════════
# TRADE OUTCOME TRACKING (called from bot.py when trade closes)
# ═══════════════════════════════════════════════════════════════════════════
def mark_traded(signal_id_or_symbol: str, traded: bool = True):
    """Mark most recent matching signal as traded."""
    symbol = _normalize_symbol(signal_id_or_symbol.split("-")[0] if "-" in signal_id_or_symbol else signal_id_or_symbol)
    with _lock:
        evs = _signals.get(symbol)
        if evs:
            for ev in reversed(evs):
                if not ev.get("traded"):
                    ev["traded"] = traded
                    return


def mark_trade_outcome(symbol: str, win: bool, pnl: float):
    """Update outcome on most recent traded signal."""
    symbol = _normalize_symbol(symbol)
    with _lock:
        for ev in reversed(_signals.get(symbol, [])):
            if ev.get("traded") and ev.get("trade_win") is None:
                ev["trade_win"] = win
                ev["trade_pnl"] = float(pnl)
                return


# ═══════════════════════════════════════════════════════════════════════════
# ANALYTICS (used in Step 2 review)
# ═══════════════════════════════════════════════════════════════════════════
def get_analytics(symbol: Optional[str] = None) -> dict:
    """
    Full analytics for Step 2 data review.
    Returns win rates per category, per session, average future moves.
    """
    results = {
        "total_signals":  0,
        "by_category":    defaultdict(lambda: {"count": 0, "future_15m_avg": 0.0, "future_60m_avg": 0.0}),
        "by_session":     defaultdict(lambda: {"count": 0, "future_15m_avg": 0.0}),
        "by_symbol":      defaultdict(lambda: {"count": 0}),
        "trade_win_rate": 0.0,
        "trade_count":    0,
    }

    wins = 0
    trades = 0

    with _lock:
        symbols = [symbol] if symbol else list(_signals.keys())
        for sym in symbols:
            sym = _normalize_symbol(sym)
            for ev in _signals.get(sym, []):
                results["total_signals"] += 1
                cat = ev["category"]
                sess = ev["session"]

                results["by_category"][cat]["count"] += 1
                results["by_session"][sess]["count"] += 1
                results["by_symbol"][sym]["count"] += 1

                if ev.get("future_15m") is not None:
                    old = results["by_category"][cat]["future_15m_avg"]
                    n   = results["by_category"][cat]["count"]
                    results["by_category"][cat]["future_15m_avg"] = (old * (n-1) + ev["future_15m"]) / n
                    sold = results["by_session"][sess]["future_15m_avg"]
                    sn   = results["by_session"][sess]["count"]
                    results["by_session"][sess]["future_15m_avg"] = (sold * (sn-1) + ev["future_15m"]) / sn

                if ev.get("future_60m") is not None:
                    old = results["by_category"][cat]["future_60m_avg"]
                    n   = results["by_category"][cat]["count"]
                    results["by_category"][cat]["future_60m_avg"] = (old * (n-1) + ev["future_60m"]) / n

                if ev.get("traded"):
                    trades += 1
                    if ev.get("trade_win"):
                        wins += 1

    results["trade_count"]    = trades
    results["trade_win_rate"] = (wins / trades * 100.0) if trades > 0 else 0.0
    # Convert defaultdicts to regular dicts
    results["by_category"] = dict(results["by_category"])
    results["by_session"]  = dict(results["by_session"])
    results["by_symbol"]   = dict(results["by_symbol"])
    return results


# ═══════════════════════════════════════════════════════════════════════════
# PERSISTENCE (crash backup only — primary storage is RAM)
# ═══════════════════════════════════════════════════════════════════════════
def _maybe_persist():
    global _last_save
    now = time.time()
    if now - _last_save < PERSIST_INTERVAL_SEC:
        return
    _last_save = now
    try:
        data = {sym: list(events) for sym, events in _signals.items()}
        tmp = PERSIST_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1, default=str)
        os.replace(tmp, PERSIST_FILE)
    except Exception as e:
        log.warning(f"[MEM] persist failed: {e}")


def load_from_disk():
    """Call on startup to restore signals from last save."""
    if not os.path.exists(PERSIST_FILE):
        return
    try:
        with open(PERSIST_FILE) as f:
            data = json.load(f)
        with _lock:
            for sym, events in data.items():
                dq = deque(maxlen=MAX_SIGNALS_PER_SYMBOL)
                for ev in events[-MAX_SIGNALS_PER_SYMBOL:]:
                    dq.append(ev)
                _signals[sym] = dq
        log.info(f"[MEM] Loaded {sum(len(d) for d in _signals.values())} signals from disk")
    except Exception as e:
        log.warning(f"[MEM] load failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# DEBUG HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def dump_summary() -> dict:
    """Quick summary for /status endpoint."""
    with _lock:
        return {
            "total_symbols": len(_signals),
            "total_signals": sum(len(d) for d in _signals.values()),
            "per_symbol":    {sym: len(d) for sym, d in _signals.items()},
        }
