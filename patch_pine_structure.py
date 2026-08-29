#!/usr/bin/env python3
"""Anchor-safe patch: capture Pine v18.13's structure on the OPEN path.

v18.13 appends "structure" ("HH/HL" | "LH/LL" | "MIXED") — the same three
words auto-live-v1 emits. Without this line v7 receives it and throws it
away, and the agreement cut stays unmeasurable. Log-only: the trade is
already placed when this block runs; nothing here can affect execution.

Ceremony: backup -> unique anchor or ABORT -> compile -> restore on fail.
    python3 patch_pine_structure.py
"""
import ast, os, shutil, sys, time

BOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")
ANCHOR = "                    entry_dist_atr=payload.get(\"entry_dist_atr\"),\n"
ADD = "                    pine_structure=payload.get(\"structure\"),\n"

def main():
    src = open(BOT, encoding="utf-8").read()
    if "pine_structure=payload.get" in src:
        print("ALREADY PATCHED — nothing to do")
        return 0
    if src.count(ANCHOR) != 1:
        print(f"ABORT: anchor found {src.count(ANCHOR)}x, need exactly 1 — bot.py untouched")
        return 1
    bak = f"{BOT}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(BOT, bak)
    new = src.replace(ANCHOR, ANCHOR + ADD)
    open(BOT, "w", encoding="utf-8").write(new)
    try:
        ast.parse(new)
    except SyntaxError as e:
        shutil.copy2(bak, BOT)
        print(f"ABORT: compile failed ({e}) — bot.py RESTORED from {bak}")
        return 1
    print(f"PATCHED bot.py (backup {os.path.basename(bak)})")
    print("Log-only field. Restart v7 to activate; the column fills forward only.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
