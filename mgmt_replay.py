#!/usr/bin/env python3
"""Management replay harness (Week-2, 2026-08-31) — read-only.

Compares management policies over CLOSED trades that carry MAE/MFE:
    ENTRY ONLY      fixed SL, fixed TP, no management
    BREAKEVEN +1R   v7's live policy (SL to BE once +1R is reached)
    TP1 PROTECTION / STRUCTURE TRAIL / RUNNER / NEWS-AWARE -> UNKNOWN:
    they need the price PATH, and the monitor records only sampled
    MAE/MFE extremes. UNKNOWN is the honest verdict, never a guess.

HONESTY: MAE/MFE are ~60s samples, so the ORDER of excursions inside a
trade is unknowable. Where the order decides the outcome (stop hit AND
TP reached, or BE reached AND stop reached) the trade is AMBIGUOUS and
the harness reports BEST/WORST bounds instead of a point estimate.

The rule this harness serves: SL MAY ONLY TIGHTEN, NEVER WIDEN
(enforced live by bot.py's _tighter guard; audited by audit_mgmt_state).

    python3 mgmt_replay.py          # nothing written, nothing traded
"""
from __future__ import annotations

import json
import sys

from mae_study import load_merged_trades

MIN_N = 20


def _r(t):
    """Per-trade geometry in R, or None if not studyable."""
    risk, tp_d = t.get("sl_distance"), t.get("tp_distance")
    mae, mfe = t.get("mae"), t.get("mfe")
    if not risk or risk <= 0 or not tp_d or tp_d <= 0 or mae is None or mfe is None:
        return None
    return {"tp_r": float(tp_d) / float(risk), "mae_r": float(mae) / float(risk),
            "mfe_r": float(mfe) / float(risk)}


def entry_only(g):
    """(best_r, worst_r, tag). Fixed SL/TP, no management."""
    stopped, hit_tp = g["mae_r"] >= 1.0, g["mfe_r"] >= g["tp_r"]
    if stopped and hit_tp:
        return g["tp_r"], -1.0, "AMBIGUOUS (order unknown)"
    if stopped:
        return -1.0, -1.0, "STOPPED"
    if hit_tp:
        return g["tp_r"], g["tp_r"], "TP"
    return None, None, "UNDECIDED (neither extreme reached)"


def breakeven_1r(g):
    """(best_r, worst_r, tag). SL to BE once +1R prints — v7 live policy."""
    reached_be = g["mfe_r"] >= 1.0
    if not reached_be:
        return entry_only(g)                 # BE never armed; identical trade
    stopped, hit_tp = g["mae_r"] >= 1.0, g["mfe_r"] >= g["tp_r"]
    if stopped and hit_tp:
        return g["tp_r"], -1.0, "AMBIGUOUS (order unknown)"
    if stopped:                              # stop level reached, but was BE in?
        return 0.0, -1.0, "AMBIGUOUS (BE vs stop order unknown)"
    if hit_tp:                               # could still have BE'd on a retrace
        return g["tp_r"], 0.0, "AMBIGUOUS (retrace-to-BE unknown)"
    return 0.0, 0.0, "BE EXIT (armed, TP unreached)"


POLICIES = [("ENTRY ONLY", entry_only), ("BREAKEVEN +1R", breakeven_1r)]
UNKNOWN_POLICIES = ["TP1 PROTECTION", "STRUCTURE TRAIL", "RUNNER",
                    "NEWS-AWARE MANAGEMENT"]


def replay(done):
    out = {}
    for name, fn in POLICIES:
        best = worst = 0.0
        n = und = amb = 0
        for t in done:
            g = _r(t)
            if g is None:
                continue
            b, w, tag = fn(g)
            if b is None:
                und += 1
                continue
            n += 1
            best += b
            worst += w
            amb += tag.startswith("AMBIGUOUS")
        out[name] = {"n": n, "undecided": und, "ambiguous": amb,
                     "net_r_best": round(best, 1), "net_r_worst": round(worst, 1),
                     "exp_best": round(best / n, 3) if n else None,
                     "exp_worst": round(worst / n, 3) if n else None}
    return out


def main():
    done = load_merged_trades()
    res = replay(done)
    print("MANAGEMENT REPLAY (bounds, not points — sampled MAE/MFE cannot order events)")
    for name, r in res.items():
        strength = "MEASURED" if r["n"] >= 100 else ("n>=20" if r["n"] >= MIN_N else "LUCK (n<20)")
        print(f"  {name:16s} n={r['n']:<4d} [{strength}] netR {r['net_r_worst']}..{r['net_r_best']} "
              f"exp {r['exp_worst']}..{r['exp_best']} ambiguous={r['ambiguous']} undecided={r['undecided']}")
    for name in UNKNOWN_POLICIES:
        print(f"  {name:16s} UNKNOWN — needs price path; monitor records extremes only")
    print("RULE: SL MAY ONLY TIGHTEN, NEVER WIDEN (live guard: bot.py _tighter; see audit_mgmt_state.py)")
    if all(r["n"] < MIN_N for r in res.values()):
        print("VERDICT: n<20 everywhere — LUCK. No management change is arguable from this data yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
