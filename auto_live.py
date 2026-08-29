#!/usr/bin/env python3
"""auto-live-v1 — v7 trades WITHOUT Pine, on its own measured record (2026-08-30).

EARNED, not granted. The review of 2026-08-30 read auto-v1's paper book
(2,659 resolved candidates) and discounted it by real recorded spreads:
    SILVER +1.303R net (n=285) · GBPUSD +1.168R (n=195) · US30 +0.843R
    (n=149) · BTC +0.133R (n=150). Everything else NEGATIVE net —
    including GOLD, USDJPY, US100. This engine trades ONLY the earners.

HOW IT STAYS SIMPLE AND SAFE (Shyam's rule: no hundred rules):
- Zero changes to bot.py. Candidates are POSTed to v7's OWN webhook on
  127.0.0.1:5000, so EVERY existing hard gate applies untouched: news
  block, per-class slots, pause, SL limits, R:R floor, sizing, equity
  guard, dedupe, telemetry, mirror, freshness shadow. We add none and
  we bypass none.
- The strategy is auto-v1's, ported VERBATIM from the platform
  (scanner.atr, scanner.structure_state, the _rules arithmetic) — the
  same math that produced the record. A different formula would be a
  different, unmeasured engine.
- LIMIT -> TOUCH translation: v7 places market orders, so instead of
  parking a limit we fire only when a CLOSED 15m bar actually TOUCHES
  the structural level (the exact moment the paper limit filled) AND
  the structure that justified it is STILL intact right now. A far
  level reached after its structure died is the measured far-bucket
  bleed; requiring live structure at touch is what excludes it.
- ONE strategy condition from the record: levels farther than
  AUTO_LIVE_MAX_DIST (default 3.0 ATR) at detection are never tracked.
- ARMED IS OPT-IN: AUTO_LIVE_ARM unset/0 = DRY RUN — every would-be
  signal is logged to logs/auto_live.jsonl and NOTHING is posted.
  Arm only after reading dry candidates and probing US30 end to end.

Env (.env or environment):
    AUTO_LIVE_SYMBOLS   default SILVER,GBPUSD,US30   (the net earners)
    AUTO_LIVE_MAX_DIST  default 3.0
    AUTO_LIVE_ARM       default 0 (dry run)
    EXECUTOR_URL        bridge, same var bot.py uses

Cron (state file dedupes; re-runs are safe):
    */5 * * * * cd /home/shyam/brother_sniper_v7 && /usr/bin/python3 auto_live.py >> logs/auto_live.log 2>&1
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
STATE_F = os.path.join(DIR, "logs", "auto_live_state.json")
DRY_LOG = os.path.join(DIR, "logs", "auto_live.jsonl")
SCEN_LOG = os.path.join(DIR, "logs", "auto_scenarios.jsonl")
WEBHOOK = "http://127.0.0.1:5000/webhook"
TF_MIN = 15
LOOKBACK = 40                    # platform auto-v1 structural window
MIN_BARS = 60
SL_ATR = 1.0                     # platform autonomous.SL_ATR
MIN_RR = 1.0                     # platform autonomous.MIN_RR
REFIRE_COOLDOWN_S = 24 * 3600    # same level+side not re-fired within a day


def _env(key, default=""):
    v = os.getenv(key, "").strip()
    if v:
        return v
    try:
        with open(os.path.join(DIR, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return default


# ── ported VERBATIM from platform app/services/scanner.py (record's math) ──

def atr(rows, period=14):
    if len(rows) < period + 1:
        return None
    trs = []
    for i in range(len(rows) - period, len(rows)):
        c, p = rows[i], rows[i - 1]
        trs.append(max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"])))
    return round(sum(trs) / period, 5)


def structure_state(rows, swing=3):
    if len(rows) < swing * 2 + 5:
        return None
    highs, lows = [], []
    for i in range(swing, len(rows) - swing):
        w = rows[i - swing:i + swing + 1]
        if rows[i]["h"] == max(c["h"] for c in w):
            highs.append(rows[i]["h"])
        if rows[i]["l"] == min(c["l"] for c in w):
            lows.append(rows[i]["l"])
    if len(highs) < 2 or len(lows) < 2:
        return None
    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "HH/HL"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "LH/LL"
    return "MIXED"


def candidate(rows, max_dist_atr, now=None):
    """auto-v1's decision on closed 15m rows, touch-translated.
    Returns (payload_core, why_not). Fires ONLY when the newest CLOSED
    bar touched the structural level and structure is still intact."""
    now = now or time.time()
    closed = [r for r in rows if r.get("time") and float(r["time"]) + TF_MIN * 60 <= now]
    if len(closed) < MIN_BARS:
        return None, f"only {len(closed)} closed bars (<{MIN_BARS})"
    if now - float(closed[-1]["time"]) > TF_MIN * 60 * 3:
        return None, "candles stale (>3 bars) — DECISION BLOCKED, DATA FRESHNESS"
    a = atr(closed)
    st = structure_state(closed)
    if not a or st not in ("HH/HL", "LH/LL"):
        return None, f"no edge context (atr={a}, structure={st})"
    win = closed[-LOOKBACK:]
    r_high = max(c["h"] for c in win)
    r_low = min(c["l"] for c in win)
    last = closed[-1]
    if st == "HH/HL":
        d, level, sl, tp = "BUY", r_low, r_low - SL_ATR * a, r_high
        touched = last["l"] <= level
    else:
        d, level, sl, tp = "SELL", r_high, r_high + SL_ATR * a, r_low
        touched = last["h"] >= level
    dist = abs(last["c"] - level) / a
    if dist > max_dist_atr:
        return None, f"level {dist:.2f} ATR away (> {max_dist_atr}) — far bucket is the measured bleed"
    if not touched:
        return None, f"level not touched this bar (dist {dist:.2f} ATR) — WAIT"
    risk = abs(level - sl)
    rr = round(abs(tp - level) / risk, 2) if risk else 0
    if rr < MIN_RR:
        return None, f"RR {rr} < {MIN_RR}"
    bar_ts = int(float(last["time"]))
    return {"direction": d, "entry": round(level, 5), "sl": round(sl, 5),
            "tp": round(tp, 5), "tp1": round(tp, 5), "rr": rr,
            "atr": a, "structure": st, "entry_dist_atr": round(dist, 2),
            "bar_ts": bar_ts, "level": round(level, 5)}, None


# ── Week-2 (2026-08-31): conditional scenario record — the DECISION even
# when the decision is WAIT. Same math as candidate(); candidate() stays
# the sole firing authority and tests pin their equivalence. ──

WAIT, FRESH_BLOCK = "⚪ WAIT", "⛔ DATA FRESHNESS"


def scenario(sym, rows, max_dist_atr, now=None):
    """Full autonomous scenario record for one symbol, every run.
    pine_dependency is NONE by construction: nothing here reads Pine.
    Missing feeds (event phase, macro) say UNKNOWN — never manufactured."""
    now = now or time.time()
    closed = [r for r in rows if r.get("time") and float(r["time"]) + TF_MIN * 60 <= now]
    rec = {"scenario_id": f"SC2-{sym}-{int(float(closed[-1]['time'])) if closed else int(now)}",
           "symbol": sym, "tf": str(TF_MIN), "ts": now,
           "pine_dependency": "NONE",
           "event_phase": "UNKNOWN (event feed not wired into scenario v1)",
           "macro_context": "UNKNOWN (never manufactured)",
           "freshness": "OK", "state": WAIT, "bias": "UNKNOWN",
           "missing_confirmation": [], "invalidation": None,
           "next_thing_to_watch": None, "current_state": None}
    if len(closed) < MIN_BARS:
        rec["missing_confirmation"] = [f"history ({len(closed)}/{MIN_BARS} closed bars)"]
        rec["current_state"] = "INSUFFICIENT HISTORY"
        return rec
    if now - float(closed[-1]["time"]) > TF_MIN * 60 * 3:
        rec.update(state=FRESH_BLOCK, freshness="STALE >3 bars",
                   current_state="DECISION BLOCKED — DATA FRESHNESS",
                   next_thing_to_watch="candle feed recovering")
        return rec
    a, st = atr(closed), structure_state(closed)
    if not a or st not in ("HH/HL", "LH/LL"):
        rec.update(bias="mixed" if st == "MIXED" else "UNKNOWN",
                   current_state="NEITHER CONFIRMED",
                   missing_confirmation=["structure (HH/HL or LH/LL)"],
                   next_thing_to_watch="two rising or two falling swing pairs")
        return rec
    win = closed[-LOOKBACK:]
    r_high, r_low = max(c["h"] for c in win), min(c["l"] for c in win)
    last = closed[-1]
    d = "BUY" if st == "HH/HL" else "SELL"
    level = r_low if d == "BUY" else r_high
    sl = level - SL_ATR * a if d == "BUY" else level + SL_ATR * a
    tp = r_high if d == "BUY" else r_low
    touched = last["l"] <= level if d == "BUY" else last["h"] >= level
    dist = abs(last["c"] - level) / a
    risk = abs(level - sl)
    rr = round(abs(tp - level) / risk, 2) if risk else 0
    rec.update(bias=f"{'bullish' if d == 'BUY' else 'bearish'} ({st})",
               key_level=round(level, 5), entry=round(level, 5),
               sl=round(sl, 5), tp=round(tp, 5), rr=rr,
               entry_dist_atr=round(dist, 2),
               bullish_condition=f"closed 15m bar touches {round(r_low, 5)} with HH/HL intact, RR≥{MIN_RR}",
               bearish_condition=f"closed 15m bar touches {round(r_high, 5)} with LH/LL intact, RR≥{MIN_RR}",
               invalidation=f"structure flip away from {st}, or level beyond {max_dist_atr} ATR")
    if dist > max_dist_atr:
        rec.update(current_state="LEVEL TOO FAR — the measured far-bucket bleed",
                   missing_confirmation=[f"price within {max_dist_atr} ATR of level (now {dist:.2f})"],
                   next_thing_to_watch=f"price returning toward {round(level, 5)}")
        return rec
    if touched and rr >= MIN_RR:
        rec.update(state=f"{'🟢' if d == 'BUY' else '🔴'} {d} READY",
                   current_state=f"{d} SETUP VALID — level touched, structure intact",
                   next_thing_to_watch="v7 hard gates (news, slots, sizing) on fire")
        return rec
    if touched:
        rec.update(current_state=f"touched but RR {rr} < {MIN_RR}",
                   missing_confirmation=[f"R:R ≥ {MIN_RR}"],
                   next_thing_to_watch="range extending to restore R:R")
        return rec
    rec.update(state=f"🟡 {d} DEVELOPING",
               current_state=f"NEITHER CONFIRMED — {d} bias, awaiting touch",
               missing_confirmation=[f"touch of {round(level, 5)} on a closed 15m bar"],
               next_thing_to_watch=f"15m closing near {round(level, 5)}")
    return rec


def _state():
    try:
        with open(STATE_F, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _fired_recently(state, sym, c, now):
    k = f"{sym}:{c['direction']}:{c['level']}"
    return (now - state.get(k, 0)) < REFIRE_COOLDOWN_S, k


def main() -> int:
    os.makedirs(os.path.join(DIR, "logs"), exist_ok=True)
    base = _env("EXECUTOR_URL").replace("/execute", "")
    if not base:
        print("REFUSED: EXECUTOR_URL unset")
        return 1
    symbols = [s.strip().upper() for s in
               _env("AUTO_LIVE_SYMBOLS", "SILVER,GBPUSD,US30").split(",") if s.strip()]
    max_dist = float(_env("AUTO_LIVE_MAX_DIST", "3.0"))
    armed = _env("AUTO_LIVE_ARM", "0").lower() in ("1", "true", "yes")
    state = _state()
    now = time.time()
    for sym in symbols:
        try:
            with urllib.request.urlopen(
                    f"{base.rstrip('/')}/candles?symbol={sym}&tf={TF_MIN}&n=120",
                    timeout=10) as r:
                rows = (json.loads(r.read().decode()) or {}).get("rows") or []
        except Exception as e:
            print(f"{sym}: candle fetch failed: {e}")
            continue
        rec = scenario(sym, rows, max_dist, now)
        prev = state.get(f"scen:{sym}")
        cur = f"{rec['state']}@{rec.get('key_level')}"
        if cur != prev:                       # log transitions, not heartbeats
            with open(SCEN_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            state[f"scen:{sym}"] = cur
        c, why = candidate(rows, max_dist, now)
        if c is None:
            print(f"{sym}: {why}")
            continue
        hot, key = _fired_recently(state, sym, c, now)
        if hot:
            print(f"{sym}: {c['direction']} at {c['level']} already fired <24h — dedupe")
            continue
        payload = {"system": "AUTOLIVE", "type": "AUTO_PULLBACK",
                   "engine": "auto-live-v1",
                   "signal": c["direction"], "direction": c["direction"],
                   "signal_id": f"AL-{c['direction']}-{sym}-{c['bar_ts']}",
                   "symbol": sym, "tf": str(TF_MIN),
                   "entry": c["entry"], "sl": c["sl"], "tp": c["tp"],
                   "tp1": c["tp1"], "rr": c["rr"], "atr": c["atr"],
                   "structure": c["structure"],
                   "entry_dist_atr": c["entry_dist_atr"],
                   "pine_dependency": "NONE",
                   "time": c["bar_ts"]}
        with open(DRY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"armed": armed, "posted_at": now, **payload}) + "\n")
        if not armed:
            print(f"{sym}: DRY RUN — would fire {c['direction']} at {c['entry']} "
                  f"(SL {c['sl']}, TP {c['tp']}, RR {c['rr']}); AUTO_LIVE_ARM=1 to go live")
            continue
        try:
            req = urllib.request.Request(
                WEBHOOK, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                reply = json.loads(r.read().decode())
            state[key] = now
            print(f"{sym}: FIRED {c['direction']} at {c['entry']} -> v7 said {reply}")
        except Exception as e:
            print(f"{sym}: POST failed (v7 gates unreached): {e}")
    with open(STATE_F, "w", encoding="utf-8") as f:
        json.dump(state, f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
