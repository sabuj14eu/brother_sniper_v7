#!/usr/bin/env python3
"""C1 (2026-09-02, audit round 2 — they were right, my refutation read a
truncated view): when a payload carries signal_id, THAT raw id was the
dedup key, and Pine ids (SS-BUY-<ts>, PB ids) carry NO symbol — so two
symbols firing the same direction on the same bar close collide and the
second trade is silently dropped. Fix: prefix the symbol. Retries and
mirror duplicates carry the same symbol, so dedup is NOT weakened.

    python3 patch_dedup_symbol.py
"""
import ast, os, shutil, sys, time

BOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")
OLD = '    if p.get("signal_id"): return str(p["signal_id"])\n'
NEW = ('    # [C1 2026-09-02] Pine ids carry no symbol -> same-bar cross-symbol\n'
       '    # collision dropped the second trade. Symbol-prefix the key.\n'
       '    if p.get("signal_id"): return f"{p.get(\'symbol\',\'\')}:{p[\'signal_id\']}"\n')


def main():
    src = open(BOT, encoding="utf-8").read()
    if "[C1 2026-09-02]" in src:
        print("ALREADY PATCHED — nothing to do")
        return 0
    if src.count(OLD) != 1:
        print(f"ABORT: anchor found {src.count(OLD)}x, need exactly 1 — untouched")
        return 1
    bak = f"{BOT}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(BOT, bak)
    out = src.replace(OLD, NEW)
    open(BOT, "w", encoding="utf-8").write(out)
    try:
        ast.parse(out)
    except SyntaxError as e:
        shutil.copy2(bak, BOT)
        print(f"ABORT: compile failed ({e}) — RESTORED")
        return 1
    print(f"PATCHED bot.py — dedup key is now symbol:signal_id (backup {os.path.basename(bak)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
