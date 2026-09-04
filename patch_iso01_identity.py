r"""
patch_iso01_identity.py -- v7 Windows bridge (sniper_executor.py) ONLY. Finding ISO-01.

Makes the bridge ASSERT the account behind its terminal on every request:
  V7_MT5_LOGIN (env) is the one account it may touch. Not set, or the terminal
  holds another login  ->  ensure_mt5() is False  ->  every order route answers
  503 and /health answers 503 ("mt5 disconnected"), which the bot already reads
  as down. Nothing on the accepted path changes (order_send request untouched).

Run on the Windows box, PowerShell as Administrator (the service file is a loose
copy in C:\Users\Administrator, so pass its path explicitly):
    python patch_iso01_identity.py C:\Users\Administrator\sniper_executor.py
Safe: backs up (<file>.bak.<stamp>), aborts UNTOUCHED unless both anchors
match exactly once, idempotent, py_compiles the result. Deploy ceremony:
backup -> patch -> compile -> set V7_MT5_LOGIN in the service env -> restart
-> verify /health says the asserted account. Evidence: tests/audit/2026-09-04_job3.
"""
import os, py_compile, shutil, sys, time

TGT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "sniper_executor.py")

MARK = "V7_MT5_LOGIN"

HEAD_OLD = '''def ensure_mt5():
    """Ensure MT5 is connected. Returns True if healthy, False if dead."""
    acc = mt5.account_info()
    if acc is not None:
        return True
'''
HEAD_NEW = '''# [ISO-01 2026-09-04] the ONE account this bridge may touch. No value = NOT
# RUNNABLE: every route answers 503 until it is set. Never a default (ADR-004).
V7_MT5_LOGIN = os.getenv("V7_MT5_LOGIN", "").strip()

def _identity_ok(acc):
    """The account behind the terminal must be the asserted one."""
    if not V7_MT5_LOGIN:
        log.critical("V7_MT5_LOGIN not set - identity unknown, refusing every order")
        return False
    if str(acc.login) != V7_MT5_LOGIN:
        log.critical(f"WRONG ACCOUNT: terminal holds {acc.login}, expected {V7_MT5_LOGIN} - refusing")
        return False
    return True

def ensure_mt5():
    """Ensure MT5 is connected TO THE ASSERTED ACCOUNT. False = refuse."""
    acc = mt5.account_info()
    if acc is not None:
        return _identity_ok(acc)
'''
TAIL_OLD = '''    log.info(f"MT5 reconnected: account {acc.login} balance {acc.balance}")
    return True
'''
TAIL_NEW = '''    log.info(f"MT5 reconnected: account {acc.login} balance {acc.balance}")
    return _identity_ok(acc)
'''


def main():
    if not os.path.exists(TGT):
        raise SystemExit(f"ABORT: {TGT} not found. Nothing written.")
    src = open(TGT, encoding="utf-8").read()
    if MARK in src:
        print(f"Already patched ({MARK} present) -- nothing to do: {TGT}")
        return
    for name, anchor in (("HEAD", HEAD_OLD), ("TAIL", TAIL_OLD)):
        n = src.count(anchor)
        if n != 1:
            raise SystemExit(f"ABORT: {name} anchor found {n} times (need exactly 1). Nothing written.")
    new = src.replace(HEAD_OLD, HEAD_NEW, 1).replace(TAIL_OLD, TAIL_NEW, 1)
    bak = f"{TGT}.bak.{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(TGT, bak)
    open(TGT, "w", encoding="utf-8", newline="").write(new)
    py_compile.compile(TGT, doraise=True)
    print(f"OK patched + compiled: {TGT}\nbackup: {bak}\nrollback: copy the backup over the file and restart the service")


if __name__ == "__main__":
    main()
