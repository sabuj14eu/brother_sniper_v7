#!/usr/bin/env python3
"""
Brother Sniper v7 — NIGHTLY EDGE ENGINE (read-only, run anytime / from cron)
============================================================================
The "auto-analytics" layer: every night, find which setups have real positive
expectancy — measured, shrunk, and honest — not just win/loss counts.

WHY SHRINKAGE (the whole point):
  A bucket with n=3 at 100% WR is almost always luck. Raw win-rate rewards
  small lucky samples and punishes large honest ones. So every bucket's win-rate
  is pulled toward the GLOBAL mean by a prior of K virtual trades (empirical
  Bayes), and every expectancy is reported at its one-standard-error LOWER bound.
  The result: a bucket only looks good here if it is good AND well-sampled.
  This is the discipline your PROVISIONAL flags were asking for, made automatic.

WHAT IT PRODUCES:
  1. Per-dimension best/worst (symbol, side, session, regime, score-band, RR-band,
     SL-band, hour, and setup-type/zone WHEN captured — auto-appears once the
     feature store lands).
  2. Top / bottom two-way COMBINATIONS (e.g. GOLD×SELL, ASIA×RANGE).
  3. Advisory per-setup WEIGHTS derived from shrunk lower-bound expectancy.
     ADVISORY ONLY — printed, never applied. Live weighting stays in
     weight_engine/discipline (Iron Rule 5 & 7: no auto risk change).

    python3 nightly_edge.py                 # human report
    python3 nightly_edge.py --json out.json # machine output for the dashboard

NOTHING is written to live state, NOTHING is traded. Reads learning/trades.jsonl.
Honors CLAUDE.md: R-multiples where possible, n<MIN_N flagged, measured not guessed.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sys

MIN_N = 20                 # below this a bucket is PROVISIONAL (still shown, flagged)
PRIOR_K = 6.0              # empirical-Bayes prior strength, in virtual trades
WEIGHT_LO, WEIGHT_HI = 0.30, 2.00   # same clamp the live weight_engine uses

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# ── data ─────────────────────────────────────────────────────────────────────

def load_trades():
    """Merged closed trades from the v7 journal (open+close joined by signal_id)."""
    try:
        from learning.trade_memory import load_all
        rows = load_all()
    except Exception:
        # standalone fallback: merge the jsonl ourselves
        rows = _merge_jsonl(os.path.join(HERE, "learning", "trades.jsonl"))
    return [t for t in rows
            if t.get("net_profit") is not None
            and "test" not in str(t.get("signal_id", "")).lower()]


def _merge_jsonl(path):
    opens, closes = {}, {}
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
                sid = r.get("signal_id", "")
                (opens if r.get("_type") == "open" else closes)[sid] = r
    except FileNotFoundError:
        return []
    out = []
    for sid, op in opens.items():
        row = dict(op)
        if sid in closes:
            row.update(closes[sid])
        out.append(row)
    return out


def r_multiple(t):
    """Realized R = net / dollar-risk. None when risk inputs are missing."""
    net = t.get("net_profit")
    bal = t.get("balance_at_open")
    risk = t.get("risk_pct")
    try:
        dr = float(bal) * float(risk)
        if net is None or dr <= 0:
            return None
        return float(net) / dr
    except (TypeError, ValueError):
        return None


def won(t):
    return bool(t.get("won")) if "won" in t else (t.get("net_profit", 0) or 0) > 0


# ── statistics: shrinkage + lower-bound expectancy ───────────────────────────

def shrunk_wr(wins, n, global_wr, k=PRIOR_K):
    """Empirical-Bayes win-rate: pulls small n toward the global mean."""
    if n <= 0:
        return global_wr
    return (wins + k * global_wr) / (n + k)


def ev_lower_bound(rs):
    """One-standard-error LOWER bound on mean R. Conservative expectancy:
    a bucket must be both profitable AND well-sampled to score positive."""
    n = len(rs)
    if n == 0:
        return None, None, 0
    mean = sum(rs) / n
    if n == 1:
        return mean, mean, 1
    var = sum((r - mean) ** 2 for r in rs) / (n - 1)
    se = math.sqrt(var / n)
    return mean, mean - se, n


def suggested_weight(ev_lcb, n):
    """ADVISORY setup weight from lower-bound expectancy. +0.5R LCB -> 1.5x,
    -0.5R -> 0.5x, clamped to the live engine's [0.30, 2.00]. Only meaningful
    at n>=MIN_N; below that we return None ('collecting')."""
    if ev_lcb is None or n < MIN_N:
        return None
    return round(max(WEIGHT_LO, min(1.0 + ev_lcb, WEIGHT_HI)), 2)


# ── bucketing ────────────────────────────────────────────────────────────────

def _band(v, edges):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    for lo, hi, lab in edges:
        if lo <= v < hi:
            return lab
    return None


def _hour(t):
    ts = t.get("timestamp_open") or ""
    return ts[11:13] + ":00" if len(ts) >= 13 else None


# dimension name -> extractor. Setup-type/zone auto-included when captured.
DIMENSIONS = {
    "symbol":   lambda t: t.get("symbol"),
    "side":     lambda t: t.get("direction"),
    "session":  lambda t: t.get("session"),
    "regime":   lambda t: t.get("regime"),
    "setup":    lambda t: t.get("setup_type") or t.get("type"),   # feature-store field
    "zone":     lambda t: t.get("zone") or t.get("loc_zone"),     # feature-store field
    "score":    lambda t: _band(t.get("ai_score"), [(0, 40, "<40"), (40, 55, "40-54"),
                                                     (55, 70, "55-69"), (70, 999, "70+")]),
    "rr":       lambda t: _band(t.get("rr"), [(0, 1.5, "<1.5"), (1.5, 2, "1.5-2"),
                                              (2, 3, "2-3"), (3, 99, ">3")]),
    "sl_pct":   lambda t: _sl_band(t),
    "hour":     _hour,
}


def _sl_band(t):
    e = t.get("entry") or 0
    sd = t.get("sl_distance") or 0
    if not (e and sd):
        return None
    p = 100 * sd / e
    return "<0.3%" if p < 0.3 else "0.3-0.6%" if p < 0.6 else "0.6-1%" if p < 1 else ">1%"


def summarize(trades, extractor, global_wr):
    buckets = collections.defaultdict(list)
    for t in trades:
        v = extractor(t)
        if v is not None:
            buckets[str(v)].append(t)
    out = []
    for label, ts in buckets.items():
        n = len(ts)
        wins = sum(1 for t in ts if won(t))
        rs = [r for r in (r_multiple(t) for t in ts) if r is not None]
        mean_r, lcb, r_n = ev_lower_bound(rs)
        out.append({
            "label": label, "n": n,
            "wr": round(100 * wins / n, 1),
            "swr": round(100 * shrunk_wr(wins, n, global_wr), 1),
            "net": round(sum(t.get("net_profit", 0) or 0 for t in ts), 2),
            "mean_r": round(mean_r, 3) if mean_r is not None else None,
            "ev_lcb": round(lcb, 3) if lcb is not None else None,
            "r_n": r_n,
            "weight": suggested_weight(lcb, n),
        })
    return out


# ── two-way combinations ─────────────────────────────────────────────────────

COMBO_DIMS = ["symbol", "side", "session", "regime", "setup", "zone"]


def combinations(trades, global_wr, min_n=8):
    dims = [d for d in COMBO_DIMS if any(DIMENSIONS[d](t) is not None for t in trades)]
    buckets = collections.defaultdict(list)
    for i in range(len(dims)):
        for j in range(i + 1, len(dims)):
            da, db = dims[i], dims[j]
            for t in trades:
                va, vb = DIMENSIONS[da](t), DIMENSIONS[db](t)
                if va is not None and vb is not None:
                    buckets[f"{da}={va} · {db}={vb}"].append(t)
    rows = []
    for label, ts in buckets.items():
        if len(ts) < min_n:
            continue
        wins = sum(1 for t in ts if won(t))
        rs = [r for r in (r_multiple(t) for t in ts) if r is not None]
        _, lcb, _ = ev_lower_bound(rs)
        rows.append({
            "label": label, "n": len(ts),
            "swr": round(100 * shrunk_wr(wins, len(ts), global_wr), 1),
            "net": round(sum(t.get("net_profit", 0) or 0 for t in ts), 2),
            "ev_lcb": round(lcb, 3) if lcb is not None else None,
        })
    rows.sort(key=lambda r: (r["ev_lcb"] if r["ev_lcb"] is not None else -9, r["net"]),
              reverse=True)
    return rows


# ── report ───────────────────────────────────────────────────────────────────

def build(trades):
    n = len(trades)
    wins = sum(1 for t in trades if won(t))
    global_wr = wins / n if n else 0.5
    rs = [r for r in (r_multiple(t) for t in trades) if r is not None]
    _, g_lcb, _ = ev_lower_bound(rs)
    report = {
        "n": n, "global_wr": round(100 * global_wr, 1),
        "net": round(sum(t.get("net_profit", 0) or 0 for t in trades), 2),
        "global_ev_lcb": round(g_lcb, 3) if g_lcb is not None else None,
        "dimensions": {}, "combinations": combinations(trades, global_wr),
    }
    for name, fn in DIMENSIONS.items():
        rows = summarize(trades, fn, global_wr)
        if rows:
            rows.sort(key=lambda r: (r["ev_lcb"] if r["ev_lcb"] is not None else -9, r["net"]),
                      reverse=True)
            report["dimensions"][name] = rows
    return report


def _fmt_rows(rows):
    print(f"    {'value':<16}{'n':>4}{'wr%':>6}{'shrunk':>8}{'meanR':>7}{'EV_lcb':>8}{'wt':>6}  flag")
    for r in rows:
        flag = "PROV" if r["n"] < MIN_N else ""
        w = "" if r["weight"] is None else f"{r['weight']:.2f}"
        mr = "" if r["mean_r"] is None else f"{r['mean_r']:+.2f}"
        lb = "" if r["ev_lcb"] is None else f"{r['ev_lcb']:+.2f}"
        print(f"    {r['label']:<16}{r['n']:>4}{r['wr']:>6}{r['swr']:>8}{mr:>7}{lb:>8}{w:>6}  {flag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write machine-readable report to this path")
    args = ap.parse_args()

    trades = load_trades()
    rep = build(trades)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
        print(f"wrote {args.json} ({rep['n']} trades)")
        return

    print("\n" + "=" * 74)
    print(f"NIGHTLY EDGE ENGINE   n={rep['n']}  WR={rep['global_wr']}%  "
          f"net={rep['net']}  global EV_lcb={rep['global_ev_lcb']}R")
    print("shrinkage: WR pulled toward global by K=%.0f virtual trades; "
          "EV_lcb = mean R minus 1 SE." % PRIOR_K)
    print("=" * 74)

    for name, rows in rep["dimensions"].items():
        print(f"\nBY {name.upper()}  (best EV_lcb first)")
        _fmt_rows(rows)

    print("\n" + "=" * 74)
    print("TOP COMBINATIONS (n>=8, ranked by lower-bound expectancy)")
    print("=" * 74)
    combos = rep["combinations"]
    for r in combos[:12]:
        lb = "" if r["ev_lcb"] is None else f"{r['ev_lcb']:+.2f}R"
        print(f"  {r['label']:<44} n={r['n']:<4} sWR={r['swr']:>5}%  {lb:>7}  net={r['net']:+.2f}")
    if len(combos) > 12:
        print("\nBOTTOM COMBINATIONS")
        for r in combos[-6:]:
            lb = "" if r["ev_lcb"] is None else f"{r['ev_lcb']:+.2f}R"
            print(f"  {r['label']:<44} n={r['n']:<4} sWR={r['swr']:>5}%  {lb:>7}  net={r['net']:+.2f}")

    print("\n" + "=" * 74)
    print("ADVISORY SETUP WEIGHTS (from shrunk lower-bound expectancy)")
    print("weights are DISPLAY-ONLY — live weighting stays in weight_engine/discipline")
    print("=" * 74)
    for dim in ("setup", "zone", "symbol", "side"):
        rows = [r for r in rep["dimensions"].get(dim, []) if r["weight"] is not None]
        if rows:
            print(f"\n  by {dim}:")
            for r in rows:
                print(f"    {r['label']:<16} weight = {r['weight']:.2f}   (n={r['n']}, EV_lcb {r['ev_lcb']:+.2f}R)")
    if not any(rep["dimensions"].get(d) for d in ("setup", "zone")):
        print("\n  setup-type / zone weights: NOT YET AVAILABLE — those features are not")
        print("  captured in trades.jsonl yet. Add them in the feature-store stage")
        print("  (docs/STRATEGY_INTELLIGENCE.md) and they appear here automatically.")


if __name__ == "__main__":
    main()
