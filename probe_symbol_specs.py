#!/usr/bin/env python3
"""Broker-truth probe for staging new symbols (crypto expansion).

Asks the v7 bridge for each candidate's REAL MT5 spec — decimals, tick size,
lot bounds, tradability — and prints a table plus a JSON block to hand to the
platform. Nothing goes live on a guess: a wrong decimal count collapses two
tradable levels into one displayed price, and an untradable or hidden symbol
looks identical to a working one until an order is rejected.

    python3 probe_symbol_specs.py                 # default candidate list
    python3 probe_symbol_specs.py XRPUSD SOLUSD   # explicit symbols
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

BRIDGE = "http://127.0.0.1:5001"
# Bridge-side names (SYMBOL_MAP resolves aliases); staging candidates.
DEFAULT = ["RIPPLE", "LITECOIN", "SOLUSD", "ADAUSD", "LINKUSD",
           "BITCOIN", "ETHEREUM"]          # last two = known-good controls


def probe(sym):
    q = urllib.parse.urlencode({"symbol": sym})
    try:
        with urllib.request.urlopen(f"{BRIDGE}/symbolspec?{q}", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"requested": sym, "ok": False, "reason": f"HTTP {e.code}"}
    except Exception as e:
        return {"requested": sym, "ok": False, "reason": type(e).__name__}


def main():
    syms = sys.argv[1:] or DEFAULT
    rows = [probe(s) for s in syms]
    print(f"{'requested':12} {'broker':10} {'dig':>4} {'tick_size':>12} "
          f"{'tick_val':>9} {'vol_min':>8} {'vol_step':>9} {'mode':>10} {'bid':>12}")
    for r in rows:
        if not r.get("ok"):
            print(f"{r.get('requested',''):12} {'-':10} {'':>4} "
                  f"{'':>12} {'':>9} {'':>8} {'':>9} "
                  f"{'NOT FOUND':>10}   <- {r.get('reason')}")
            continue
        print(f"{r['requested']:12} {r['symbol']:10} {r['digits']:>4} "
              f"{r['tick_size']:>12} {r['tick_value']:>9} {r['volume_min']:>8} "
              f"{r['volume_step']:>9} {r['trade_mode']:>10} "
              f"{(r.get('bid') if r.get('bid') is not None else '-'):>12}")

    ok = [r for r in rows if r.get("ok")]
    bad = [r for r in rows if not r.get("ok")]
    untradable = [r for r in ok if not r.get("tradable")]
    print(f"\n{len(ok)}/{len(rows)} resolved."
          + (f"  MISSING: {', '.join(r.get('requested','?') for r in bad)}" if bad else "")
          + (f"  NOT FULLY TRADABLE: {', '.join(r['symbol'] for r in untradable)}" if untradable else ""))
    print("\nDECIMALS for the platform display config (must equal `digits`):")
    for r in ok:
        print(f"  {r['symbol']}: {r['digits']}")
    print("\n--- JSON for the platform session ---")
    print(json.dumps([{k: r[k] for k in
                       ("symbol", "digits", "tick_size", "tick_value",
                        "volume_min", "volume_step", "trade_mode", "tradable")}
                      for r in ok], indent=1))


if __name__ == "__main__":
    main()
