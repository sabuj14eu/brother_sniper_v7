"""ANCHOR-SAFE box patch — freshness gate v1, SHADOW mode (2026-08-22).

Run ON THE BOX, from the repo root, whatever branch its checkout is on:

    cd /home/shyam/brother_sniper_v7 && python3 patch_freshness_gate.py

Inserts the autonomy-order stage-2 gate immediately before Execute, at
the point where signal_age_seconds_v is in scope. SHADOW BY DEFAULT:
until V7_FRESHNESS_GATE=enforce is set (an explicit human decision made
after reading the shadow evidence, n>=20), this logs and telemetry-tags
what it WOULD have blocked and changes no trade. Requires
filters/freshness_gate.py (take it with this script). Iron Rule 4:
backup, unique anchor or abort, compile or restore.
"""
from __future__ import annotations

import os
import py_compile
import shutil
import sys
import time

BOT = "bot.py"
MODULE = os.path.join("filters", "freshness_gate.py")
ANCHOR = "    lot,_=calc_lot(symbol,entry,inst_sl,balance,effective_risk)\n"
INSERT = (
    "\n"
    "    # ── [08-22 FRESHNESS GATE v1 — autonomy stage 2, SHADOW default] A\n"
    "    # stale evaluation is never authoritative. Shadow logs what it WOULD\n"
    "    # block; only V7_FRESHNESS_GATE=enforce (explicit human decision,\n"
    "    # after shadow evidence n>=20) makes it real. Fully guarded. ──\n"
    "    try:\n"
    "        from filters.freshness_gate import gate_from_env as _fg_eval\n"
    "        _fg = _fg_eval(signal_age_s=signal_age_seconds_v)\n"
    "        if _fg[\"blocked\"]:\n"
    "            log.warning(f\"[FRESH-GATE {_fg['mode'].upper()}] {symbol} {direction} \"\n"
    "                        f\"{_fg['state']}: {_fg['reason']}\")\n"
    "            try:\n"
    "                from learning.telemetry import capture_reject\n"
    "                capture_reject(payload, f\"freshness_{_fg['mode']}\", _fg[\"reason\"])\n"
    "            except Exception: pass\n"
    "            if _fg[\"mode\"] == \"enforce\":\n"
    "                return {\"status\":\"blocked\",\n"
    "                        \"msg\":f\"DECISION BLOCKED — DATA FRESHNESS: {_fg['reason']}\"}\n"
    "    except Exception as _fge:\n"
    "        log.warning(f\"[FRESH-GATE] skipped (non-fatal): {_fge}\")\n"
)


def main() -> int:
    with open(BOT, encoding="utf-8") as f:
        bot = f.read()
    if "freshness_gate" in bot:
        print("ALREADY PATCHED: bot.py references freshness_gate — nothing to do.")
        return 0
    if not os.path.exists(MODULE):
        print(f"ABORT (no changes made): {MODULE} missing. Take it first:\n"
              f"  git fetch origin claude/evidence-integrity-audit-35rlfa"
              f" && git checkout FETCH_HEAD -- {MODULE}")
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
        py_compile.compile(MODULE, doraise=True)
    except Exception as e:
        shutil.copy2(bak, BOT)
        print(f"ABORT: compile failed, backup restored: {e}")
        return 1
    print(f"PATCHED {BOT}  (backup: {bak})")
    print("MODE: shadow (V7_FRESHNESS_GATE unset). Nothing is blocked yet —\n"
          "read the shadow evidence first, then enforce deliberately.")
    print("OK — restart the service: sudo systemctl restart sniper-bot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
