"""ANCHOR-SAFE box patch — mirror trade CLOSES to the platform (2026-08-22).

Run ON THE BOX, from the repo root, whatever branch its checkout is on:

    cd /home/shyam/brother_sniper_v7 && python3 patch_mirror_close.py

THE HOLE (measured, 2026-08-22): the box's learning/platform_mirror.py
(8517 bytes) already defines mirror_v7_close, but the box's bot.py never
calls it — so opens and rejects reach the platform while CLOSES do not,
and /chart keeps drawing a closed trade's levels until the 12h TTL.

THE FIX: insert the exact wiring the mirror branch carries (same guard,
same log line, so the branches converge textually) immediately after the
close bookkeeping, where tracked/net/won/cp/_hold are all in scope:

    equity_guard.record_trade(net, tracked["symbol"])   <- unique anchor
    + try: mirror_v7_close(tracked, net, won, ...)      <- fire-and-forget

Read-only mirror law: display data only; a failure is logged and the
close path continues untouched. Iron Rule 4: backup first, abort on
ambiguous anchors, compile before declaring success, restore on failure.

After patching: sudo systemctl restart sniper-bot
Verify on the next close: journalctl -u sniper-bot | grep MIRROR   (only
appears if a post fails) and the platform's /chart dropping the levels.
"""
from __future__ import annotations

import os
import py_compile
import shutil
import sys
import time

BOT = "bot.py"
MODULE = os.path.join("learning", "platform_mirror.py")
ANCHOR = '                    equity_guard.record_trade(net, tracked["symbol"])\n'
INSERT = (
    "                    # ── [08-22] platform mirror: trade OUTCOME, fire-and-forget.\n"
    "                    try:\n"
    "                        from learning.platform_mirror import mirror_v7_close\n"
    "                        mirror_v7_close(tracked, net, won, close_price=float(cp), hold_seconds=_hold)\n"
    "                    except Exception as _pm:\n"
    "                        log.warning(f\"[MIRROR] close skipped (non-fatal): {_pm}\")\n"
)


def main() -> int:
    with open(BOT, encoding="utf-8") as f:
        bot = f.read()
    if "mirror_v7_close" in bot:
        print("ALREADY PATCHED: bot.py calls mirror_v7_close — nothing to do.")
        return 0
    try:
        with open(MODULE, encoding="utf-8") as f:
            module = f.read()
    except FileNotFoundError:
        print(f"ABORT (no changes made): {MODULE} does not exist on this box. "
              f"Take it first:\n  git fetch origin claude/brain-platform-mirror-fcacwl"
              f" && git checkout FETCH_HEAD -- {MODULE}")
        return 1
    if "def mirror_v7_close" not in module:
        print(f"ABORT (no changes made): {MODULE} exists but has no "
              f"mirror_v7_close — it predates the close mirror. Take the "
              f"newer copy:\n  git fetch origin claude/brain-platform-mirror-fcacwl"
              f" && git checkout FETCH_HEAD -- {MODULE}\nthen re-run this patch.")
        return 1
    n = bot.count(ANCHOR)
    if n != 1:
        print(f"ABORT (no changes made): anchor appears {n}x in bot.py "
              f"(need exactly 1): {ANCHOR.strip()}")
        return 1

    bak = f"{BOT}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(BOT, bak)
    with open(BOT, "w", encoding="utf-8") as f:
        f.write(bot.replace(ANCHOR, ANCHOR + INSERT))
    try:
        py_compile.compile(BOT, doraise=True)
    except Exception as e:
        shutil.copy2(bak, BOT)
        print(f"ABORT: compile failed, backup restored: {e}")
        return 1
    print(f"PATCHED {BOT}  (backup: {bak})")
    print("OK — restart the service: sudo systemctl restart sniper-bot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
