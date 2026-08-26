"""Conditional profile — "under WHICH conditions is this asset bad?" (2026-08-24)

Shyam's adaptive-gates principle (docs/ADAPTIVE_GATES_SPEC.md): a gate
should protect the bot, not blind it. "GOLD loses" is a label; "GOLD
loses counter-trend in Asia at poor entry distance, and wins trend-
aligned in NY at A-grade retests" is intelligence — IF the cells are
measured, and UNKNOWN when they are not.

READ MODEL ONLY. This module reads the unified feature store
(telemetry opens + journal outcomes, joined by signal_id) and answers
with historical cells. It never gates, sizes, or touches an order.
The path to production is fixed by the spec and the constitution:
  OFFLINE REPORT (this file, runnable today, read-only)
  -> SHADOW wiring (logs what an adaptive gate WOULD say, blocks nothing)
  -> EVIDENCE REVIEW (n floors, both populations)
  -> EXPLICIT HUMAN APPROVAL -> the existing CAUTION mechanisms
     (ASSET_GATE_SIZE multiplier / cluster scale), deploy ceremony.
Never: yesterday-bad -> AI edits gate -> today-trades.

HIERARCHICAL BACKOFF — the honest answer machine: ask the most specific
cell first (symbol+side+aligned+session+grade+distance+news); if its
RESOLVED n is under the floor, drop the least important dimension and
ask again; report WHICH level answered. A specific cell that is UNKNOWN
never borrows confidence from a broad one without saying so.

CLI (read-only, safe on the box any time):
    python3 -m learning.conditional_profile GOLD
"""
from __future__ import annotations

import sys

FLOOR = 20            # Evidence Law: n<20 is luck
MEASURED_N = 100      # ~100 to judge

DIST_EDGES = [(0.0, 0.5, "<=0.5"), (0.5, 1.0, "0.5-1"), (1.0, 1.5, "1-1.5"),
              (1.5, 3.0, "1.5-3"), (3.0, 1e9, ">3")]


def dist_bucket(v):
    if v is None:
        return "UNKNOWN"
    for lo, hi, label in DIST_EDGES:
        if lo <= v < hi:
            return label
    return "UNKNOWN"


def grade_band(g):
    g = str(g or "").upper().strip()
    if g in ("A+", "A"):
        return "A"
    if g == "B":
        return "B"
    if g in ("C", "D"):
        return "C-D"
    return "UNKNOWN"


def news_band(mins):
    if mins is None:
        return "UNKNOWN"
    try:
        m = abs(float(mins))
    except (TypeError, ValueError):
        return "UNKNOWN"
    return "NEWS<30m" if m <= 30 else "NEWS<120m" if m <= 120 else "QUIET"


def aligned_of(row):
    side = str(row.get("side") or "").upper()
    ht = str(row.get("htf_align") or "").upper()
    if side not in ("BUY", "SELL") or ht in ("", "RANGE", "NONE"):
        return "UNKNOWN"
    if ("UP" in ht and side == "BUY") or ("DOWN" in ht and side == "SELL"):
        return "WITH-TREND"
    return "AGAINST-TREND"


def context_of(row):
    """The condition key of one unified row — every dim honest-UNKNOWN."""
    return {
        "symbol": str(row.get("symbol") or "?").upper(),
        "side": str(row.get("side") or "UNKNOWN").upper(),
        "aligned": aligned_of(row),
        "session": str(row.get("session") or "UNKNOWN").upper(),
        "grade": grade_band(row.get("grade")),
        "dist": dist_bucket(row.get("entry_dist_atr")),
        "news": news_band(row.get("news_minutes")),
    }


def _r_of(row):
    """Outcome in R when resolvable: net vs risked amount, else None."""
    if row.get("r") is not None:
        return row["r"]
    net = row.get("net_profit")
    bal, risk = row.get("balance_at_open"), row.get("risk_pct")
    try:
        risked = float(bal) * float(risk)
        return float(net) / risked if risked > 0 else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def cell_stats(rows):
    rs = [r for r in (_r_of(x) for x in rows) if r is not None]
    n = len(rs)
    wins = sum(1 for r in rs if r > 0)
    return {"n": n, "wins": wins, "losses": sum(1 for r in rs if r < 0),
            "win_rate": round(wins / n * 100, 1) if n else None,
            "expectancy_r": round(sum(rs) / n, 3) if n else None,
            "strength": ("MEASURED" if n >= MEASURED_N else
                         "DEVELOPING" if n >= FLOOR else "LUCK-ZONE")}


