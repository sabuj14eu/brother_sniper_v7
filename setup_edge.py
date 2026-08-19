#!/usr/bin/env python3
"""Setup Edge — realized edge for COMBINATIONS of conditions (read-only, $0).

`gate_effectiveness.by_dimension` answers "how does v7 do in LONDON?" and
"how does it do on SILVER?". It cannot answer the question the desk actually
asks: "how does it do BUYING SILVER in LONDON?" — the one-dimensional views
average that away. This module cuts the same realized trades by 2-3 stored
fields at once.

WHAT IT IS NOT: a trading rule. A combination that looks good here is a
hypothesis, nothing more — the sample shrinks with every dimension added,
which is exactly how a spurious edge is manufactured. So:

  * The statistics are NOT reimplemented here. bucket_stats, cluster_verdict
    and MIN_N are imported from gate_effectiveness, so one number can never
    be computed two ways (test_setup_edge.py pins the R formula to theirs).
  * Buckets below MIN_N read UNPROVEN, however pretty the win rate is.
    n=3 at 100% WR is not an edge, it is three trades.
  * Nothing is dropped silently. Buckets too thin to display are COUNTED in
    `hidden_thin`, and a truncated family reports `truncated`.
  * `coverage_pct` says how many rows even HAD the fields — a family built
    on telemetry that only started recording last week must read
    "not instrumented yet", never "no edge found".

Usage:
    python3 setup_edge.py                  # table
    python3 setup_edge.py --json out.json
    python3 setup_edge.py --family symbol_side
"""
from __future__ import annotations

import json
import sys

from gate_effectiveness import MIN_N, bucket_stats, cluster_verdict

# A bucket below this is not rendered as its own row (it would be one trade
# per line, thousands of lines). It is still COUNTED — see hidden_thin.
MIN_SHOW = 3
# Per-family row cap, so one page cannot be flooded. Reported as `truncated`.
TOP_N = 40

# Stored field -> the aliases a row may actually carry. load_unified joins
# telemetry (side/setup_type) with the trade journal (direction/type), and
# older rows predate the telemetry schema entirely.
_ALIASES = {
    "side": ("side", "direction"),
    "symbol": ("symbol",),
    "session": ("session",),
    "grade": ("grade",),
    "setup_type": ("setup_type", "type", "strategy_id"),
    "regime": ("regime",),
    "htf_align": ("htf_align",),
    "zone": ("zone", "loc_zone"),
}

# The combinations worth asking about, in order of how much sample each can
# realistically hold. Deeper cuts are kept deliberately few: every extra
# dimension divides the sample, and an UNPROVEN row is all a 3-way cut can
# honestly produce at this trade count.
FAMILIES = [
    {"name": "session_side", "dims": ("session", "side"),
     "title": "session x direction"},
    {"name": "symbol_side", "dims": ("symbol", "side"),
     "title": "symbol x direction"},
    {"name": "symbol_session", "dims": ("symbol", "session"),
     "title": "symbol x session"},
    {"name": "grade_side", "dims": ("grade", "side"),
     "title": "grade x direction"},
    {"name": "setup_side", "dims": ("setup_type", "side"),
     "title": "setup x direction"},
    {"name": "setup_session", "dims": ("setup_type", "session"),
     "title": "setup x session"},
    {"name": "regime_side", "dims": ("regime", "side"),
     "title": "regime x direction"},
    {"name": "symbol_side_session", "dims": ("symbol", "side", "session"),
     "title": "symbol x direction x session"},
]


