"""ANCHOR-SAFE box patch — entry_dist_atr into v7 telemetry (2026-08-21).

Run ON THE BOX, from the repo root, whatever branch its checkout is on:

    cd /home/shyam/brother_sniper_v7 && python3 patch_entry_dist_atr.py

Why a patch script and not a file copy: the box's bot.py belongs to another
session's branch. Copying a whole bot.py over it would silently drop that
session's work — the exact multi-session failure SESSION_COORDINATION.md
exists to prevent. This inserts THREE lines at unique anchors and touches
nothing else. Iron Rule 4: backup first, abort on ambiguous anchors,
compile before declaring success, restore backups on any failure.

What it adds (log-only, zero effect on trading):
  - learning/telemetry.py: "entry_dist_atr" in the market schema group
  - learning/telemetry.py: capture on rejected signals (capture_reject)
  - bot.py: capture at the open call site (the _cap block)
Pine v18.12 already sends the field on every scalp payload; the bot simply
stops dropping it. Forward-only: the n>=20-30 per bucket clock starts when
this lands. This is the SECOND population for the >3 ATR distance question.

After patching: sudo systemctl restart sniper-bot
Verify on the next trade or reject:
  tail -1 learning/telemetry.jsonl | python3 -c "import json,sys; print(json.load(sys.stdin).get('entry_dist_atr'))"
"""
from __future__ import annotations

import py_compile
import shutil
import sys
import time

EDITS = [
    # (file, unique anchor, text inserted immediately AFTER the anchor)
    ("learning/telemetry.py",
     '"dxy", "oil", "us10y", "vix", "volatility"],',
     None),  # special-cased below: list append needs the anchor REPLACED
    ("learning/telemetry.py",
     'dxy=payload.get("dxy_dir"), us10y=payload.get("yield_dir"),\n',
     '            entry_dist_atr=payload.get("entry_dist_atr"),\n'),
    ("bot.py",
     '                    us10y=payload.get("yield_dir"),\n',
     '                    entry_dist_atr=payload.get("entry_dist_atr"),\n'),
]

SCHEMA_OLD = '"dxy", "oil", "us10y", "vix", "volatility"],'
SCHEMA_NEW = ('"dxy", "oil", "us10y", "vix", "volatility",\n'
              '               "entry_dist_atr"],  # 08-21 append-only: Pine v18.12 sends it')


def main() -> int:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    texts, backups = {}, {}
    for path in {p for p, _, _ in EDITS}:
        with open(path, encoding="utf-8") as f:
            texts[path] = f.read()
        if "entry_dist_atr" in texts[path]:
            print(f"ALREADY PATCHED: {path} mentions entry_dist_atr — nothing to do.")
            return 0

    # verify EVERY anchor is unique before touching anything
    for path, anchor, _ in EDITS:
        n = texts[path].count(anchor)
        if n != 1:
            print(f"ABORT (no changes made): anchor appears {n}x in {path} "
                  f"(need exactly 1):\n  {anchor.strip()[:70]}")
            return 1

    for path in texts:
        backups[path] = f"{path}.bak-{stamp}"
        shutil.copy2(path, backups[path])

    texts["learning/telemetry.py"] = texts["learning/telemetry.py"].replace(
        SCHEMA_OLD, SCHEMA_NEW)
    for path, anchor, insert in EDITS:
        if insert is None:
            continue
        texts[path] = texts[path].replace(anchor, anchor + insert)

    for path, text in texts.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    try:
        for path in texts:
            py_compile.compile(path, doraise=True)
    except Exception as e:
        for path, bak in backups.items():
            shutil.copy2(bak, path)
        print(f"ABORT: compile failed, backups restored: {e}")
        return 1

    for path, bak in backups.items():
        print(f"PATCHED {path}  (backup: {bak})")
    print("OK — restart the service: sudo systemctl restart sniper-bot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
