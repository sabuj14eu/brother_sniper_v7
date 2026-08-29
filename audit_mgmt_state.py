#!/usr/bin/env python3
"""Management state-machine audit (Week-2, 2026-08-31) — read-only + one
result file. Invariants that MUST be zero, checked against what actually
exists (learning/trades.jsonl, signal_memory.json, state.json, bot.py):

    closed_reactivated   a closed signal_id still sits in state.json opens
    double_close         same signal_id closed twice in trades.jsonl
    partial_fired        partial is disabled ([BE-ONLY]); any partial_done=True
    sl_wrong_side        open trade whose SL is on the profit side of entry
                         (setup-SL confused with position-SL)
    negative_excursion   mae/mfe recorded negative
    widen_guard_missing  bot.py no longer carries the _tighter guard
                         (the only line standing between BE and SL-widening)

Every violation is printed with WHAT/WHY/RULE/WHERE. Result counts land in
logs/mgmt_audit_last.json for the daily scorecard. Exit 1 on any violation.

    python3 audit_mgmt_state.py
"""
from __future__ import annotations

import collections
import json
import os
import sys
from datetime import datetime, timezone

DIR = os.path.dirname(os.path.abspath(__file__))
TRADES = os.path.join(DIR, "learning", "trades.jsonl")
MEMORY = os.path.join(DIR, "signal_memory.json")
STATE = os.path.join(DIR, "state.json")
BOT = os.path.join(DIR, "bot.py")
OUT = os.path.join(DIR, "logs", "mgmt_audit_last.json")

GUARD = '_tighter=(_dir=="BUY" and _be>_cur_sl) or (_dir=="SELL" and _be<_cur_sl)'


def _jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except Exception:
                        pass
    except FileNotFoundError:
        return


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def audit():
    v = collections.defaultdict(list)      # invariant -> violation descriptions

    close_counts = collections.Counter()
    for r in _jsonl(TRADES):
        sid = r.get("signal_id")
        if sid and ("won" in r or "net_profit" in r):
            close_counts[sid] += 1
        for k in ("mae", "mfe"):
            if r.get(k) is not None and float(r[k]) < 0:
                v["negative_excursion"].append(
                    f"WHAT {k}={r[k]} WHY excursions are magnitudes RULE mae/mfe>=0 WHERE {sid}")
        if r.get("partial_done"):
            v["partial_fired"].append(
                f"WHAT partial_done=True WHY partial is disabled [BE-ONLY] RULE no partials WHERE {sid}")
    for sid, n in close_counts.items():
        if n > 1:
            v["double_close"].append(
                f"WHAT closed {n}x WHY one position closes once RULE single close WHERE {sid}")

    state = _load(STATE, {})
    opens = state.get("open_trades") or {}
    if not isinstance(opens, dict):
        opens = {}
    open_rows = [t for t in opens.values() if isinstance(t, dict)] or \
                ([state["open_trade"]] if isinstance(state.get("open_trade"), dict) else [])
    for t in open_rows:
        sid, d = t.get("signal_id"), t.get("direction")
        entry, sl = float(t.get("entry") or 0), float(t.get("sl") or 0)
        if sid and close_counts.get(sid):
            v["closed_reactivated"].append(
                f"WHAT closed id open again WHY CLOSED->ACTIVE forbidden RULE terminal states stay terminal WHERE {sid}")
        if entry and sl and d in ("BUY", "SELL"):
            if (d == "BUY" and sl >= entry) or (d == "SELL" and sl <= entry):
                v["sl_wrong_side"].append(
                    f"WHAT {d} entry={entry} sl={sl} WHY SL on profit side WHY2 setup-SL vs position-SL RULE stop protects WHERE {sid}")

    # signal_memory cross-check: traded records must carry a close verdict
    mem = _load(MEMORY, {})
    if isinstance(mem, dict):
        for sym, rows in mem.items():
            for r in rows if isinstance(rows, list) else []:
                if r.get("traded") and r.get("trade_win") is None and r.get("trade_pnl") is None:
                    v["double_close"].append(  # bucketed as bookkeeping breach
                        f"WHAT traded without outcome WHY close never recorded RULE every open ends WHERE {sym}:{r.get('ts')}")

    try:
        src = open(BOT, encoding="utf-8").read()
        if GUARD not in src:
            v["widen_guard_missing"].append(
                "WHAT _tighter guard absent from bot.py WHY nothing else forbids widening RULE SL MAY ONLY TIGHTEN WHERE bot.py")
    except FileNotFoundError:
        v["widen_guard_missing"].append("WHAT bot.py unreadable WHERE " + BOT)

    return v, len(close_counts), len(open_rows)


def main():
    v, n_closed, n_open = audit()
    total = sum(len(x) for x in v.values())
    print(f"MGMT STATE AUDIT — {n_closed} closed ids, {n_open} open, "
          f"{total} violation(s) at {datetime.now(timezone.utc).isoformat()}")
    for inv in ("closed_reactivated", "double_close", "partial_fired",
                "sl_wrong_side", "negative_excursion", "widen_guard_missing"):
        rows = v.get(inv, [])
        print(f"  {inv:20s} {'ZERO ✓' if not rows else len(rows)}")
        for msg in rows[:10]:
            print(f"    {msg}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"ts": datetime.now(timezone.utc).isoformat(),
                   "closed": n_closed, "open": n_open, "violations": total,
                   "by_invariant": {k: len(x) for k, x in v.items()}}, f)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
