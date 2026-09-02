#!/usr/bin/env python3
"""Restore v7's platform heartbeat + decision emitter on the deploy branch
(2026-09-03). The box ran the trade-desk branch until 2026-09-01; moving it
onto the deploy branch dropped core/v7_status and its two bot.py hooks, so
the platform read "v7 DOWN — last heartbeat 79880s ago" while the bot was
alive and trading (Iron Rule 6, the other way round: silence read as death).
Two hooks, both display-only and fully guarded, exactly as they were:
  1. _monitor(): after the SLOT-RECON sweep, update_heartbeat() every cycle
     (bridge_ok = the sweep reached the bridge; reconciliation not ported).
  2. webhook(): after REJECT-TELEMETRY, record_decision() for every verdict.
    python3 patch_v7_status_hooks.py
"""
import ast, os, shutil, sys, time

BOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")
MARK = "[V7-STATUS 2026-09-03]"
A_OLD = '        # ── [SLOT-RECON]: catch timeout-orphans — broker positions v7 isn\'t tracking ──\n'
A_NEW = '        _bridge_ok=True  # ' + MARK + '\n' + A_OLD
B_OLD = ('            log.warning(f"[SLOT-RECON] sweep failed: {_re2}")\n'
         '        if not any_open_trade(): continue\n')
B_NEW = ('            _bridge_ok=False  # ' + MARK + '\n'
         '            log.warning(f"[SLOT-RECON] sweep failed: {_re2}")\n'
         '        # ── ' + MARK + ' heartbeat every cycle — display-only, fully guarded,\n'
         '        # so the desk can tell "v7 quiet" apart from "v7 down" (Iron Rule 6).\n'
         '        try:\n'
         '            from core.v7_status import update_heartbeat\n'
         '            update_heartbeat(state, equity_guard.to_dict(), bridge_ok=_bridge_ok,\n'
         '                             symbols_enabled=ALLOWED_SYMBOLS, reconciliation=None)\n'
         '        except Exception as _he:\n'
         '            log.warning(f"[V7-STATUS] heartbeat skipped (non-fatal): {_he}")\n'
         '        if not any_open_trade(): continue\n')
C_OLD = ('        log.warning(f"[REJECT-TELEMETRY] skipped (non-fatal): {_re}")\n'
         '    return jsonify(result)\n')
C_NEW = ('        log.warning(f"[REJECT-TELEMETRY] skipped (non-fatal): {_re}")\n'
         '    # ── ' + MARK + ' every verdict to the platform desk (display-only, guarded;\n'
         '    # cannot affect the response). Pure noise (\'ignored\' chart annotations)\n'
         '    # is skipped; grade/v4_rr drops ARE verdicts and are kept.\n'
         '    try:\n'
         '        _st2=str((result or {}).get("status",""))\n'
         '        _mg2=str((result or {}).get("msg",""))\n'
         '        if _st2 in ("ok","rejected","blocked","filtered","skipped","paused") \\\n'
         '           or (_st2=="ignored" and ("grade" in _mg2 or "v4_rr" in _mg2)):\n'
         '            from core.v7_status import record_decision\n'
         '            record_decision(payload, result)\n'
         '    except Exception as _ve:\n'
         '        log.warning(f"[V7-STATUS] skipped (non-fatal): {_ve}")\n'
         '    return jsonify(result)\n')


def main():
    src = open(BOT, encoding="utf-8").read()
    if MARK in src:
        print("ALREADY PATCHED — nothing to do")
        return 0
    for name, old in (("slot-recon head", A_OLD), ("slot-recon tail", B_OLD), ("webhook tail", C_OLD)):
        if src.count(old) != 1:
            print(f"ABORT: {name} anchor found {src.count(old)}x, need exactly 1 — untouched")
            return 1
    bak = f"{BOT}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(BOT, bak)
    out = src.replace(A_OLD, A_NEW).replace(B_OLD, B_NEW).replace(C_OLD, C_NEW)
    open(BOT, "w", encoding="utf-8").write(out)
    try:
        ast.parse(out)
    except SyntaxError as e:
        shutil.copy2(bak, BOT)
        print(f"ABORT: compile failed ({e}) — RESTORED")
        return 1
    print(f"PATCHED bot.py — v7 heartbeat + decision emitter restored (backup {os.path.basename(bak)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
