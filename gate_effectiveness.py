#!/usr/bin/env python3
"""Which of v7's gates actually earn their keep? (batch, read-only, $0)

The desk can already say "GATE-SLOT stopped 12 signals". That number alone
proves nothing — a frequent gate is not thereby a wrong gate:

    Killed 100 signals, 80 would have lost  -> a GOOD gate, keep it.
    Killed 100 signals, 70 would have won   -> a COSTLY gate, investigate.

So this joins the two lanes v7 now records:
    KILLED lane  — counterfactual replay of blocked signals (v7_counterfactual)
    KEPT lane    — realized outcomes of executed trades (learning/trades.jsonl
                   joined to open-time facts by telemetry.load_unified)

EVIDENCE LAW, enforced in code, not in a comment:
  * Rows are split 70/30 by TIME. The VALIDATE column decides. A verdict
    computed on the training half only is reported as UNPROVEN.
  * Fewer than MIN_N resolved rows in validate -> PROVISIONAL, verdict
    UNPROVEN. n<20 is luck.
  * This module never changes a gate, a threshold or a weight. Changing a
    gate is a STRATEGY change: separate project, human decision, logged.
    It only measures.

Usage:
    python3 gate_effectiveness.py                    # table
    python3 gate_effectiveness.py --json out.json
    python3 gate_effectiveness.py --cf learning/counterfactual.jsonl
"""
from __future__ import annotations

import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
CF_FILE = os.path.join(BASE, "learning", "counterfactual.jsonl")

MIN_N = 20              # Evidence Law: below this it is luck
TRAIN_RATIO = 0.7       # 70/30 by time; the validate column decides
RESOLVED = ("HIT", "SL", "NO_FILL")


# ── shared edge math (measurement only — no weighting, no tuning) ────────────

def profit_factor(rs: list[float]) -> float | None:
    """Gross win R / gross loss R. None when either side is missing —
    a PF with no losses yet is not infinity, it is unknown."""
    wins = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    if not wins or not losses:
        return None
    return round(wins / losses, 2)


def bucket_stats(rs: list[float], n_rows: int | None = None) -> dict:
    """n, win rate, expectancy, PF over a list of R multiples."""
    n = len(rs) if n_rows is None else n_rows
    if not rs:
        return {"n": n, "win_rate": None, "expectancy_r": None, "pf": None,
                "provisional": True}
    wins = [r for r in rs if r > 0]
    return {
        "n": n,
        "win_rate": round(len(wins) / len(rs) * 100, 1),
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "pf": profit_factor(rs),
        "avg_win_r": round(sum(wins) / len(wins), 3) if wins else None,
        "avg_loss_r": (round(sum(r for r in rs if r < 0) /
                             len([r for r in rs if r < 0]), 3)
                       if any(r < 0 for r in rs) else None),
        "provisional": len(rs) < MIN_N,
    }


def split_train_validate(rows: list[dict], ratio: float = TRAIN_RATIO) -> tuple:
    """Oldest `ratio` by timestamp is TRAIN, the newest remainder is VALIDATE.
    Split by time, never at random: a rule must survive on data it has not
    already been fitted to."""
    ordered = sorted([r for r in rows if r.get("ts") is not None],
                     key=lambda r: r["ts"])
    cut = int(len(ordered) * ratio)
    return ordered[:cut], ordered[cut:]


def _rs(rows: list[dict]) -> list[float]:
    return [r["r"] for r in rows
            if r.get("would_have") in RESOLVED and r.get("r") is not None]


# ── the gate table ───────────────────────────────────────────────────────────

def verdict(validate: dict) -> str:
    """What the VALIDATE half says about a gate. Deliberately blunt about
    ignorance: everything thin or untested reads UNPROVEN."""
    if validate["n"] < MIN_N or validate["expectancy_r"] is None:
        return "UNPROVEN"
    e = validate["expectancy_r"]
    if e <= -0.10:
        return "GOOD GATE"        # what it killed would have bled
    if e >= 0.10:
        return "COSTLY GATE"      # what it killed would have paid
    return "NEUTRAL"


