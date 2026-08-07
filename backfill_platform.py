#!/usr/bin/env python3
"""Historical backfill: v7 telemetry.jsonl -> Brother Bot Platform DecisionEvents.

Replays every captured v7 decision (opens AND rejects) to the platform's
brain-signal webhook so the Decision Lab holds months of real v7 behavior
instead of an empty page. READ-ONLY on telemetry.jsonl — never modifies it.

Idempotent + resumable:
  - each row posts with its original signal_id ("v7-<id>") and backfill:true
    + its original ts, so the platform can dedupe/date correctly;
  - progress is checkpointed to .backfill_cursor (line number); rerunning
    continues where it stopped. Delete the cursor file to start over.

Usage (on the v7 box, with PLATFORM_WEBHOOK_URL/SECRET in the environment
or in .env):
    python3 backfill_platform.py --dry-run          # count + preview, no posts
    python3 backfill_platform.py                    # full run
    python3 backfill_platform.py --limit 100        # first 100 pending rows
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

TELEMETRY = os.path.join(_DIR, "learning", "telemetry.jsonl")
CURSOR = os.path.join(_DIR, ".backfill_cursor")


def _env_fallback(key):
    """os.environ first; fall back to .env (script may run outside systemd)."""
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


def row_to_payload(row: dict):
    """Normalize a telemetry row (open or reject) to the mirror contract."""
    t = row.get("_type") or ("reject" if row.get("reject_status") else "open")
    pseudo = {
        "signal_id": row.get("signal_id"),
        "symbol": row.get("symbol"),
        "direction": row.get("direction") or row.get("side"),
        "entry": row.get("entry") or row.get("requested_price"),
        "sl": row.get("sl"),
        "tp": row.get("tp") or row.get("tp1"),
        "tp2": row.get("tp2"),
        "rr": row.get("rr"),
        "grade": row.get("grade"),
        "pine_ver": row.get("pine_version") or row.get("pine_ver"),
        "type": row.get("setup_type") or row.get("type"),
    }
    if t == "reject":
        body = build_v7_payload(pseudo, row.get("reject_status") or "rejected",
                                row.get("reject_reason") or "")
    else:
        body = build_v7_payload(pseudo, "approved", "",
                                order_id=row.get("broker_ticket"))
    body["backfill"] = True
    body["ts"] = row.get("ts") or row.get("timestamp") or row.get("v7_receive_time")
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="max rows this run (0 = all)")
    ap.add_argument("--sleep", type=float, default=0.15, help="seconds between posts")
    args = ap.parse_args()

    if not os.path.exists(TELEMETRY):
        raise SystemExit(f"no telemetry file at {TELEMETRY}")
    url = _env_fallback("PLATFORM_WEBHOOK_URL")
    secret = _env_fallback("PLATFORM_WEBHOOK_SECRET")
    if not args.dry_run and (not url or not secret):
        raise SystemExit("PLATFORM_WEBHOOK_URL / PLATFORM_WEBHOOK_SECRET not set")

    start = 0
    if os.path.exists(CURSOR):
        try:
            start = int(open(CURSOR).read().strip())
        except Exception:
            start = 0

    lines = open(TELEMETRY, encoding="utf-8").read().splitlines()
    todo = lines[start:]
    print(f"[backfill] telemetry rows: {len(lines)} · already done: {start} · pending: {len(todo)}")

    sent = skipped = failed = 0
    for i, ln in enumerate(todo):
        if args.limit and sent + skipped + failed >= args.limit:
            break
        lineno = start + i + 1
        try:
            row = json.loads(ln)
            body = row_to_payload(row)
        except Exception as e:
            print(f"[skip] line {lineno}: unparseable ({type(e).__name__})")
            skipped += 1
            continue
        if args.dry_run:
            if sent < 3:
                print(f"[dry] {body['signal_id']} status={body['status']} ({body.get('v7_status')}) ts={body.get('ts')}")
            sent += 1
            continue
        try:
            ok = _post_one(body, url, secret)
        except Exception as e:
            print(f"[FAIL] line {lineno} {body.get('signal_id')}: {type(e).__name__} — stopping (cursor saved, rerun to resume)")
            failed += 1
            break
        if ok:
            sent += 1
        else:
            print(f"[warn] non-2xx for {body.get('signal_id')} — counted, continuing")
            skipped += 1
        open(CURSOR, "w").write(str(lineno))
        if args.sleep:
            time.sleep(args.sleep)

    print(f"[backfill] done: sent={sent} skipped={skipped} failed={failed}"
          + (" (DRY RUN — nothing posted)" if args.dry_run else f" · cursor at {open(CURSOR).read().strip() if os.path.exists(CURSOR) else 0}"))


if __name__ == "__main__":
    main()
