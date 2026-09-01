#!/usr/bin/env python3
"""EXECUTOR TRUTH PATCH (2026-08-31, run on the WINDOWS box) — /positions
must never answer "no positions" when the truth is "MT5 unreachable".

Before: ensure_mt5()'s result was ignored and a disconnected MT5 made
positions_get() return None -> {"count":0} with HTTP 200 -> the bot
mistook every tracked trade for closed. Iron Rule 6 exists for this.

    python patch_executor_positions.py     (then restart SniperExecutorV7)
"""
import ast, os, shutil, sys, time

EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sniper_executor.py")
OLD = ("    try:\n"
       "        ensure_mt5()\n"
       "        pos = mt5.positions_get()\n")
NEW = ("    try:\n"
       "        if not ensure_mt5():\n"
       "            return jsonify({\"status\":\"error\",\"msg\":\"mt5 disconnected\"}), 503\n"
       "        pos = mt5.positions_get()\n"
       "        if pos is None:\n"
       "            return jsonify({\"status\":\"error\",\"msg\":\"positions_get None (mt5 not ready)\"}), 503\n")


def main():
    src = open(EXE, encoding="utf-8").read()
    if "positions_get None" in src:
        print("ALREADY PATCHED — nothing to do")
        return 0
    if src.count(OLD) != 1:
        print(f"ABORT: anchor found {src.count(OLD)}x, need exactly 1 — file untouched")
        return 1
    bak = f"{EXE}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(EXE, bak)
    out = src.replace(OLD, NEW)
    open(EXE, "w", encoding="utf-8").write(out)
    try:
        ast.parse(out)
    except SyntaxError as e:
        shutil.copy2(bak, EXE)
        print(f"ABORT: compile failed ({e}) — RESTORED from {bak}")
        return 1
    print(f"PATCHED sniper_executor.py (backup {os.path.basename(bak)})")
    print("Restart service SniperExecutorV7 to activate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
