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


OBS_V7_ROUTE = '@app.route("/health", methods=["GET"])'
OBS_V7_IDENT = (
    "# [OBS 2026-09-02] identity for the Git<->Production MATCH light.\n"
    "def _deploy_commit():\n"
    "    try:\n"
    "        import subprocess as _sp, os as _os\n"
    "        return _sp.run([\"git\", \"-C\", _os.path.dirname(_os.path.abspath(__file__)),\n"
    "                        \"rev-parse\", \"--short\", \"HEAD\"],\n"
    "                       capture_output=True, text=True, timeout=5).stdout.strip() or \"untracked\"\n"
    "    except Exception:\n"
    "        return \"untracked\"\n"
    "\n"
    "\n"
    "_GIT_COMMIT = _deploy_commit()\n"
    "\n"
    "\n")
OBS_V7_OLD = '        return jsonify({"status":"ok","account":acc.login,"balance":acc.balance,"equity":acc.equity})'
OBS_V7_NEW = '        return jsonify({"status":"ok","account":acc.login,"balance":acc.balance,"equity":acc.equity,"git_commit":_GIT_COMMIT,"service_version":"sniper-executor-v7"})'

OBS_V18_ROUTE = '@app.get("/health")'
OBS_V18_IDENT = (
    "# [OBS 2026-09-02] identity for the Git<->Production MATCH light\n"
    "def _deploy_commit():\n"
    "    try:\n"
    "        import subprocess\n"
    "        return subprocess.run([\"git\", \"-C\", str(_ROOT), \"rev-parse\", \"--short\", \"HEAD\"],\n"
    "                              capture_output=True, text=True, timeout=5).stdout.strip() or \"untracked\"\n"
    "    except Exception:\n"
    "        return \"untracked\"\n"
    "\n"
    "\n"
    "_GIT_COMMIT = _deploy_commit()\n"
    "\n"
    "\n"
    "def _pnl_pct_today():\n"
    "    \"\"\"[B6] Today's realized P/L as % of balance. None on ANY doubt —\n"
    "    a daily-loss watchdog must never read silence as safety.\"\"\"\n"
    "    try:\n"
    "        import MetaTrader5 as mt5\n"
    "        acc = mt5.account_info()\n"
    "        if not acc or not acc.balance:\n"
    "            return None\n"
    "        day0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)\n"
    "        deals = mt5.history_deals_get(day0, datetime.now(timezone.utc))\n"
    "        if deals is None:\n"
    "            return None\n"
    "        pnl = sum((d.profit + d.swap + d.commission) for d in deals)\n"
    "        return round(pnl / acc.balance * 100.0, 3)\n"
    "    except Exception:\n"
    "        return None\n"
    "\n"
    "\n")
OBS_V18_OLD = ('        "trades_today": _state.trades_today,\n'
               '        "balance": _mt5.account_balance(),\n'
               '    }\n'
               '\n'
               '\n'
               '@app.get("/positions")')
OBS_V18_NEW = ('        "trades_today": _state.trades_today,\n'
               '        "balance": _mt5.account_balance(),\n'
               '        "pnl_pct_today": _pnl_pct_today(),\n'
               '        "git_commit": _GIT_COMMIT, "service_version": "executor-ic-markets",\n'
               '    }\n'
               '\n'
               '\n'
               '@app.get("/positions")')


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

    print("OBS — /health identity (git_commit + service_version), B6 pnl_pct_today")
    ok3 = apply(V7, [("v7 health route", OBS_V7_ROUTE, OBS_V7_IDENT + OBS_V7_ROUTE),
                     ("v7 health fields", OBS_V7_OLD, OBS_V7_NEW)],
                "[OBS 2026-09-02]", dry)
    ok4 = apply(V18, [("v18 health route", OBS_V18_ROUTE, OBS_V18_IDENT + OBS_V18_ROUTE),
                      ("v18 health fields", OBS_V18_OLD, OBS_V18_NEW)],
                "[OBS 2026-09-02]", dry)

    print()
    print("RESULT: A1 " + ("OK" if ok1 else "NOT APPLIED") +
          " | B5 " + ("OK" if ok2 else "NOT APPLIED") +
          " | OBS-V7 " + ("OK" if ok3 else "NOT APPLIED") +
          " | OBS-V18 " + ("OK" if ok4 else "NOT APPLIED"))
    if ok1 or ok2:
        print("Next: nssm restart SniperExecutorV7   (and/or SniperExecutorV18)")
    return 0 if (ok1 and ok2 and ok3 and ok4) else 1


if __name__ == "__main__":
    sys.exit(main())
