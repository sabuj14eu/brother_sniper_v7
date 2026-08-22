"""DECISION BLOCKED — DATA FRESHNESS (autonomy stage 2, v1 — 2026-08-22).

The state the desk never had: not "WAIT because the setup is bad" but
"this evaluation is NO LONGER AUTHORITATIVE — recalculate, then decide
fresh." Never "buy because price moved", never "refresh and auto-buy":
a stale decision produces NO ACTION, and only a completely new
evaluation may act.

v1 gates on what the bot already measures at the decision site:
  - SIGNAL AGE: seconds since Pine fired (signal_age_seconds_v). A
    15m-engine signal older than one bar is describing a market that no
    longer exists. Default max 900s, env V7_FRESH_MAX_SIGNAL_AGE_S.
  - MATERIAL MOVE (inputs optional until the live-tick plumbing lands,
    planned v2): |reference_close − entry| / ATR beyond
    V7_FRESH_MAX_MOVE_ATR (default 1.5) means the reference changed
    materially — the BTC 78,385→80,000 case.

MODES (env V7_FRESHNESS_GATE, default "shadow" — Evidence Law: the gate
earns enforcement with its own shadow log, n>=20 before judging):
  off      never evaluates
  shadow   evaluates + logs + telemetry-rejects tagged freshness_shadow;
           NEVER blocks. This builds the would-have-blocked evidence.
  enforce  blocks with DECISION BLOCKED — DATA FRESHNESS. Turning this
           on is an EXPLICIT HUMAN DECISION (Iron Rule 7 posture), made
           after reading the shadow numbers.

UNKNOWN inputs (age None, ATR None) do NOT block in v1 — this matches
the codebase's documented fail-safe posture (fetch_atr fails to None and
the trade proceeds). Flipping UNKNOWN to fail-closed is a listed future
decision, not a silent default. Pure functions; no I/O; never raises.
"""
from __future__ import annotations

import os

BLOCKED_STATE = "DECISION BLOCKED — DATA FRESHNESS"

DEFAULT_MAX_SIGNAL_AGE_S = 900.0     # one 15m bar
DEFAULT_MAX_MOVE_ATR = 1.5


def evaluate(signal_age_s=None, entry=None, reference_close=None, atr=None,
             max_age_s: float = DEFAULT_MAX_SIGNAL_AGE_S,
             max_move_atr: float = DEFAULT_MAX_MOVE_ATR) -> dict:
    """Pure verdict. blocked=True means the criteria are violated;
    whether that becomes NO ACTION is the caller's mode decision."""
    checks = {}
    reasons = []

    if signal_age_s is None:
        checks["signal_age"] = "UNKNOWN"
    elif signal_age_s > max_age_s:
        checks["signal_age"] = f"STALE ({signal_age_s:.0f}s > {max_age_s:.0f}s)"
        reasons.append(f"signal fired {signal_age_s:.0f}s ago "
                       f"(limit {max_age_s:.0f}s) — the market it describes "
                       f"is {signal_age_s / 900:.1f} bars old")
    else:
        checks["signal_age"] = f"FRESH ({signal_age_s:.0f}s)"

    move_atr = None
    if entry is not None and reference_close is not None and atr:
        try:
            move_atr = round(abs(float(reference_close) - float(entry)) / float(atr), 2)
        except (TypeError, ValueError, ZeroDivisionError):
            move_atr = None
    if move_atr is None:
        checks["material_move"] = "UNKNOWN (no live reference wired yet — v2)"
    elif move_atr > max_move_atr:
        checks["material_move"] = f"MOVED {move_atr} ATR (> {max_move_atr})"
        reasons.append(f"price sits {move_atr} ATR from the evaluated entry "
                       f"(limit {max_move_atr}) — the reference changed "
                       f"materially; the old decision is not authoritative")
    else:
        checks["material_move"] = f"OK ({move_atr} ATR)"

    blocked = bool(reasons)
    return {"state": BLOCKED_STATE if blocked else "OK",
            "blocked": blocked,
            "reason": "; ".join(reasons) if reasons else "fresh",
            "checks": checks,
            "limits": {"max_age_s": max_age_s, "max_move_atr": max_move_atr}}


def gate_from_env(signal_age_s=None, entry=None, reference_close=None,
                  atr=None) -> dict:
    """The wiring entry point: reads mode + thresholds from env, returns
    the verdict with the mode attached. mode=off short-circuits to OK."""
    mode = (os.getenv("V7_FRESHNESS_GATE", "shadow") or "shadow").strip().lower()
    if mode not in ("off", "shadow", "enforce"):
        mode = "shadow"                      # an unknown word never widens risk
    if mode == "off":
        return {"state": "OK", "blocked": False, "mode": "off",
                "reason": "gate off", "checks": {}, "limits": {}}

    def _f(env, default):
        try:
            return float(os.getenv(env, "") or default)
        except (TypeError, ValueError):
            return default

    out = evaluate(signal_age_s=signal_age_s, entry=entry,
                   reference_close=reference_close, atr=atr,
                   max_age_s=_f("V7_FRESH_MAX_SIGNAL_AGE_S", DEFAULT_MAX_SIGNAL_AGE_S),
                   max_move_atr=_f("V7_FRESH_MAX_MOVE_ATR", DEFAULT_MAX_MOVE_ATR))
    out["mode"] = mode
    return out
