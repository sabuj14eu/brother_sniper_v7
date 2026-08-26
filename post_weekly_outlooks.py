#!/usr/bin/env python3
"""Auto-generate weekly outlooks from MEASURED data (2026-08-26).

The board reads ABSENT because the desk never invents an outlook — and
Shyam should not have to write prose at midnight for a board to fill.
This authors one weekly outlook per tradable symbol from numbers the
system already measured, honestly signed source="bot box auto-weekly-v1"
(the outlook contract explicitly allows bot-box authorship; the platform
renders the author). Facts only — no confidence words (refused by the
contract AND by post_outlook locally), no feelings, no invented levels:

  thesis    last close, the week's traded range, close vs prior week,
            and the symbol's conditional-profile cell (n + expectancy)
  scenarios above the week's HIGH -> acceptance/continuation reading
            below the week's LOW  -> range-lost/reset reading
            (the levels ARE the week's traded extremes — nothing drawn)

Candles come from the bridge's open closed-bar endpoint — the same rows
fetch_atr trades on (EXECUTOR_URL, GET /candles -> {"rows":[{"time":..}]},
the wire the 2026-08-20 lesson was earned on). A symbol with missing or
stale candles is SKIPPED with the reason — an outlook is never invented
to fill a box. Re-posting is append-only by design (a changed week is a
new post). Run manually or Sunday pre-open:
    30 21 * * 0 cd /home/shyam/brother_sniper_v7 && /usr/bin/python3 post_weekly_outlooks.py >> logs/outlook_push.log 2>&1
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

from post_outlook import BANNED, build_payload, _env  # same contract + refusals

# v7 bridge name -> platform outlook symbol
SYMBOLS = [("GOLD", "GOLD"), ("SILVER", "SILVER"), ("BITCOIN", "BTC"),
           ("ETHEREUM", "ETH"), ("USDJPY", "USDJPY"), ("US30", "US30"),
           ("USTEC", "US100")]
TF_MIN = 240                 # 4h bars
WEEK_BARS = 42               # ~7 days of 4h
STALE_S = TF_MIN * 60 * 3    # same 3-bar staleness rule as fetch_atr


def _num(row, *keys):
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def closed_rows(rows, now=None):
    now = now or time.time()
    out = []
    for r in rows or []:
        t = r.get("time")
        if t is None:
            continue
        if float(t) + TF_MIN * 60 <= now:            # closed bars only
            out.append(r)
    return out


def build_symbol_outlook(rows, profile_stats, now=None):
    """Pure: closed 4h rows + conditional-profile stats -> outlook args,
    or (None, reason) when the data does not justify one."""
    rows = closed_rows(rows, now)
    if len(rows) < WEEK_BARS + 10:
        return None, f"only {len(rows)} closed 4h bars — need {WEEK_BARS + 10}"
    now = now or time.time()
    if now - float(rows[-1]["time"]) > STALE_S:
        return None, "candles stale (newest beyond 3 bars) — no outlook invented"
    week = rows[-WEEK_BARS:]
    prior = rows[-2 * WEEK_BARS:-WEEK_BARS]
    hi = max(_num(r, "h", "high") for r in week)
    lo = min(_num(r, "l", "low") for r in week)
    last = _num(week[-1], "c", "close")
    if hi is None or lo is None or last is None:
        return None, f"unrecognised candle keys: {sorted(week[-1])}"
    prior_close = _num(prior[-1], "c", "close") if prior else None
    if prior_close:
        chg = (last - prior_close) / prior_close * 100
        vs = (f"{abs(chg):.1f}% {'above' if chg >= 0 else 'below'} last "
              f"week's close")
    else:
        vs = "no prior-week comparison available"
    n = profile_stats.get("n", 0)
    exp = profile_stats.get("expectancy_r")
    prof = (f"conditional profile n={n}, expectancy {exp:+.2f}R"
            if n and exp is not None else "conditional profile UNKNOWN (thin sample)")
    thesis = (f"Auto-weekly v1 from measured data: last close {last:g}, "
              f"week's traded range {lo:g}-{hi:g}, {vs}. {prof}. Levels are "
              f"the week's traded extremes, not drawn opinions.")
    for w in BANNED:
        assert w not in thesis.lower()
    scenarios = [
        f"above:{hi:g}:acceptance above the week's range — continuation "
        f"reading, watch structure at the highs",
        f"below:{lo:g}:week's range lost — structure reset, retest lower "
        f"before any new reading",
    ]
    return {"thesis": thesis, "scenarios": scenarios}, None


def _fetch(base, symbol):
    # tf param is MINUTES, same convention fetch_atr uses on this wire
    url = f"{base.rstrip('/')}/candles?symbol={symbol}&tf={TF_MIN}&n=120"
    with urllib.request.urlopen(url, timeout=10) as r:
        return (json.loads(r.read().decode()) or {}).get("rows") or []


def main() -> int:
    import os
    base = (os.getenv("EXECUTOR_URL") or _env("EXECUTOR_URL")).replace("/execute", "")
    url = _env("PLATFORM_WEBHOOK_URL")
    secret = _env("PLATFORM_WEBHOOK_SECRET")
    dry = "--dry-run" in sys.argv
    if not base:
        print("REFUSED: EXECUTOR_URL unset — cannot read candles")
        return 1
    if not dry and (not url or not secret):
        print("REFUSED: PLATFORM_WEBHOOK_URL / PLATFORM_WEBHOOK_SECRET unset")
        return 1
    try:
        from learning.conditional_profile import cell_stats, context_of
        from learning.telemetry import load_unified
        unified = load_unified()
    except Exception:
        unified = []
    posted = skipped = 0
    for bridge_sym, out_sym in SYMBOLS:
        try:
            rows = _fetch(base, bridge_sym)
        except Exception as e:
            print(f"{out_sym}: SKIP — candle fetch failed: {e}")
            skipped += 1
            continue
        mine = [r for r in unified
                if str(r.get("symbol") or "").upper() in (bridge_sym, out_sym)]
        args, why = build_symbol_outlook(rows, cell_stats(mine) if mine else {"n": 0})
        if args is None:
            print(f"{out_sym}: SKIP — {why}")
            skipped += 1
            continue
        body = build_payload(out_sym, "weekly", args["thesis"],
                             "bot box auto-weekly-v1", args["scenarios"], None)
        if dry:
            print(f"{out_sym}: DRY RUN\n{json.dumps(body, indent=2)}")
            posted += 1
            continue
        req = urllib.request.Request(
            f"{url.rstrip('/')}/webhooks/brain/outlook",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Brain-Secret": secret})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                reply = json.loads(r.read().decode())
            print(f"{out_sym}: STORED id={reply.get('id')} valid until "
                  f"{reply.get('valid_until')}")
            posted += 1
        except Exception as e:
            print(f"{out_sym}: POST FAILED — {e}")
            skipped += 1
    print(f"done: {posted} outlook(s) posted, {skipped} skipped (skips are "
          f"honest — a box with no data stays ABSENT)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
