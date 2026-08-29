#!/usr/bin/env python3
"""News semantic engine v1 (2026-08-31) — WHAT the news means, deterministically.

NEWS TEXT -> EVENT CLASS -> SURPRISE (numbers first) -> STANCE -> PRESSURE MAP
-> price confirmation stays with the scenario engine. This module NEVER
produces a trade signal and NEVER blocks: it turns calendar rows into
STRUCTURED FACTS with named confidence, and UNKNOWN stays UNKNOWN.

Laws of this engine:
- Numbers beat words: when actual+forecast exist, surprise comes from the
  comparison, never from wording. No numbers -> surprise UNKNOWN.
- Inverted series (unemployment rate, jobless claims): HIGHER actual means
  a WEAKER economy -> dovish, the polarity table below says so explicitly.
- Non-USD events -> pressure UNKNOWN in v1 (no fact is manufactured).
- Two in-window events with opposite stances -> CONFLICTING NEWS -> the
  fact says so and the only honest action is WAIT.
- MACRO PRESSURE is context, not a signal; the deterministic price engine
  (structure, touch, retest, R:R, freshness) keeps the final vote.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# ── 1. taxonomy: normalized event classes from calendar titles ──
TAXONOMY = {
    "INFLATION": ("CPI", "PCE", "PPI", "INFLATION"),
    "EMPLOYMENT": ("NON-FARM", "NONFARM", "PAYROLL", "NFP", "UNEMPLOYMENT",
                   "JOBLESS", "EMPLOYMENT", "ADP", "JOBS"),
    "FED_RATE": ("FOMC", "FEDERAL FUNDS", "FED CHAIR", "POWELL",
                 "INTEREST RATE", "RATE STATEMENT", "MONETARY POLICY"),
    "GROWTH": ("GDP",),
}
# series where a HIGHER actual means a WEAKER economy
INVERTED = ("UNEMPLOYMENT", "JOBLESS")

# headline words -> stance, MEDIUM confidence, used ONLY when numbers absent
STANCE_WORDS = {"HAWKISH": "HAWKISH", "HOTTER": "HAWKISH", "RATE HIKE": "HAWKISH",
                "DOVISH": "DOVISH", "COOLER": "DOVISH", "RATE CUT": "DOVISH"}

# ── 4. deterministic stance -> asset pressure map (USD events) ──
PRESSURE = {
    "HAWKISH": {"DXY": "BULLISH", "YIELDS": "BULLISH", "GOLD": "BEARISH",
                "SILVER": "BEARISH", "US100": "BEARISH", "US30": "BEARISH",
                "USDJPY": "BULLISH", "GBPUSD": "BEARISH", "BTC": "BEARISH"},
    "DOVISH": {"DXY": "BEARISH", "YIELDS": "BEARISH", "GOLD": "BULLISH",
               "SILVER": "BULLISH", "US100": "BULLISH", "US30": "BULLISH",
               "USDJPY": "BEARISH", "GBPUSD": "BULLISH", "BTC": "BULLISH"},
}

PHASES = ((-60, 0, "PRE-EVENT"), (0, 15, "INITIAL MOVE"),
          (15, 45, "STRUCTURE FORMING"), (45, 90, "RETEST"),
          (90, 240, "POST-NEWS"))


def parse_num(s):
    """'3.1%' -> 3.1, '210K' -> 210000.0, '' -> None. Numbers first."""
    if s is None:
        return None
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*([KMB%])?\s*$", str(s).strip())
    if not m:
        return None
    v = float(m.group(1))
    return v * {"K": 1e3, "M": 1e6, "B": 1e9, "%": 1, None: 1}[m.group(2)]


def classify(title):
    up = (title or "").upper()
    for cls, words in TAXONOMY.items():
        if any(w in up for w in words):
            return cls
    return "OTHER"


def surprise(actual, forecast):
    """(surprise, confidence). Numeric compare or UNKNOWN — never wording
    when numbers exist, and wording alone never sets surprise at all."""
    a, f = parse_num(actual), parse_num(forecast)
    if a is None or f is None:
        return "UNKNOWN", "UNKNOWN"
    if a > f:
        return "HOT", "HIGH"
    if a < f:
        return "COOL", "HIGH"
    return "INLINE", "HIGH"


def stance_of(title, cls, surp):
    """Fed-direction reading of one event. (stance, confidence, basis)."""
    up = (title or "").upper()
    inverted = any(w in up for w in INVERTED)
    if surp in ("HOT", "COOL"):
        hot_is_hawkish = not inverted          # hot inflation/jobs/gdp = hawkish
        hawk = (surp == "HOT") == hot_is_hawkish
        return ("HAWKISH" if hawk else "DOVISH"), "HIGH", "actual vs forecast"
    for word, st in STANCE_WORDS.items():      # words only when numbers absent
        if word in up:
            return st, "MEDIUM", f"headline word '{word}'"
    return "UNKNOWN", "UNKNOWN", "no numbers, no stance wording"


def phase_of(minutes_from_event):
    for lo, hi, name in PHASES:
        if lo <= minutes_from_event < hi:
            return name
    return "NORMAL"


def event_fact(ev, now=None):
    """One calendar row -> one structured fact (source/keyword/value/
    confidence/timestamp all named, per the confidence law)."""
    now = now or datetime.now(timezone.utc)
    try:
        t = datetime.fromisoformat(str(ev.get("date")).replace("Z", "+00:00"))
    except Exception:
        return None
    mins = (now - t).total_seconds() / 60.0
    cls = classify(ev.get("title"))
    surp, s_conf = surprise(ev.get("actual"), ev.get("forecast"))
    stance, conf, basis = stance_of(ev.get("title"), cls, surp)
    currency = str(ev.get("currency") or "").upper()
    pressure = PRESSURE.get(stance, {}) if currency == "USD" else {}
    return {"event": ev.get("title"), "event_class": cls, "currency": currency,
            "event_time": t.isoformat(), "minutes_from_event": round(mins, 1),
            "event_phase": phase_of(mins), "surprise": surp,
            "stance": stance, "stance_basis": basis, "confidence": conf,
            "pressure": pressure or "UNKNOWN (non-USD or stance unknown)",
            "source": "economic calendar"}


def news_context(events, symbol, now=None):
    """Nearest in-window (PRE..POST) high-impact facts for one symbol.
    Returns the context dict the scenario record embeds, or None when the
    regime is NORMAL. CONFLICTING NEWS is declared, never resolved."""
    now = now or datetime.now(timezone.utc)
    facts = []
    for ev in events or []:
        f = event_fact(ev, now)
        if f and f["event_phase"] != "NORMAL":
            facts.append(f)
    if not facts:
        return None
    facts.sort(key=lambda f: abs(f["minutes_from_event"]))
    lead = facts[0]
    stances = {f["stance"] for f in facts} - {"UNKNOWN"}
    conflicting = stances >= {"HAWKISH", "DOVISH"}
    sym_press = "UNKNOWN"
    if not conflicting and isinstance(lead["pressure"], dict):
        sym_press = lead["pressure"].get(symbol.upper(), "UNKNOWN")
    return {**lead, "symbol_pressure": sym_press,
            "conflicting": conflicting,
            "note": "CONFLICTING NEWS — no direction forced" if conflicting
                    else "MACRO PRESSURE, not a trade signal"}


def agreement(symbol_pressure, bias):
    """News direction vs price direction. Price keeps the final vote."""
    if symbol_pressure not in ("BULLISH", "BEARISH") or not bias:
        return "UNKNOWN"
    price = "BULLISH" if "bullish" in str(bias) else \
            "BEARISH" if "bearish" in str(bias) else None
    if price is None:
        return "UNKNOWN"
    return "CONFIRMED" if price == symbol_pressure else "⚠ CONFLICT — WAIT"