# Backoff order: drop the least load-bearing dimension first. Alignment
# survives longest (the #1 documented loss driver), then symbol.
BACKOFF = ["news", "grade", "dist", "session", "side", "aligned"]


def profile_verdict(rows, ctx):
    """The most specific historical cell for ctx with resolved n>=FLOOR.

    Returns {level, dims, stats, verdict} where verdict is INFORMATIONAL:
      POSITIVE CELL  n>=FLOOR and expectancy > 0
      NEGATIVE CELL  n>=FLOOR and expectancy <= 0
      UNKNOWN        no cell at any level reaches the floor
    Nothing here is a gate: the spec's ALLOW/CAUTION/BLOCK mapping happens
    only after shadow + review + explicit approval."""
    dims = ["symbol", "side", "aligned", "session", "grade", "dist", "news"]
    for level in range(len(BACKOFF) + 1):
        active = [d for d in dims if d == "symbol" or d not in BACKOFF[:level]]
        got = [r for r in rows
               if all(context_of(r)[d] == ctx.get(d) for d in active)]
        st = cell_stats(got)
        if st["n"] >= FLOOR:
            verdict = ("POSITIVE CELL" if st["expectancy_r"] is not None
                       and st["expectancy_r"] > 0 else "NEGATIVE CELL")
            return {"level": level, "dims": active, "stats": st,
                    "verdict": verdict,
                    "note": ("exact condition" if level == 0 else
                             f"backed off {level} dim(s): "
                             f"{', '.join(BACKOFF[:level])} ignored")}
    return {"level": None, "dims": ["symbol"], "stats": cell_stats(
                [r for r in rows if context_of(r)["symbol"] == ctx.get("symbol")]),
            "verdict": "UNKNOWN",
            "note": f"no cell reaches n>={FLOOR} — do not pretend this is proven"}


def symbol_report(rows, symbol):
    """The Shyam-§3 breakdown: marginals + alignment x session, printable."""
    sym = symbol.upper()
    mine = [r for r in rows if context_of(r)["symbol"] == sym]
    out = {"symbol": sym, "overall": cell_stats(mine), "cuts": {}}
    for dim in ("aligned", "session", "grade", "dist", "news", "side"):
        vals = {}
        for r in mine:
            vals.setdefault(context_of(r)[dim], []).append(r)
        out["cuts"][dim] = {k: cell_stats(v) for k, v in sorted(vals.items())}
    combo = {}
    for r in mine:
        c = context_of(r)
        combo.setdefault((c["aligned"], c["session"]), []).append(r)
    out["cuts"]["aligned x session"] = {f"{a} / {s}": cell_stats(v)
                                        for (a, s), v in sorted(combo.items())}
    return out


def _fmt(stats):
    e = stats["expectancy_r"]
    return (f"n={stats['n']:<4} wr={stats['win_rate'] or '—':<5} "
            f"exp={('%+.3f' % e) + 'R' if e is not None else '—':<9} {stats['strength']}")


def main():
    from learning.telemetry import load_unified
    symbol = (sys.argv[1] if len(sys.argv) > 1 else "GOLD")
    rep = symbol_report(load_unified(), symbol)
    print(f"CONDITIONAL PROFILE — {rep['symbol']} (read-only; gates nothing)")
    print(f"  OVERALL          {_fmt(rep['overall'])}")
    for dim, cells in rep["cuts"].items():
        print(f"  by {dim}:")
        for k, st in cells.items():
            print(f"    {k:<24} {_fmt(st)}")
    print(f"  Evidence Law: n<{FLOOR} is luck; ~{MEASURED_N} to judge. "
          f"UNKNOWN cells stay UNKNOWN.")


if __name__ == "__main__":
    main()
