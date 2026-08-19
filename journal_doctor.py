#!/usr/bin/env python3
"""Why can the desk not read outcomes that are already in the journal?

BOT-P0-1 was reported as "170 outcomes missing". The journal actually holds
them: 212 opens, 202 closes. So nothing is missing — something in the READ
path drops them, and guessing which is how you end up backfilling rows that
already exist.

This prints, without changing anything:
  * what the journal contains and how much of it JOINS by signal_id;
  * of the joined rows, how many can be priced in R (the desk's edge tables
    need balance_at_open and risk_pct, both written on the OPEN row);
  * what load_unified() — the canonical reader every analytic uses — returns;
  * the exact field names on a sample open and close row.

Read-only. Usage:  python3 journal_doctor.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))


def scan(path: str) -> dict:
    opens, closes, other, bad = {}, {}, Counter(), 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                bad += 1
                continue
            if not isinstance(r, dict):
                bad += 1
                continue
            t = r.get("_type")
            sid = str(r.get("signal_id") or "")
            if t == "open":
                opens[sid] = r
            elif t == "close":
                closes[sid] = r
            else:
                other[str(t)] += 1
    return {"opens": opens, "closes": closes, "other": other, "bad": bad}


def main() -> int:
    os.chdir(BASE)
    from learning.trade_memory import MEMORY_FILE
    print(f"journal: {MEMORY_FILE}")
    if not os.path.exists(MEMORY_FILE):
        print("  MISSING — nothing to read")
        return 1
    s = scan(MEMORY_FILE)
    opens, closes = s["opens"], s["closes"]
    joined = set(opens) & set(closes)
    print(f"  {len(opens)} opens · {len(closes)} closes · "
          f"{len(joined)} JOIN by signal_id")
    if s["other"]:
        print(f"  other _type rows: {dict(s['other'])}")
    if s["bad"]:
        print(f"  unparseable lines: {s['bad']}")

    orphan_closes = set(closes) - set(opens)
    if orphan_closes:
        print(f"  ! {len(orphan_closes)} closes have NO matching open "
              f"(they cannot be joined, so no analytic can price them)")
        for sid in list(orphan_closes)[:3]:
            print(f"      e.g. {sid!r}")

    # can the desk price them? R needs balance_at_open + risk_pct (open row)
    priceable = missing_bal = missing_risk = 0
    for sid in joined:
        o = opens[sid]
        bal, risk = o.get("balance_at_open"), o.get("risk_pct")
        if not bal:
            missing_bal += 1
        if not risk:
            missing_risk += 1
        try:
            if float(bal) > 0 and float(risk) > 0:
                priceable += 1
        except (TypeError, ValueError):
            pass
    print(f"  of the joined: {priceable} can be expressed in R "
          f"(missing balance_at_open {missing_bal} · missing risk_pct {missing_risk})")

    # what the canonical reader actually returns
    try:
        from learning.telemetry import load_unified
        rows = load_unified()
        with_net = [r for r in rows if r.get("net_profit") is not None]
        print(f"load_unified(): {len(rows)} rows · {len(with_net)} with an outcome")
        if rows and not with_net:
            print("  ! the join produced rows but no outcomes — telemetry and the "
                  "trade journal disagree on signal_id")
    except Exception as e:
        print(f"load_unified() FAILED: {type(e).__name__}: {e}")

    for label, d in (("open", opens), ("close", closes)):
        if d:
            sample = next(iter(d.values()))
            print(f"sample {label} row keys: {sorted(sample.keys())}")
    print("\nRead-only: nothing was written. If joins and R look healthy here, "
          "the gap is in the display path, not the data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
