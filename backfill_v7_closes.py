#!/usr/bin/env python3
"""Send v7's CLOSED-trade history to the platform (the W81/L89 the desk can see
but not read).

learning/trades.jsonl holds every trade as an `open` row and a later `close`
row joined by signal_id — 170 resolved outcomes, a bigger sample than anything
else in the system. Only closes since the outcome mirror went live were ever
sent, so the platform's V7 Desk shows the totals and "no closed trades" under
them. This replays the history through the same contract mirror_v7_close uses.

Idempotent (stable v7-<signal_id>), resumable (.backfill_closes_cursor),
read-only on trades.jsonl, and it stops cleanly if the platform goes away.

    python3 backfill_v7_closes.py --dry-run
    python3 backfill_v7_closes.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from learning.platform_mirror import build_v7_payload, _post_one  # noqa: E402

TRADES = os.path.join(_DIR, "learning", "trades.jsonl")
CURSOR = os.path.join(_DIR, ".backfill_closes_cursor")


def _env(key):
    v = os.getenv(key, "").strip()
    if v:
        return v
    try:
        with open(os.path.join(_DIR, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def load_pairs():
    """[(signal_id, open_row, close_row)] in close order. Opens without a
    close are skipped — an unresolved trade is not an outcome."""
    opens, closes = {}, {}
    with open(TRADES, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            sid = r.get("signal_id")
            if not sid:
                continue
            t = r.get("_type") or ("close" if r.get("net_profit") is not None else "open")
            (closes if t == "close" else opens)[sid] = r
    out = [(sid, opens.get(sid, {}), c) for sid, c in closes.items()]
    out.sort(key=lambda x: str(x[2].get("timestamp_close") or ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.12)
    args = ap.parse_args()

    if not os.path.exists(TRADES):
        raise SystemExit(f"no trade memory at {TRADES}")
    url, secret = _env("PLATFORM_WEBHOOK_URL"), _env("PLATFORM_WEBHOOK_SECRET")
    if not args.dry_run and not (url and secret):
        raise SystemExit("PLATFORM_WEBHOOK_URL / PLATFORM_WEBHOOK_SECRET not set")

    pairs = load_pairs()
    start = 0
    if os.path.exists(CURSOR):
        try:
            start = int(open(CURSOR).read().strip())
        except Exception:
            start = 0
    todo = pairs[start:]
    print(f"[closes] resolved trades: {len(pairs)} · already sent: {start} · pending: {len(todo)}")

    sent = unsendable = 0
    for i, (sid, o, c) in enumerate(todo):
        if args.limit and sent >= args.limit:
            break
        # An ORPHAN close — a close row with no matching open row — carries no
        # symbol, and neither does the close record itself (trade_memory writes
        # ids, prices and PnL only). Sending it produces symbol:null, which the
        # platform rightly declines: that is how 2 of these silently "never
        # arrived". Skip it and SAY SO. The symbol is not invented from the
        # ticket, and never guessed. (Recoverable in principle for ADOPTED_<tk>
        # rows, whose ticket is in the id, by asking the broker — worth doing
        # only if this ever stops being a handful of rows.)
        if not o.get("symbol"):
            unsendable += 1
            print(f"[skip] {sid} — orphan close, no open row and therefore no "
                  f"symbol; not sent (never invent one)")
            open(CURSOR, "w").write(str(start + i + 1))
            continue
        net = float(c.get("net_profit") or 0)
        body = build_v7_payload(
            {"signal_id": sid, "symbol": o.get("symbol"), "direction": o.get("direction"),
             "entry": o.get("entry"), "sl": o.get("inst_sl") or o.get("raw_sl"),
             "tp": o.get("tp"), "rr": o.get("rr"), "session": o.get("session")},
            "closed", order_id=o.get("order_id"),
            outcome={"win": bool(c.get("won", net > 0)), "net": round(net, 2),
                     "close_price": c.get("close_price"), "ticket": o.get("order_id"),
                     "hold_seconds": c.get("hold_time_seconds"),
                     "mae": c.get("mae"), "mfe": c.get("mfe"),
                     "be_done": c.get("be_done"), "partial_done": c.get("partial_done"),
                     "closed_at": c.get("timestamp_close")})
        body["backfill"] = True
        body["ts"] = c.get("timestamp_close")
        if args.dry_run:
            if sent < 3:
                print(f"[dry] {body['signal_id']} {body['symbol']} net={net:+.2f} "
                      f"closed={body['ts']}")
            sent += 1
            continue
        try:
            _post_one(body, url, secret)
        except Exception as e:
            print(f"[FAIL] {sid}: {type(e).__name__} — stopping, cursor saved; rerun to resume")
            break
        sent += 1
        open(CURSOR, "w").write(str(start + i + 1))
        if args.sleep:
            time.sleep(args.sleep)

    print(f"[closes] sent {sent}"
          + (f" · skipped {unsendable} orphan (no symbol)" if unsendable else "")
          + (" (DRY RUN — nothing posted)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