def gate_table(cf_rows: list[dict]) -> list[dict]:
    """Per gate: what the signals it stopped would have done."""
    by_gate: dict = {}
    for r in cf_rows or []:
        if not isinstance(r, dict) or r.get("executed"):
            continue          # the kept lane is judged by realized outcomes
        gate = str(r.get("gate") or "UNKNOWN")
        by_gate.setdefault(gate, []).append(r)

    out = []
    for gate, rows in by_gate.items():
        train, val = split_train_validate(rows)
        t_stats = bucket_stats(_rs(train), n_rows=len(_rs(train)))
        v_stats = bucket_stats(_rs(val), n_rows=len(_rs(val)))
        out.append({
            "gate": gate,
            "killed": len(rows),
            "resolved": len(_rs(rows)),
            "open": sum(1 for r in rows if r.get("would_have") == "OPEN"),
            "unknown": sum(1 for r in rows if r.get("would_have") == "UNKNOWN"),
            "no_fill": sum(1 for r in rows if r.get("would_have") == "NO_FILL"),
            "train": t_stats, "validate": v_stats,
            "verdict": verdict(v_stats),
            "symbols": ", ".join(sorted({str(r.get("symbol")) for r in rows
                                         if r.get("symbol")})[:6]),
        })
    return sorted(out, key=lambda r: -r["killed"])


def kept_lane(unified_rows: list[dict]) -> dict:
    """Realized performance of what v7 DID trade — the baseline every gate
    verdict is read against. R is the canonical v7 formula."""
    rs = []
    for row in unified_rows or []:
        try:
            net = float(row["net_profit"])
            bal = float(row["balance_at_open"])
            rp = float(row["risk_pct"])
            if bal > 0 and rp > 0:
                rs.append(net / (bal * rp))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    return bucket_stats(rs)


def by_dimension(unified_rows: list[dict], key: str) -> list[dict]:
    """Realized edge grouped by any stored field (session, symbol, grade,
    regime, strategy_id …) — the asset x setup matrix, with PF."""
    buckets: dict = {}
    for row in unified_rows or []:
        try:
            net = float(row["net_profit"])
            bal = float(row["balance_at_open"])
            rp = float(row["risk_pct"])
            if not (bal > 0 and rp > 0):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        buckets.setdefault(str(row.get(key) or "—"), []).append(net / (bal * rp))
    return sorted(({"key": k, **bucket_stats(v)} for k, v in buckets.items()),
                  key=lambda r: -r["n"])


# ── io ───────────────────────────────────────────────────────────────────────

def load_cf(path: str | None = None) -> list[dict]:
    rows = []
    try:
        with open(path or CF_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
    except FileNotFoundError:
        pass
    return rows


def report(cf_rows: list[dict], unified_rows: list[dict]) -> dict:
    return {"kept_lane": kept_lane(unified_rows), "gates": gate_table(cf_rows),
            "by_session": by_dimension(unified_rows, "session"),
            "by_symbol": by_dimension(unified_rows, "symbol"),
            "by_grade": by_dimension(unified_rows, "grade"),
            "by_strategy": by_dimension(unified_rows, "strategy_id"),
            "min_n": MIN_N, "train_ratio": TRAIN_RATIO}


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    cf_path = argv[argv.index("--cf") + 1] if "--cf" in argv else None
    cf_rows = load_cf(cf_path)
    try:
        from learning.telemetry import load_unified
        unified = load_unified()
    except Exception:
        unified = []
    rep = report(cf_rows, unified)

    kept = rep["kept_lane"]
    print(f"KEPT lane (what v7 traded): n={kept['n']} WR={kept['win_rate']}% "
          f"PF={kept['pf']} expectancy={kept['expectancy_r']}R"
          + ("  [PROVISIONAL]" if kept["provisional"] else ""))
    if not cf_rows:
        print("\nno counterfactual rows yet — run v7_counterfactual.py first")
        return 0
    print(f"\nGATE EFFECTIVENESS — what each gate's KILLED signals would have done")
    print(f"{'gate':<20}{'killed':>7}{'resolv':>7}{'val n':>7}{'val WR':>8}"
          f"{'val PF':>8}{'val exp':>9}  verdict")
    for g in rep["gates"]:
        v = g["validate"]
        print(f"{g['gate']:<20}{g['killed']:>7}{g['resolved']:>7}{v['n']:>7}"
              f"{(str(v['win_rate']) + '%') if v['win_rate'] is not None else '—':>8}"
              f"{str(v['pf']) if v['pf'] is not None else '—':>8}"
              f"{str(v['expectancy_r']) + 'R' if v['expectancy_r'] is not None else '—':>9}"
              f"  {g['verdict']}")
    print(f"\nVerdict reads the VALIDATE half only. UNPROVEN until n>={MIN_N}.")
    print("A verdict is evidence for a HUMAN decision — no gate changes itself.")
    if "--json" in argv:
        with open(argv[argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
