"""Strategy DNA (Stage 8) — classify every signal into ONE strategy family so
performance can be measured per-strategy and a losing family can be retired on
evidence, not feeling.

Families:
    S1  trend_continuation  — with the H1/H4 trend, momentum entry
    S2  pullback_sniper     — Pine type PULLBACK / retrace to structure
    S3  breakout            — Pine type BREAKOUT / breakout_* fields present
    S4  mean_reversion      — counter-trend scalp / discount-premium fade
    S5  news_reaction       — fired inside a news window
    S0  unclassified        — nothing matched (keep, don't guess)

Pure function, no I/O — safe to unit-test and to backfill over signal_memory.json
(the Pine fields it reads are already archived, so historical trades can be
tagged retroactively; only NEW trades get tagged live via telemetry).
"""
from __future__ import annotations

STRATEGIES = {
    "S1": "trend_continuation",
    "S2": "pullback_sniper",
    "S3": "breakout",
    "S4": "mean_reversion",
    "S5": "news_reaction",
    "S0": "unclassified",
}


def _s(v):
    return str(v or "").strip().upper()


def classify(payload: dict) -> str:
    """Return a strategy id (S1..S5, or S0). Order matters: the most specific,
    most physically-distinct families are tested first so a trade lands in the
    family that actually describes it.

    Reads only fields Pine already sends (type, breakout_*, news_window,
    trend/htf_trend, zone, direction) — no new capture required."""
    typ = _s(payload.get("type"))
    zone = _s(payload.get("zone") or payload.get("loc_zone"))
    direction = _s(payload.get("direction") or payload.get("signal"))
    trend = _s(payload.get("htf_trend") or payload.get("trend"))

    # S5 news reaction — a live news window dominates the family (it's a
    # different risk regime regardless of the structural setup).
    nw = payload.get("news_window")
    if nw is True or _s(nw) in ("TRUE", "1", "YES", "ON"):
        return "S5"

    # S3 breakout — explicit type or the breakout_* telemetry Pine sends.
    if typ == "BREAKOUT" or payload.get("breakout_prob") is not None \
            or _s(payload.get("breakout_strength")) in ("STRONG", "BUILDING"):
        return "S3"

    # S2 pullback sniper — the validated class (its own physics per CLAUDE.md).
    if typ == "PULLBACK":
        return "S2"

    # S4 mean reversion — a counter-trend entry, or a fade at the far edge of
    # the range (SELL in a DISCOUNT/support zone, BUY in a PREMIUM/resistance
    # zone). This is the #1 documented loss driver, so tagging it is the point.
    counter = (trend in ("UP", "BULL") and direction == "SELL") or \
              (trend in ("DOWN", "BEAR") and direction == "BUY")
    fade = (direction == "SELL" and "DISCOUNT" in zone) or \
           (direction == "BUY" and "PREMIUM" in zone)
    if counter or fade:
        return "S4"

    # S1 trend continuation — aligned with the higher-timeframe trend.
    aligned = (trend in ("UP", "BULL") and direction == "BUY") or \
              (trend in ("DOWN", "BEAR") and direction == "SELL")
    if aligned:
        return "S1"

    return "S0"


def classify_named(payload: dict) -> tuple:
    """(strategy_id, human_name) for logging/telemetry."""
    sid = classify(payload)
    return sid, STRATEGIES[sid]
