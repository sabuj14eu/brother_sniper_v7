#!/usr/bin/env python3
"""Broker symbol probe (2026-08-31) — read-only, secret-safe.

Answers one question per symbol: can v7 actually GET candles for it from
the bridge? That settles the US30/USTEC bridge-400 item and tells
auto_live which names are tradable before Monday's open.

Prints symbol, HTTP status, bar count, newest bar age. NEVER prints the
bridge URL, token, or account (Iron Rule 8). Nothing is written, nothing
is traded, no order is ever placed.

    python3 probe_symbols.py                    # default universe
    python3 probe_symbols.py US30 USTEC GOLD    # explicit list
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

from auto_live import TF_MIN, _env

DEFAULT = ["SILVER", "GBPUSD", "US30", "USTEC", "US100", "GOLD", "BTC"]


def probe(base, sym):
    url = f"{base.rstrip('/')}/candles?symbol={sym}&tf={TF_MIN}&n=5"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            rows = (json.loads(r.read().decode()) or {}).get("rows") or []
            status = r.status
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", 0, None      # the 400 case, named plainly
    except Exception as e:
        return type(e).__name__, 0, None
    age = None
    if rows:
        try:
            age = (time.time() - float(rows[-1]["time"])) / 60.0
        except Exception:
            pass
    return f"HTTP {status}", len(rows), age


def main():
    base = _env("EXECUTOR_URL").replace("/execute", "")
    if not base:
        print("REFUSED: EXECUTOR_URL unset")
        return 1
    syms = [s.upper() for s in sys.argv[1:]] or DEFAULT
    print(f"{'SYMBOL':10s} {'RESULT':12s} {'BARS':>5s}  NEWEST BAR")
    ok = []
    for s in syms:
        status, n, age = probe(base, s)
        age_s = "—" if age is None else f"{age:.0f} min old"
        verdict = "TRADABLE" if (status == "HTTP 200" and n) else "NO CANDLES"
        print(f"{s:10s} {status:12s} {n:>5d}  {age_s:14s} {verdict}")
        if verdict == "TRADABLE":
            ok.append(s)
    print(f"\nCandle-tradable names: {','.join(ok) if ok else 'NONE'}")
    print("(This proves the FEED only. Order acceptance is a separate,")
    print(" human-approved probe — no order was placed by this script.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
