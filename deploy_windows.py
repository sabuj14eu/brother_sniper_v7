#!/usr/bin/env python3
"""WINDOWS VPS DEPLOY (2026-09-02) — both executors, one run, no git needed.

The VPS has NO git repo in either service folder (verified: Test-Path
.git = False for C:\\Users\\Administrator and C:\\brother_v18), so the
git-pull ceremony cannot apply there. This script carries the two fixes
itself and applies each with the full ceremony:
    backup -> unique anchor or ABORT -> edit -> compile -> restore on fail.

A1  C:\\Users\\Administrator\\sniper_executor.py
    /positions must answer 503 when MT5 is down, never a clean count:0
    that the bot reads as "every trade closed" (the fake $0 losses).
B5  C:\\brother_v18\\executor_ic_markets\\src\\main.py (+ src/clock_witness.py)
    /candles derived the broker-clock offset from ONE witness and fell
    back to 0 silently while still claiming utc_normalized:true. Two
    fresh 24/7 witnesses must agree or the endpoint refuses.

Idempotent: run twice, the second run says ALREADY. Nothing is trading
logic; no thresholds, no sizing, no risk numbers change.

    python deploy_windows.py            (add --dry-run to only report)
"""
import ast
import os
import shutil
import sys
import time

V7 = r"C:\Users\Administrator\sniper_executor.py"
V18 = r"C:\brother_v18\executor_ic_markets\src\main.py"

A1_OLD = ("    try:\n"
          "        ensure_mt5()\n"
          "        pos = mt5.positions_get()\n")
A1_NEW = ("    try:\n"
          "        if not ensure_mt5():\n"
          "            return jsonify({\"status\":\"error\",\"msg\":\"mt5 disconnected\"}), 503\n"
          "        pos = mt5.positions_get()\n"
          "        if pos is None:\n"
          "            return jsonify({\"status\":\"error\",\"msg\":\"positions_get None (mt5 not ready)\"}), 503\n")

CLOCK_WITNESS = '''"""Two-witness broker-clock rule (B5, 2026-09-02)."""
from __future__ import annotations


def clock_offset(witnesses, now):
    """witnesses: [(symbol, tick_epoch_s), ...] from 24/7 symbols.
    Fresh = within 6h of now; offsets round to 30min; ALL fresh witnesses
    must agree and there must be >=2. (None, reason) means REFUSE."""
    fresh = [(s, t) for s, t in witnesses if t and abs(t - now) < 6 * 3600]
    if len(fresh) < 2:
        return None, f"{len(fresh)} fresh witness(es), need >=2 (got {[s for s, _ in witnesses]})"
    offs = {round((t - now) / 1800.0) * 1800 for _, t in fresh}
    if len(offs) != 1:
        return None, f"witnesses disagree: {sorted(offs)}"
    return int(offs.pop()), "agreed"
'''

B5_OLD = '''    _off = 0
    try:
        import time as _t
        _tk = await _mt5_call(mt5.symbol_info_tick, "BTCUSD")
        if _tk and _tk.time and abs(_tk.time - _t.time()) < 6 * 3600:
            _off = int(round((_tk.time - _t.time()) / 1800.0) * 1800)
    except Exception:
        pass
'''
B5_NEW = '''    import time as _t
    from src.clock_witness import clock_offset
    _wit = []
    for _wsym in os.getenv("CLOCK_WITNESSES", "BTCUSD,ETHUSD").split(","):
        try:
            _tk = await _mt5_call(mt5.symbol_info_tick, _wsym.strip())
            if _tk and _tk.time:
                _wit.append((_wsym.strip(), int(_tk.time)))
        except Exception:
            pass
    _off, _why = clock_offset(_wit, _t.time())
    if _off is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": f"clock unverifiable: {_why}",
                             "rows": [], "utc_normalized": False},
                            status_code=503)
'''


def fingerprint(path):
    try:
        src = open(path, encoding="utf-8").read()
    except OSError as e:
        return f"UNREADABLE ({e})"
    return f"{len(src.splitlines())} lines, {len(src)} bytes"


def apply(path, edits, marker, dry=False):
    """edits: [(name, old, new)]. All must match exactly once, or nothing."""
    if not os.path.exists(path):
        print(f"  SKIP: {path} not found")
        return False
    src = open(path, encoding="utf-8").read()
    if marker in src:
        print(f"  ALREADY patched: {path}")
        return True
    for name, old, _ in edits:
        n = src.count(old)
        if n != 1:
            print(f"  ABORT: anchor '{name}' found {n}x (need 1) in {path}")
            print(f"         file fingerprint: {fingerprint(path)} — send this line back")
            return False
    if dry:
        print(f"  DRY RUN: {path} would be patched ({fingerprint(path)})")
        return True
    bak = f"{path}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(path, bak)
    out = src
    for _, old, new in edits:
        out = out.replace(old, new)
    open(path, "w", encoding="utf-8").write(out)
    try:
        ast.parse(out)
    except SyntaxError as e:
        shutil.copy2(bak, path)
        print(f"  ABORT: compile failed ({e}) — RESTORED from {os.path.basename(bak)}")
        return False
    print(f"  PATCHED {path}  (backup {os.path.basename(bak)})")
    return True


def main():
    dry = "--dry-run" in sys.argv
    print("A1 — v7 executor /positions must not lie about a dead MT5")
    ok1 = apply(V7, [("positions try-block", A1_OLD, A1_NEW)],
                "positions_get None", dry)

    print("B5 — v18 executor /candles two-witness clock")
    wit_path = os.path.join(os.path.dirname(V18), "clock_witness.py")
    if os.path.exists(V18) and not dry:
        if not os.path.exists(wit_path):
            open(wit_path, "w", encoding="utf-8").write(CLOCK_WITNESS)
            print(f"  wrote {wit_path}")
        else:
            print(f"  clock_witness.py already present")
    ok2 = apply(V18, [("candles clock block", B5_OLD, B5_NEW)],
                "clock unverifiable", dry)

    print()
    print("RESULT: A1 " + ("OK" if ok1 else "NOT APPLIED") +
          " | B5 " + ("OK" if ok2 else "NOT APPLIED"))
    if ok1 or ok2:
        print("Next: nssm restart SniperExecutorV7   (and/or SniperExecutorV18)")
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
