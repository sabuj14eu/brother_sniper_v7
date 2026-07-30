"""
patch_v7_bsv11.py -- v7 bot.py ONLY. Adds BSv11 (LITE v11) as a trusted system.

Two two-string edits, no logic change:
  1. line ~670 secret auto-inject list  -> add "BSv11"
  2. line ~954 trust-mode list          -> add "BSV11"

Effect: v7 accepts BSv11 alerts (direct or via relay) and honours the Pine's
own laddered SL in trust mode instead of rebuilding it. Completely inert until
a payload with system=="BSv11" actually arrives.

Run from /home/shyam/brother_sniper_v7/ :
    python3 patch_v7_bsv11.py
Safe: backs up bot.py, aborts untouched on any anchor mismatch. Re-runnable.
"""
import os, shutil, py_compile, datetime

TGT = "bot.py"

OLD_SECRET = '        if payload.get("system") in ("BSv16","BSv17","BSv18") or payload.get("version","").startswith("v9") or payload.get("bot","").startswith("BS_"):'
NEW_SECRET = '        if payload.get("system") in ("BSv16","BSv17","BSv18","BSv11") or payload.get("version","").startswith("v9") or payload.get("bot","").startswith("BS_"):'

OLD_TRUST = '        _sys_trust in ("BSV17","BSV18") or'
NEW_TRUST = '        _sys_trust in ("BSV17","BSV18","BSV11") or'


def main():
    if not os.path.exists(TGT):
        raise SystemExit(f"ABORT: {TGT} not found. Run from /home/shyam/brother_sniper_v7/.")
    src = open(TGT, encoding="utf-8").read()

    if "BSv11" in src and "BSV11" in src:
        print("BSv11 already present -- nothing to do.")
        return

    for label, anchor in (("secret-inject", OLD_SECRET), ("trust-mode", OLD_TRUST)):
        n = src.count(anchor)
        if n != 1:
            raise SystemExit(f"ABORT: {label} anchor found {n} times (need exactly 1). Nothing written.")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TGT}.bak_bsv11_{stamp}"
    shutil.copy2(TGT, bak)

    src = src.replace(OLD_SECRET, NEW_SECRET).replace(OLD_TRUST, NEW_TRUST)
    open(TGT, "w", encoding="utf-8").write(src)

    try:
        py_compile.compile(TGT, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, TGT)
        raise SystemExit(f"ABORT: compile failed, restored from backup.\n{e}")

    print(f"OK: BSv11 added to secret-inject + trust-mode. Backup: {bak}")
    print("Now: sudo systemctl restart sniper-bot.service")


if __name__ == "__main__":
    main()
