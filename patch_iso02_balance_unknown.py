r"""
patch_iso02_balance_unknown.py -- v7 BOT (Contabo, /home/shyam/brother_sniper_v7) ONLY. Finding ISO-02.

An unreadable balance becomes None = UNKNOWN, never 1000.0 and never ACCOUNT_BALANCE:
  core/ic_markets.py  get_balance(): bridge non-200, 200 without a balance field, any
                      exception  ->  None (ACCOUNT_BALANCE in .env is dead config).
  risk/equity_guard.py check(None) blocks BEFORE update_balance touches state (W2-02
                      ordering); update_balance(None) is a no-op; status_summary(None) says UNKNOWN.
  bot.py              guard reuses the measured _bal_gate; calibration skips on None;
                      /health -> degraded + balance_state UNKNOWN; /recalibrate -> 503;
                      /status and the startup Telegram say UNKNOWN. No risk number changes.

Run on the Contabo box as shyam, pointing at the LIVE bot directory:
    python3 patch_iso02_balance_unknown.py /home/shyam/brother_sniper_v7
Safe: every anchor of every file must match exactly once or NOTHING is written; each
file is backed up (<file>.bak.<stamp>) then patched and py_compiled; idempotent.
Deploy ceremony: backup -> patch -> compile -> restart the bot -> verify /health
carries balance_state MEASURED and the log shows no "[CT] get_balance" warning.
Evidence: tests/audit/2026-09-05_iso02 (golden: script output == repo at 4937532).
"""
FILES = {'core/ic_markets.py': {'mark': '[ISO-02',
                        'hunks': [('    def get_balance(self):\n        try:\n',
                                   '    def get_balance(self):\n'
                                   '        """Measured balance as float, or None = UNKNOWN.\n'
                                   '\n'
                                   '        [ISO-02 2026-09-05] Never a number the broker did not say. The '
                                   "bridge's\n"
                                   '        own 503 ("mt5 disconnected"), a 200 without a balance field, and '
                                   'any\n'
                                   '        exception are all UNKNOWN. Every caller treats None as NO '
                                   'EXECUTION and\n'
                                   '        NO GUARD UPDATE (Freshness Law). ACCOUNT_BALANCE in .env is dead '
                                   'config.\n'
                                   '        """\n'
                                   '        try:\n'),
                                  ('            return float(r.json().get("balance", 1000.0))\n',
                                   '            if r.status_code != 200:\n'
                                   '                log.warning(f"[CT] get_balance: bridge answered '
                                   '{r.status_code} - balance UNKNOWN")\n'
                                   '                return None\n'
                                   '            bal = r.json().get("balance")\n'
                                   '            if bal is None:\n'
                                   '                log.warning("[CT] get_balance: 200 without a balance '
                                   'field - balance UNKNOWN")\n'
                                   '                return None\n'
                                   '            return float(bal)\n'),
                                  ('            fb = float(os.getenv("ACCOUNT_BALANCE","6000.0"))\n'
                                   '            log.warning(f"[CT] get_balance FAILED ({type(e).__name__}) - '
                                   'using conservative fallback {fb}")\n'
                                   '            return fb\n',
                                   '            log.warning(f"[CT] get_balance FAILED ({type(e).__name__}) - '
                                   'balance UNKNOWN, no fallback")\n'
                                   '            return None\n')]},
 'risk/equity_guard.py': {'mark': '[ISO-02',
                          'hunks': [('    def update_balance(self,bal):\n'
                                     '        today=date.today().isoformat(); '
                                     'wk=datetime.now(timezone.utc).strftime("%Y-W%W")\n',
                                     '    def update_balance(self,bal):\n'
                                     '        # [ISO-02] UNKNOWN balance never moves peak/day/week state.\n'
                                     '        if bal is None:\n'
                                     '            log.warning("[EQ] balance UNKNOWN - guard state not '
                                     'updated"); return\n'
                                     '        today=date.today().isoformat(); '
                                     'wk=datetime.now(timezone.utc).strftime("%Y-W%W")\n'),
                                    ('    def check(self,bal,consecutive_losses,max_losses=3):\n'
                                     '        self.update_balance(bal); eq=self.eq\n',
                                     '    def check(self,bal,consecutive_losses,max_losses=3):\n'
                                     '        # [ISO-02 2026-09-05] UNKNOWN balance = blocked, before any '
                                     'state is touched.\n'
                                     '        if bal is None:\n'
                                     '            return self._block("unknown",0,0,0,"balance UNKNOWN - '
                                     'bridge unreadable, no execution")\n'
                                     '        self.update_balance(bal); eq=self.eq\n'),
                                    ('    def status_summary(self,bal):\n'
                                     '        self.update_balance(bal); eq=self.eq\n',
                                     '    def status_summary(self,bal):\n'
                                     '        if bal is None:\n'
                                     '            eq=self.eq\n'
                                     '            return ("Equity: UNKNOWN (bridge unreadable)\\n"\n'
                                     '                    +"Peak: $"+str(round(eq.peak_balance,2))+" (last '
                                     'measured)\\n"\n'
                                     '                    +"Day PnL: UNKNOWN\\nWeek PnL: UNKNOWN\\nRisk: 0% '
                                     'per trade (no execution)\\n"\n'
                                     '                    +"Stopped: "+("YES" if eq.hard_stopped else '
                                     '"No"))\n'
                                     '        self.update_balance(bal); eq=self.eq\n')]},
 'bot.py': {'mark': '[ISO-02',
            'hunks': [('        try:\n'
                       '            bal=xtb.get_balance()\n'
                       '        except Exception: bal=1000.0\n',
                       '        bal=xtb.get_balance()   # [ISO-02] None = UNKNOWN, never a default\n'
                       '        if bal is None:\n'
                       '            log.warning("[CALIB] balance UNKNOWN - guard not updated, calibration '
                       'skipped this cycle")\n'
                       '            _shutdown.wait(CALIBRATION_HRS*3600); continue\n'),
                      ('    try: balance=xtb.get_balance()\n    except Exception: balance=1000.0\n',
                       '    # [ISO-02] the MEASURED number the gate above already accepted; never '
                       're-fetched, never defaulted\n'
                       '    balance=_bal_gate\n'),
                      ('    ok=xtb._connected and xtb._login_ok\n'
                       '    try: bal=xtb.get_balance()\n'
                       '    except Exception: bal=0\n',
                       '    bal=xtb.get_balance()   # [ISO-02] None = UNKNOWN; health is then degraded/503 '
                       '(Iron Rule 6)\n'
                       '    ok=xtb._connected and xtb._login_ok and bal is not None\n'),
                      ('        "status":"ok" if ok else "degraded","xtb":ok,"demo":USE_DEMO,\n'
                       '        "paused":state.get("paused"),\n',
                       '        "status":"ok" if ok else "degraded","xtb":ok,"demo":USE_DEMO,\n'
                       '        "balance":bal,"balance_state":"MEASURED" if bal is not None else "UNKNOWN",\n'
                       '        "paused":state.get("paused"),\n'),
                      ('    if (request.get_json(force=True) or {}).get("secret")!=WEBHOOK_SECRET: '
                       'abort(403)\n'
                       '    try: bal=xtb.get_balance()\n'
                       '    except Exception: bal=1000.0\n'
                       '    '
                       'daily_dd=max(0,-equity_guard.eq.day_pnl)/max(equity_guard.eq.day_open_balance,1)\n',
                       '    if (request.get_json(force=True) or {}).get("secret")!=WEBHOOK_SECRET: '
                       'abort(403)\n'
                       '    bal=xtb.get_balance()   # [ISO-02]\n'
                       '    if bal is None:\n'
                       '        return jsonify({"status":"error","msg":"balance UNKNOWN - recalibration '
                       'refused"}),503\n'
                       '    equity_guard.update_balance(bal)\n'
                       '    '
                       'daily_dd=max(0,-equity_guard.eq.day_pnl)/max(equity_guard.eq.day_open_balance,1)\n'),
                      ('    try: bal=xtb.get_balance()\n'
                       '    except Exception: bal=0\n'
                       '    return '
                       'jsonify({"state":state,"equity":equity_guard.status_summary(bal),"timestamp":datetime.now().isoformat()})\n',
                       '    bal=xtb.get_balance()   # [ISO-02] None -> status_summary says UNKNOWN\n'
                       '    return jsonify({"state":state,"balance":bal,"balance_state":"MEASURED" if bal is '
                       'not None else "UNKNOWN",\n'
                       '                    '
                       '"equity":equity_guard.status_summary(bal),"timestamp":datetime.now().isoformat()})\n'),
                      ('\n'
                       '    try: bal=xtb.get_balance()\n'
                       '    except Exception: bal=1000.0\n'
                       '    equity_guard.update_balance(bal)\n',
                       '\n'
                       '    bal=xtb.get_balance()   # [ISO-02] None = UNKNOWN: guard untouched, Telegram '
                       'says so\n'
                       '    equity_guard.update_balance(bal)\n'),
                      ('    w=load_weights(); mem=stats_summary(50)\n\n',
                       '    w=load_weights(); mem=stats_summary(50)\n'
                       '    _bal_txt=f"<code>${bal:.2f}</code>  Ready." if bal is not None else '
                       '"<b>UNKNOWN</b> (bridge unreadable - no trades until measured)"\n'
                       '\n'),
                      ('        f"Balance:    <code>${bal:.2f}</code>  Ready."\n',
                       '        f"Balance:    {_bal_txt}"\n')]}}

