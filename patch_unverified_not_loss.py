#!/usr/bin/env python3
"""A1 round 2 (2026-09-02): the 10-miss fallback close still counted the
fake $0 as a LOSS (net=0 -> won=False -> consecutive_losses+1 -> pause).
An UNKNOWN outcome must never feed the loss streak. Requires the
[TRUTH-GUARD 08-31] patch to be applied first (it sets _hist_miss).

    python3 patch_unverified_not_loss.py
"""
import ast, os, shutil, sys, time

BOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")
OLD = ('                    else: state["consecutive_losses"]=state.get("consecutive_losses",0)+1; '
       'state["total_losses"]=state.get("total_losses",0)+1; emoji,tag="❌",f"LOSS ${net:.2f}"\n')
NEW = ('                    elif deal is None: emoji,tag="❓",f"UNVERIFIED ${net:.2f}"  '
       '# [TRUTH-GUARD-V2 09-02] unknown outcome is never a loss: no streak, no loss count\n'
       '                    else: state["consecutive_losses"]=state.get("consecutive_losses",0)+1; '
       'state["total_losses"]=state.get("total_losses",0)+1; emoji,tag="❌",f"LOSS ${net:.2f}"\n')


def main():
    src = open(BOT, encoding="utf-8").read()
    if "[TRUTH-GUARD-V2 09-02]" in src:
        print("ALREADY PATCHED — nothing to do")
        return 0
    if "[TRUTH-GUARD 08-31]" not in src:
        print("ABORT: apply patch_truth_guards.py first (this extends it)")
        return 1
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
    print(f"PATCHED bot.py — unverified close counts NO loss (backup {os.path.basename(bak)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
