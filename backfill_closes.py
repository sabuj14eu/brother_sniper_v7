#!/usr/bin/env python3
"""BOT-P0-1: recover missing close rows from the broker's own history.

The desk shows W81 / L89 from state.json counters while the trade journal
has (almost) no close rows to analyze — 170 real outcomes, a larger sample
than anything else in either system, unreadable. The outcomes still exist
in one place that never forgets: MT5's deal history, reachable through the
bridge's /history endpoint (per-position aggregates keyed by position_id,
which is exactly the order_id v7 stored on each open row).

This matches journal opens that lack a close against those broker
aggregates and writes the missing close rows THROUGH the journal's own
writer, in its exact schema, flagged "backfilled": true so a backfilled
outcome can never masquerade as a live-recorded one.

SAFETY:
  * DRY RUN by default — prints what it would write; --write to append.
  * Append-only: never edits or removes a row; a signal that already has a
    close row is untouchable.
  * A position still open at the broker (or still tracked in state.json)
    never receives a close row, whatever the history says.
  * Unmatched opens are REPORTED, never invented. Broker silence is
    UNKNOWN, not a loss.
  * mae/mfe are deliberately absent on backfilled rows — the live sampler
    was not watching. mae_recompute.py fills exact M1 excursions afterward,
    because the backfilled rows carry both timestamps.

Usage (from the repo root on the bot box):
    python3 backfill_closes.py                 # dry run + report
    python3 backfill_closes.py --hours 8760    # look back a full year
    python3 backfill_closes.py --write         # append the close rows
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_HOURS = 2160          # 90 days; --hours 8760 for a year


def _ts(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v / 1000 if v > 4102444800 else v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# ── journal side ─────────────────────────────────────────────────────────────

def load_journal(path: str):
    """(opens by signal_id, signal_ids that already have a close row)."""
    opens, closed = {}, set()
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
                if not isinstance(r, dict):
                    continue
                sid = str(r.get("signal_id") or "")
                if not sid:
                    continue
                if r.get("_type") == "open":
                    opens[sid] = r
                elif r.get("_type") == "close":
                    closed.add(sid)
    except FileNotFoundError:
        pass
    return opens, closed


def candidates(opens: dict, closed: set, live_tickets: set) -> list:
    """Open rows that need a close: no close row yet, a broker ticket to
    match on, and NOT currently open or tracked."""
    out = []
    for sid, row in opens.items():
        if sid in closed:
            continue
        ticket = row.get("order_id")
        if ticket in (None, "", 0):
            continue                      # nothing to match on — reported later
        if ticket in live_tickets:
            continue                      # still running: not ours to close
        out.append(row)
    out.sort(key=lambda r: str(r.get("timestamp_open") or ""))
    return out


# ── broker side ──────────────────────────────────────────────────────────────

def match(cands: list, history: list) -> tuple:
    """(matches [(open_row, broker_position)], unmatched [open_row])."""
    by_pid = {}
    for h in history or []:
        if isinstance(h, dict) and h.get("position_id") is not None:
            by_pid[h["position_id"]] = h
    hits, misses = [], []
    for row in cands:
        h = by_pid.get(row.get("order_id"))
        if h is not None and h.get("close_price") is not None:
            hits.append((row, h))
        else:
            misses.append(row)
    return hits, misses


def close_record(open_row: dict, hist: dict) -> dict:
    """The journal's own close schema (learning/trade_memory.close_trade),
    built from broker numbers, flagged as backfilled. No mae/mfe — the
    sampler was not watching; mae_recompute fills exact values later."""
    profit = float(hist.get("profit") or 0.0)
    swap = float(hist.get("swap") or 0.0)
    commission = float(hist.get("commission") or 0.0)
    net = profit + swap + commission
    ct = _ts(hist.get("close_time"))
    rec = {"_type": "close",
           "signal_id": str(open_row.get("signal_id")),
           "timestamp_close": (datetime.fromtimestamp(ct, tz=timezone.utc)
                               .isoformat() if ct else None),
           "close_price": hist.get("close_price"),
           "gross_profit": profit, "swap": swap, "commission": commission,
           "net_profit": net, "won": net > 0, "version": "v8",
           "backfilled": True, "backfill_source": "bridge_history",
           "broker_ticket": hist.get("position_id")}
    ot = _ts(open_row.get("timestamp_open"))
    if ot and ct and ct > ot:
        rec["hold_time_seconds"] = round(ct - ot, 1)
    return rec


# ── io ───────────────────────────────────────────────────────────────────────

def _get(url: str):
    import urllib.request
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    from core.env_boot import load_env
    load_env()          # cron/CLI runs inherit no systemd environment
    os.chdir(BASE)                        # trade_memory paths are repo-relative
    hours = (int(argv[argv.index("--hours") + 1])
             if "--hours" in argv else DEFAULT_HOURS)
    write = "--write" in argv

    from learning.trade_memory import MEMORY_FILE, _append_raw
    opens, closed = load_journal(MEMORY_FILE)
    print(f"journal: {len(opens)} open rows · {len(closed)} already closed")

    base = os.getenv("EXECUTOR_URL", "").replace("/execute", "")
    if not base:
        print("EXECUTOR_URL not set — cannot reach the bridge")
        return 1
    try:
        live = {p.get("ticket") for p in
                (_get(base + "/positions").get("positions") or [])}
    except Exception as e:
        print(f"bridge /positions unreachable ({type(e).__name__}) — refusing "
              f"to backfill blind: a still-open trade must never get a close row")
        return 1
    # tracked slots are excluded too, even if the positions call missed them
    try:
        st = json.load(open("state.json"))
        for t in (st.get("open_trades") or {}).values():
            if t:
                live.add(t.get("order_id"))
    except Exception:
        pass

    cands = candidates(opens, closed, live)
    print(f"needing a close: {len(cands)} (live/tracked excluded: "
          f"{len([s for s in opens if s not in closed]) - len(cands)})")
    if not cands:
        return 0

    try:
        history = _get(f"{base}/history?hours={hours}").get("deals") or []
    except Exception as e:
        print(f"bridge /history unreachable ({type(e).__name__})")
        return 1
    hits, misses = match(cands, history)
    print(f"broker history ({hours}h): matched {len(hits)} · "
          f"unmatched {len(misses)} (reported, never invented)")

    wrote = 0
    for open_row, hist in hits:
        rec = close_record(open_row, hist)
        tag = "WRITE" if write else "dry-run"
        print(f"  [{tag}] {rec['signal_id']} {open_row.get('symbol')} "
              f"net={rec['net_profit']:.2f} won={rec['won']} "
              f"closed={rec.get('timestamp_close')}")
        if write:
            _append_raw(rec)
            wrote += 1
    for row in misses[:10]:
        print(f"  [UNKNOWN] {row.get('signal_id')} {row.get('symbol')} "
              f"ticket={row.get('order_id')} — outside the {hours}h window or "
              f"not in broker history; try --hours 8760")
    if misses[10:]:
        print(f"  ... and {len(misses) - 10} more unmatched")

    if write and wrote:
        print(f"\nappended {wrote} close rows (flagged backfilled:true).")
        print("Next: python3 mae_recompute.py && python3 v7_counterfactual.py "
              "&& python3 v7_evidence_report.py — the desks light up from there.")
    elif not write and hits:
        print(f"\ndry run only — rerun with --write to append {len(hits)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
