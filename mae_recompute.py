#!/usr/bin/env python3
"""Exact MAE/MFE for closed trades, replayed from M1 candles (read-only, $0).

The live monitor samples open positions every 60 seconds (bot.py:451), so
the recorded MAE/MFE are the worst and best moments it HAPPENED TO SEE —
systematically understating both. mae_study.py says so out loud, and every
"is our stop too tight?" answer rests on those numbers.

This replays each closed trade minute by minute between its open and close
and stores the true extremes beside the sampled ones. It never edits
learning/trades.jsonl — that journal is append-only, so the recomputed
values go to a sidecar keyed by signal_id, and the two columns keep each
other honest: a large gap is itself the evidence that sampling was lossy.

Direction matters and is not symmetric:
    BUY   MAE = entry - lowest low     MFE = highest high - entry
    SELL  MAE = highest high - entry   MFE = entry - lowest low
Both are reported in price and in R (÷ sl_distance), never mixed.

Missing candles produce NOTHING for that trade — the sampled value stands
alone rather than being quietly replaced by a worse-informed guess.

Usage:
    python3 mae_recompute.py                 # replay + comparison summary
    python3 mae_recompute.py --json out.json
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(BASE, "learning", "mae_m1.jsonl")
TF_M1 = "1"
MAX_BARS = 5000
PAD_MIN = 2          # a little slack around the fill/close timestamps


def _ts(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v / 1000 if v > 4102444800 else v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def closed_trades(rows: list[dict]) -> list[dict]:
    """Merged trade rows that actually closed and carry what a replay needs."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or r.get("net_profit") is None:
            continue
        t_open, t_close = _ts(r.get("timestamp_open")), _ts(r.get("timestamp_close"))
        entry = _f(r.get("entry"))
        side = str(r.get("direction") or "").upper()
        if not (t_open and t_close and entry and side in ("BUY", "SELL")):
            continue
        if t_close <= t_open:
            continue
        out.append(r)
    return out


def excursions(trade: dict, rows: list[dict]) -> dict | None:
    """True MAE/MFE from the bars the trade was actually open for.
    None when the window has no candles — never a guess."""
    t_open, t_close = _ts(trade["timestamp_open"]), _ts(trade["timestamp_close"])
    entry = _f(trade["entry"])
    side = str(trade["direction"]).upper()
    lo = t_open - PAD_MIN * 60
    hi = t_close + PAD_MIN * 60
    window = [r for r in rows or [] if lo <= r.get("t", 0) <= hi]
    if not window:
        return None
    low = min(r["l"] for r in window)
    high = max(r["h"] for r in window)
    if side == "BUY":
        mae, mfe = entry - low, high - entry
    else:
        mae, mfe = high - entry, entry - low
    mae, mfe = max(0.0, mae), max(0.0, mfe)
    sl_dist = _f(trade.get("sl_distance"))
    out = {
        "signal_id": trade.get("signal_id"), "symbol": trade.get("symbol"),
        "direction": side, "entry": entry,
        "bars": len(window),
        "mae_m1": round(mae, 6), "mfe_m1": round(mfe, 6),
        "mae_sampled": _f(trade.get("mae")), "mfe_sampled": _f(trade.get("mfe")),
        "won": trade.get("won"), "session": trade.get("session"),
        "timestamp_open": trade.get("timestamp_open"),
    }
    if sl_dist and sl_dist > 0:
        out["mae_r"] = round(mae / sl_dist, 3)
        out["mfe_r"] = round(mfe / sl_dist, 3)
    return out


def understatement(rows: list[dict]) -> dict:
    """How much the 60s sampling missed, over trades where both exist.
    This is the number that says whether the sampled column can be trusted."""
    pairs = [(r["mae_m1"], r["mae_sampled"], r["mfe_m1"], r["mfe_sampled"])
             for r in rows or []
             if r.get("mae_sampled") is not None and r.get("mfe_sampled") is not None]
    if not pairs:
        return {"n": 0, "mae_missed_avg": None, "mfe_missed_avg": None,
                "mae_worse_pct": None}
    mae_gap = [a - b for a, b, _, _ in pairs]
    mfe_gap = [c - d for _, _, c, d in pairs]
    worse = sum(1 for g in mae_gap if g > 1e-9)
    return {
        "n": len(pairs),
        "mae_missed_avg": round(sum(mae_gap) / len(mae_gap), 6),
        "mfe_missed_avg": round(sum(mfe_gap) / len(mfe_gap), 6),
        "mae_worse_pct": round(worse / len(pairs) * 100, 1),
    }


def stop_headroom(rows: list[dict]) -> dict:
    """Of the trades that WON, how close did they come to the stop? A pile of
    winners with MAE_R near 1.0 is the evidence a stop is too tight — and a
    pile of losers that never reached +1R says the opposite. Reported as
    counts; the decision stays human (Iron Rule 7)."""
    winners = [r["mae_r"] for r in rows or []
               if r.get("won") and r.get("mae_r") is not None]
    losers = [r["mfe_r"] for r in rows or []
              if r.get("won") is False and r.get("mfe_r") is not None]
    return {
        "winners_n": len(winners),
        "winners_max_mae_r": round(max(winners), 3) if winners else None,
        "winners_near_stop": sum(1 for r in winners if r >= 0.8),
        "losers_n": len(losers),
        "losers_reached_1r": sum(1 for r in losers if r >= 1.0),
        "provisional": len(winners) + len(losers) < 20,
    }


def run(trades: list[dict], candles_for) -> list[dict]:
    out = []
    for t in trades:
        got = excursions(t, candles_for(t.get("symbol")))
        if got:
            out.append(got)
    return out


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    try:
        from learning.trade_memory import load_all
        trades = closed_trades(load_all())
    except Exception as e:
        print(f"cannot read the trade journal: {e}")
        return 1
    if not trades:
        print("no closed trades with the fields a replay needs yet")
        return 0
    from v7_counterfactual import bridge_candles, make_candle_cache
    cache = make_candle_cache(lambda s, tf=TF_M1, n=MAX_BARS:
                              bridge_candles(s, TF_M1, MAX_BARS))
    rows = run(trades, cache)
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")

    u, h = understatement(rows), stop_headroom(rows)
    print(f"recomputed {len(rows)} of {len(trades)} closed trades -> {OUT_FILE}")
    if u["n"]:
        print(f"  sampling missed on average: MAE {u['mae_missed_avg']} · "
              f"MFE {u['mfe_missed_avg']} (worse MAE on {u['mae_worse_pct']}% of trades)")
    print(f"  winners n={h['winners_n']} · {h['winners_near_stop']} came within "
          f"0.2R of the stop · worst {h['winners_max_mae_r']}R")
    print(f"  losers  n={h['losers_n']} · {h['losers_reached_1r']} had reached +1R "
          f"before losing"
          + ("   [PROVISIONAL n<20]" if h["provisional"] else ""))
    print("  Evidence for a human stop/TP decision — nothing here changes a level.")
    if "--json" in argv:
        with open(argv[argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump({"rows": rows, "understatement": u, "headroom": h},
                      f, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