import os, py_compile, shutil, sys, time

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))


def main():
    plan = {}
    for rel, spec in FILES.items():
        tgt = os.path.join(ROOT, *rel.split("/"))
        if not os.path.exists(tgt):
            raise SystemExit(f"ABORT: {tgt} not found. Nothing written.")
        src = open(tgt, encoding="utf-8").read()
        if spec["mark"] in src:
            print(f"Already patched ({spec['mark']} present) -- skipping: {tgt}")
            continue
        cur = src
        for i, (old, new) in enumerate(spec["hunks"], 1):
            n = cur.count(old)
            if n != 1:
                raise SystemExit(f"ABORT: {rel} hunk {i}/{len(spec['hunks'])} anchor found {n} times "
                                 f"(need exactly 1). Nothing written anywhere.")
            cur = cur.replace(old, new, 1)
        compile(cur, tgt, "exec")          # syntax-check BEFORE any file is touched
        plan[tgt] = cur
    if not plan:
        print("Nothing to do.")
        return
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for tgt, new in plan.items():
        bak = f"{tgt}.bak.{stamp}"
        shutil.copy2(tgt, bak)
        open(tgt, "w", encoding="utf-8", newline="").write(new)
        py_compile.compile(tgt, doraise=True)
        print(f"OK patched + compiled: {tgt}\n   backup: {bak}")
    print("rollback: copy each backup over its file and restart the service")


if __name__ == "__main__":
    main()
