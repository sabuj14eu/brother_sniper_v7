#!/usr/bin/env python3
"""TRUTH GUARDS (2026-08-31) — three anchor-safe bot.py edits, P0s from the
external review, each verified against the code before this was written.

1. POSITIONS-SHAPE GUARD: an executor error reply (500 JSON, or any body
   without a "positions" key) used to parse as an EMPTY position list, so
   every tracked trade looked closed. UNKNOWN is not FLAT.
2. UNVERIFIED-CLOSE GUARD: a ticket missing from /positions AND from
   /history was journaled as a $0 loss at entry — feeding consecutive-loss
   pause while the REAL position stayed open at the broker. Now the slot is
   held for 10 cycles; only then a LOUD unverified fallback close fires.
3. XFF GUARD: the IP allowlist trusted X-Forwarded-For from anyone. Now the
   header is honored only when the connection comes from our own nginx on
   loopback; direct hits are judged by their real address.

Ceremony: backup -> unique anchors or ABORT -> compile -> restore on fail.
    python3 patch_truth_guards.py
"""
import ast, os, shutil, sys, time

BOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")

EDITS = [
    ("positions-shape",
     "                    _r=_rq.get(_base+\"/positions\",timeout=5)\n"
     "                    _poslist=_r.json().get(\"positions\",[])\n",
     "                    _r=_rq.get(_base+\"/positions\",timeout=5)\n"
     "                    _pj=_r.json()\n"
     "                    if _r.status_code!=200 or \"positions\" not in _pj:\n"
     "                        log.warning(f\"[MON] positions UNKNOWN (HTTP {_r.status_code}) — closed!=unreachable, skipping cycle\"); continue\n"
     "                    _poslist=_pj.get(\"positions\") or []\n"),
    ("unverified-close",
     "                        log.warning(f\"[MON] Trade {oid} ({ac}/{tracked.get('symbol','?')}) not in history yet — using entry as fallback\")\n",
     "                        # [TRUTH-GUARD 08-31] missing deal = UNKNOWN, not a $0 close\n"
     "                        _miss=int(tracked.get(\"_hist_miss\") or 0)+1\n"
     "                        tracked[\"_hist_miss\"]=_miss; set_open_trade(ac, tracked)\n"
     "                        if _miss<10:\n"
     "                            log.warning(f\"[MON] {oid} gone from positions but NOT in history (miss {_miss}/10) — holding slot, not closing\")\n"
     "                            continue\n"
     "                        log.error(f\"[MON] {oid} absent {_miss} cycles — UNVERIFIED fallback close at entry\")\n"
     "                        send_telegram(f\"\\u26a0\\ufe0f <b>UNVERIFIED close</b>\\n{tracked.get('symbol')} <code>{oid}</code>\\nNo deal in /history after {_miss} checks — journaled at entry, VERIFY AT BROKER.\")\n"),
    ("xff-guard",
     "    ip=(request.headers.get(\"X-Forwarded-For\",request.remote_addr) or \"\").split(\",\")[0].strip()\n",
     "    _ra=request.remote_addr or \"\"\n"
     "    if _ra in (\"127.0.0.1\",\"::1\"):\n"
     "        ip=(request.headers.get(\"X-Forwarded-For\") or _ra).split(\",\")[0].strip()\n"
     "    else:\n"
     "        ip=_ra  # [TRUTH-GUARD 08-31] XFF is attacker-controlled unless our own nginx set it\n"),
]


def main():
    src = open(BOT, encoding="utf-8").read()
    if "[TRUTH-GUARD 08-31]" in src:
        print("ALREADY PATCHED — nothing to do")
        return 0
    for name, old, _ in EDITS:
        n = src.count(old)
        if n != 1:
            print(f"ABORT: anchor '{name}' found {n}x, need exactly 1 — bot.py untouched")
            return 1
    bak = f"{BOT}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(BOT, bak)
    for name, old, new in EDITS:
        src = src.replace(old, new)
    open(BOT, "w", encoding="utf-8").write(src)
    try:
        ast.parse(src)
    except SyntaxError as e:
        shutil.copy2(bak, BOT)
        print(f"ABORT: compile failed ({e}) — bot.py RESTORED from {bak}")
        return 1
    print(f"PATCHED bot.py — 3 truth guards (backup {os.path.basename(bak)})")
    print("Restart v7 to activate. No sizing, no gates, no payloads changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
