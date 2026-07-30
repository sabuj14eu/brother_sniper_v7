"""
patch_v7_atr_floor.py -- v7 bot.py ONLY.  [F9 2026-07-10]

FINDING: v7's trust-mode SL floor (sl_result.sl_distance) is a legacy
percent-of-price floor (~1.5%) designed for swing trades. Pine v18.6 sends
structural scalp stops (already floored at 0.7 ATR at source). Result:
SILVER floor 0.908 vs Pine 0.3696 (floor = 4.7x live ATR!) -> widen-ratio
guard rejects at 2.46x -> v7 rejects essentially EVERY v18 signal ->
the A/B experiment's mechanical arm never trades -> no evidence.

FIX: in trust mode, the floor becomes 1.2 x live M15 ATR (the real ATR v7
now fetches since the bridge revival), falling back to the legacy engine
floor only when ATR is unavailable. The 1.6x widen-ratio guard is KEPT --
it still rejects genuinely noise-tight stops (Pine dist < 0.75 ATR).

Example (SILVER, live ATR 0.19257): floor 0.908 -> 0.231.
Pine stop 0.3696 now passes VERBATIM. No R:R collapse possible.

One-line change. Run from /home/shyam/brother_sniper_v7/ :
    python3 patch_v7_atr_floor.py
Then: sudo systemctl restart sniper-bot.service
Aborts untouched on anchor mismatch. Backs up, compiles, auto-restores.
"""
import os, shutil, py_compile, datetime

TGT = "bot.py"

OLD = """        engine_floor = sl_result.sl_distance
        pine_dist    = abs(entry - raw_sl)"""

NEW = """        # [F9 2026-07-10] scalp-aware floor: the legacy percent floor (~1.5%)
        # was 4-5x live ATR and starved the v7 A/B arm (rejected ~every v18
        # scalp stop). Pine v18.6 already floors SL at 0.7 ATR at source --
        # mirror that here: 1.2x live M15 ATR when ATR is known, else legacy.
        engine_floor = (1.2 * atr) if (atr is not None and atr > 0) else sl_result.sl_distance
        pine_dist    = abs(entry - raw_sl)"""


def main():
    if not os.path.exists(TGT):
        raise SystemExit("ABORT: bot.py not found. Run from /home/shyam/brother_sniper_v7/.")
    src = open(TGT, encoding="utf-8").read()

    if "[F9 2026-07-10]" in src:
        print("F9 ATR floor already present -- nothing to do.")
        return

    n = src.count(OLD)
    if n != 1:
        raise SystemExit(f"ABORT: anchor found {n} times (need exactly 1). Nothing written.\n"
                         "Run: grep -n 'engine_floor = sl_result' bot.py  and paste the output.")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"bot.py.bak_f9_{stamp}"
    shutil.copy2(TGT, bak)

    src = src.replace(OLD, NEW, 1)
    open(TGT, "w", encoding="utf-8").write(src)

    try:
        py_compile.compile(TGT, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, TGT)
        raise SystemExit(f"ABORT: compile failed, restored from backup.\n{e}")

    print(f"OK [F9]: trust-mode floor is now 1.2x live ATR (legacy fallback kept). Backup: {bak}")
    print("Now: sudo systemctl restart sniper-bot.service")


if __name__ == "__main__":
    main()