def row_r(row: dict):
    """One trade's outcome in R. Mirrors gate_effectiveness.kept_lane exactly —
    net profit over the cash that was actually risked at open. None when the
    row cannot support the arithmetic; never a guess.

    test_setup_edge.py asserts this agrees with kept_lane over the same rows,
    so the two cannot drift apart unnoticed."""
    try:
        net = float(row["net_profit"])
        bal = float(row["balance_at_open"])
        rp = float(row["risk_pct"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (bal > 0 and rp > 0):
        return None
    return net / (bal * rp)


def _val(row: dict, dim: str):
    """The row's value for one dimension, or None if it never recorded it.
    Empty strings count as missing — a blank is absence, not a category."""
    for name in _ALIASES.get(dim, (dim,)):
        v = row.get(name)
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in ("none", "null", "unknown", "-", "—"):
            return s.upper()
    return None


def by_combo(rows: list, dims: tuple, min_show: int = MIN_SHOW,
             top_n: int = TOP_N) -> dict:
    """Realized edge for one combination of stored fields.

    Rows missing ANY dimension are not bucketed — they are counted in
    `uncovered`, because "we never recorded the setup type" and "this setup
    has no edge" are different facts and must never render as the same row."""
    buckets: dict = {}
    scored = uncovered = 0
    for row in rows or []:
        r = row_r(row)
        if r is None:
            continue                     # open trade or unusable row
        scored += 1
        parts = [_val(row, d) for d in dims]
        if any(p is None for p in parts):
            uncovered += 1
            continue
        buckets.setdefault(tuple(parts), []).append(r)

    out = []
    hidden_thin = hidden_n = 0
    for key, rs in buckets.items():
        if len(rs) < min_show:
            hidden_thin += 1
            hidden_n += len(rs)
            continue
        stats = bucket_stats(rs)
        out.append({
            "key": " · ".join(key),
            "parts": dict(zip(dims, key)),
            **stats,
            "verdict": cluster_verdict(stats),
        })
    out.sort(key=lambda r: (-r["n"], r["key"]))
    truncated = max(0, len(out) - top_n)
    covered = scored - uncovered
    return {
        "dims": list(dims),
        "rows": out[:top_n],
        "buckets": len(buckets),
        "scored": scored,
        "uncovered": uncovered,
        "coverage_pct": round(covered / scored * 100, 1) if scored else None,
        "hidden_thin": hidden_thin,
        "hidden_thin_rows": hidden_n,
        "min_show": min_show,
        "truncated": truncated,
        "proven": sum(1 for r in out if r["verdict"] != "UNPROVEN"),
    }


def setup_edge(unified_rows: list, families: list | None = None) -> dict:
    """Every family, keyed by name. Families whose fields were never recorded
    still appear — with coverage_pct 0 — so the desk shows a blind spot as a
    blind spot."""
    fams = families if families is not None else FAMILIES
    return {
        "min_n": MIN_N,
        "families": [
            {"name": f["name"], "title": f["title"],
             **by_combo(unified_rows, f["dims"])}
            for f in fams
        ],
        "note": ("Realized trades cut by 2-3 recorded fields at once. Each "
                 "added dimension divides the sample, so most rows are "
                 f"UNPROVEN by design (n<{MIN_N} is luck). coverage_pct is "
                 "how many trades even recorded those fields: low coverage "
                 "means NOT MEASURED, not 'no edge'. Evidence for a human — "
                 "no rule reads this file."),
    }


def _print(report: dict, only: str | None = None) -> None:
    for fam in report["families"]:
        if only and fam["name"] != only:
            continue
        head = (f"{fam['title'].upper()}  —  coverage {fam['coverage_pct']}% "
                f"({fam['scored'] - fam['uncovered']}/{fam['scored']} trades)")
        print("\n" + head)
        if not fam["rows"]:
            reason = ("no trade recorded these fields yet"
                      if not fam["coverage_pct"] else
                      f"every bucket below n={fam['min_show']}")
            print(f"  — nothing to show ({reason}; "
                  f"{fam['hidden_thin']} thin buckets held back)")
            continue
        print(f"  {'combination':<34}{'n':>5}{'WR':>8}{'PF':>7}{'exp':>9}"
              f"  verdict")
        for r in fam["rows"]:
            wr = f"{r['win_rate']}%" if r["win_rate"] is not None else "—"
            pf = str(r["pf"]) if r["pf"] is not None else "—"
            ex = f"{r['expectancy_r']}R" if r["expectancy_r"] is not None else "—"
            print(f"  {r['key']:<34}{r['n']:>5}{wr:>8}{pf:>7}{ex:>9}"
                  f"  {r['verdict']}")
        if fam["hidden_thin"]:
            print(f"  ({fam['hidden_thin']} buckets below n={fam['min_show']} "
                  f"held back, {fam['hidden_thin_rows']} trades)")
        if fam["truncated"]:
            print(f"  ({fam['truncated']} further rows not shown)")


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    try:
        from core.env_boot import load_env
        load_env()      # cron/CLI runs inherit no systemd environment
    except Exception:
        pass
    try:
        from learning.telemetry import load_unified
        unified = load_unified()
    except Exception as e:
        print(f"cannot read the trade journals: {type(e).__name__}: {e}")
        return 1
    rep = setup_edge(unified)
    only = argv[argv.index("--family") + 1] if "--family" in argv else None
    _print(rep, only)
    print(f"\nUNPROVEN until n>={MIN_N}. A combination is a hypothesis, not a "
          "rule — nothing here changes v7 behaviour.")
    if "--json" in argv:
        with open(argv[argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
