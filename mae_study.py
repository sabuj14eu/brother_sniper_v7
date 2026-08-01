#!/usr/bin/env python3
"""
Brother Sniper v7 — MAE STOP-DISTANCE STUDY (read-only, run anytime)
====================================================================
The study that settles whether tight stops lose because they're TIGHT, or
because they were attached to BAD trades.

For every closed trade that has MAE/MFE data, replay it against stop
distances 1.0 / 1.2 / 1.5 / 2.0 x ATR:
    survived  = MAE  < stop distance      (drawdown never touched that stop)
    hit TP    = MFE >= recorded TP distance
    R at stop = +tp_dist/stop_dist if survived & hit TP, -1.0 if stopped,
                UNDECIDED if survived but never reached TP (excluded from R,
                counted separately — honesty over completeness).

Also prints the TASK-1 DIAGNOSTIC: how many closed trades carry MAE at all,
and the evidence rows where MFE exceeded 1R of the ACTUAL stop (trades where
breakeven SHOULD have fired if +1R detection worked).

    python3 mae_study.py

NOTHING is written, NOTHING is traded. Pure analysis.
HONESTY: every bucket shows n; n<20 is PROVISIONAL. MAE/MFE are sampled by
the monitor every ~60s, so both are UNDERSTATED — intrabar spikes between
samples are invisible. Survival rates here are therefore OPTIMISTIC bounds.
"""
import collections
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TRADES = os.path.join(HERE, "learning", "trades.jsonl")
MIN_N = 20
MULTS = (1.0, 1.2, 1.5, 2.0)


def load_merged_trades(path=TRADES):
    """Merge open+close rows by signal_id (scorecard pattern)."""
    trades = collections.OrderedDict()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                sid = r.get("signal_id")
                if not sid:
                    continue
                rec = trades.setdefault(sid, {})
                for k, v in r.items():
                    if v is not None:
                        rec[k] = v
    except FileNotFoundError:
        pass
    done = [t for t in trades.values()
            if ("won" in t or "net_profit" in t)
            and "test" not in str(t.get("signal_id", "")).lower()]
    return done


def replay_at_stop(t, mult):
    """Replay one trade at stop = mult * ATR. Returns dict or None if not studyable."""
    atr = t.get("atr")
    mae = t.get("mae")
    mfe = t.get("mfe")
    tp_dist = t.get("tp_distance")
    if not atr or atr <= 0 or mae is None or mfe is None or not tp_dist or tp_dist <= 0:
        return None
    stop = mult * float(atr)
    if stop <= 0:
        return None
    survived = float(mae) < stop
    hit_tp = float(mfe) >= float(tp_dist)
    if not survived:
        r = -1.0
    elif hit_tp:
        r = float(tp_dist) / stop
    else:
        r = None  # survived but TP unreached in the recorded excursion
    return {"survived": survived, "hit_tp": hit_tp, "r": r}


def study(done, mults=MULTS):
    out = {}
    for m in mults:
        rows = [x for x in (replay_at_stop(t, m) for t in done) if x is not None]
        n = len(rows)
        surv = sum(1 for x in rows if x["survived"])
        tp = sum(1 for x in rows if x["survived"] and x["hit_tp"])
        decided = [x["r"] for x in rows if x["r"] is not None]
        out[m] = {
            "n": n,
            "survived": surv,
            "surv_pct": round(100 * surv / n, 1) if n else None,
            "tp_hits": tp,
            "undecided": sum(1 for x in rows if x["r"] is None),
            "avg_r": round(sum(decided) / len(decided), 3) if decided else None,
            "net_r": round(sum(decided), 1) if decided else None,
        }
    return out


def task1_evidence(done):
    """Rows where MFE >= 1R of the ACTUAL stop -> BE should have fired."""
    rows = []
    for t in done:
        mfe = t.get("mfe")
        sl_dist = t.get("sl_distance")
        if mfe is None or not sl_dist or sl_dist <= 0:
            continue
        if float(mfe) >= float(sl_dist):
            rows.append({
                "signal_id": t.get("signal_id"),
                "symbol": t.get("symbol"),
                "direction": t.get("direction"),
                "sl_distance": sl_dist,
                "mfe": mfe,
                "mfe_R": round(float(mfe) / float(sl_dist), 2),
                "won": t.get("won", (t.get("net_profit", 0) or 0) > 0),
            })
    return rows


def main():
    done = load_merged_trades()
    print(f"\nMAE STOP-DISTANCE STUDY   {datetime.now(timezone.utc).isoformat()}")
    print(f"closed trades: {len(done)}")
    with_mae = [t for t in done if t.get("mae") is not None]
    with_atr = [t for t in with_mae if t.get("atr") and t.get("tp_distance")]
    print(f"with MAE/MFE data: {len(with_mae)}   studyable (MAE+ATR+TPdist): {len(with_atr)}")
    print("NOTE: MAE/MFE sampled every ~60s -> understated; survival is an OPTIMISTIC bound.\n")

    # ── TASK-1 DIAGNOSTIC ──────────────────────────────────────────────────
    print("=" * 72)
    print("TASK-1 DIAGNOSTIC — did any trade actually reach +1R while monitored?")
    print("=" * 72)
    if not with_mae:
        print("  ZERO closed trades carry MAE/MFE. The monitor's price source")
        print("  (price_current from the bridge /positions) is NOT flowing -> the")
        print("  +1R breakeven branch can never trigger either. Answer: (b) broken")
        print("  detection — wrong/missing price source. Check the bridge payload.")
    else:
        ev = task1_evidence(done)
        print(f"  trades whose MFE reached >=1R of their actual stop: {len(ev)}")
        if ev:
            print("  -> BE SHOULD have fired on these. If logs show no [BE] lines for")
            print("     them, detection is broken (b). If [BE] lines exist, the zero is")
            print("     a JOURNAL gap (be_done never written to trades.jsonl).")
            print(f"\n  {'signal_id':<44}{'sym':<10}{'dir':<5}{'MFE_R':>6}  won")
            for r in ev[:20]:
                print(f"  {str(r['signal_id'])[:43]:<44}{str(r['symbol']):<10}"
                      f"{str(r['direction']):<5}{r['mfe_R']:>6}  {r['won']}")
            if len(ev) > 20:
                print(f"  ... and {len(ev)-20} more")
        else:
            print("  -> none. Answer: (a) no monitored trade ever reached +1R —")
            print("     the zeros are real market behavior, not a bug.")

    # ── STOP-DISTANCE REPLAY ───────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("STOP-DISTANCE REPLAY (per ATR multiplier)")
    print("=" * 72)
    res = study(done)
    print(f"  {'stop':<10}{'n':>5}{'surv%':>8}{'TP hits':>9}{'undecided':>11}{'avgR':>8}{'netR':>8}  flag")
    for m, s in res.items():
        flag = "PROVISIONAL" if (s["n"] or 0) < MIN_N else ""
        print(f"  {m:<10}{s['n']:>5}{str(s['surv_pct']):>8}{s['tp_hits']:>9}"
              f"{s['undecided']:>11}{str(s['avg_r']):>8}{str(s['net_r']):>8}  {flag}")
    print("\n  Read: if surv% rises sharply from 1.0x to 1.5x AND avgR holds, tight")
    print("  stops were dying on noise (widen). If surv% rises but avgR falls toward")
    print("  zero, the trades were bad regardless of stop (strategy, not stop width).")


if __name__ == "__main__":
    main()
