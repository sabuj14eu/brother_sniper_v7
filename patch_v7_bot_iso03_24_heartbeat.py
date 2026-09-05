r"""
patch_v7_bot_iso03_24_heartbeat.py -- v7 BOT (Contabo, /home/shyam/brother_sniper_v7) ONLY.
Pre-state: main c1618f5/a3640d6 with the ISO-02 patch applied (bot.py, core/ic_markets.py at 4937532).

  ISO-03     core/ic_markets.py open_trade() sends account_id = V7_MT5_LOGIN with every order
             (empty env => the ISO-03 bridge refuses with no_account_id: fail closed).
  ISO-24     filters/ai_filter.py: the model vote is recorded as shadow evidence, it can no longer
             flip a rule block.
  heartbeat  core/ic_markets.py get_account(); core/v7_status.py build_heartbeat carries
             account_login + trade_mode (dropped when UNKNOWN); bot.py passes them.

Run on the Contabo box as shyam:
    python3 patch_v7_bot_iso03_24_heartbeat.py /home/shyam/brother_sniper_v7
Safe: every anchor of every file must match exactly once or NOTHING is written; backups
<file>.bak.<stamp>; py_compile; idempotent. Then add V7_MT5_LOGIN=52834417 to the bot .env and
restart sniper-bot. Verify: bot log shows no no_account_id refusals, /health ok. Deploy this BEFORE
the bridge patch. Evidence: tests/audit/2026-09-05_deploy_v7_bot.
"""
FILES = {'core/ic_markets.py': {'mark': 'def get_account',
                        'hunks': [('            log.warning(f"[CT] get_balance FAILED ({type(e).__name__}) - '
                                   'balance UNKNOWN, no fallback")\n'
                                   '            return None\n',
                                   '            log.warning(f"[CT] get_balance FAILED ({type(e).__name__}) - '
                                   'balance UNKNOWN, no fallback")\n'
                                   '            return None\n'
                                   '\n'
                                   '    def get_account(self):\n'
                                   '        """Measured account identity from the bridge\'s /health, or None '
                                   '= UNKNOWN.\n'
                                   '\n'
                                   '        [HEARTBEAT WORK ORDER 2026-09-05] display-only; the ISO-02 '
                                   'shape: a\n'
                                   '        non-200, a 200 without an account, or any exception is None and '
                                   'the\n'
                                   '        heartbeat then carries NO account keys rather than a guessed '
                                   'one.\n'
                                   '        Returns {"login", "trade_mode", "balance"}; trade_mode is '
                                   "MT5's\n"
                                   '        account_info().trade_mode (0 demo, 1 contest, 2 real) or None '
                                   'when the\n'
                                   '        bridge predates the field.\n'
                                   '        """\n'
                                   '        try:\n'
                                   '            url = self.executor_url.replace("/execute","/health")\n'
                                   '            r = requests.get(url, timeout=5)\n'
                                   '            if r.status_code != 200:\n'
                                   '                return None\n'
                                   '            j = r.json() or {}\n'
                                   '            if j.get("account") is None:\n'
                                   '                return None\n'
                                   '            return {"login": j.get("account"), "trade_mode": '
                                   'j.get("trade_mode"), "balance": j.get("balance")}\n'
                                   '        except Exception as e:\n'
                                   '            log.warning(f"[CT] get_account FAILED ({type(e).__name__}) - '
                                   'account UNKNOWN")\n'
                                   '            return None\n'),
                                  ('                "signal_id": comment,\n            }\n',
                                   '                "signal_id": comment,\n'
                                   '                # [ISO-03] the account this order is meant for; the '
                                   'bridge refuses any other.\n'
                                   '                # Empty here = the bridge answers no_account_id and '
                                   'nothing executes (fail closed).\n'
                                   '                "account_id": os.getenv("V7_MT5_LOGIN", "").strip(),\n'
                                   '            }\n')]},
 'core/v7_status.py': {'mark': 'account_login',
                       'hunks': [('                    symbols_enabled=None, reconciliation=None) -> dict:\n',
                                  '                    symbols_enabled=None, reconciliation=None,\n'
                                  '                    account_login=None, trade_mode=None) -> dict:\n'),
                                 ('        "bridge_ok": bridge_ok,\n        "open_slots": slots,\n',
                                  '        "bridge_ok": bridge_ok,\n'
                                  '        # [HEARTBEAT WORK ORDER 2026-09-05] append-only: the MEASURED '
                                  'login behind\n'
                                  '        # the bridge (asserted since ISO-01) and MT5 trade_mode (0 demo, '
                                  '1 contest,\n'
                                  '        # 2 real). None = UNKNOWN and the key is dropped below, never '
                                  'guessed.\n'
                                  '        "account_login": account_login,\n'
                                  '        "trade_mode": trade_mode,\n'
                                  '        "open_slots": slots,\n')]},
 'filters/ai_filter.py': {'mark': 'shadow_only',
                          'hunks': [('    if not passed and "news" in flags:\n'
                                     '        log.info(f"[FILTER] {symbol} {direction}: news-flagged block — '
                                     'AI override disabled")\n',
                                     '    # [ISO-24 2026-09-05] The model vote is SHADOW EVIDENCE ONLY. It '
                                     'is asked on a\n'
                                     '    # rule block (so the journal can grade it) and recorded in '
                                     'breakdown["deepseek"],\n'
                                     '    # but it can never turn `passed` from False to True. "No LLM in '
                                     'the decision\n'
                                     '    # path, ever" (V7_SELF_DEPENDENCE_PLAN); a model may remove risk, '
                                     'never add it.\n'
                                     '    # The override branch that used to live here is preserved in git '
                                     'history.\n'
                                     '    if not passed and "news" in flags:\n'
                                     '        log.info(f"[FILTER] {symbol} {direction}: news-flagged block — '
                                     'no model vote asked")\n'),
                                    ('                '
                                     'breakdown["deepseek"]={"take":_take,"confidence":_conf,"reason":_dsreason}\n'
                                     '                if _take and _conf>=60:\n'
                                     '                    passed=True\n'
                                     '                    reason=f"AI OVERRIDE (conf {_conf}): {_dsreason} | '
                                     'was: {reason}"\n'
                                     '                    log.info(f"[FILTER] {symbol} {direction}: DeepSeek '
                                     'OVERRODE block conf={_conf}")\n'
                                     '                else:\n'
                                     '                    reason=f"{reason} | AI agreed block (conf '
                                     '{_conf})"\n'
                                     '        except Exception as _e:\n'
                                     '            log.warning(f"[FILTER] DeepSeek hook error: {_e}")\n',
                                     '                '
                                     'breakdown["deepseek"]={"take":_take,"confidence":_conf,"reason":_dsreason,"shadow_only":True}\n'
                                     '                reason=f"{reason} | model vote recorded, not applied '
                                     '(take={_take} conf {_conf})"\n'
                                     '        except Exception as _e:\n'
                                     '            log.warning(f"[FILTER] model vote hook error (non-fatal, '
                                     'block stands): {_e}")\n')]},
 'bot.py': {'mark': 'HEARTBEAT WORK ORDER',
            'hunks': [('            update_heartbeat(state, equity_guard.to_dict(), bridge_ok=_bridge_ok,\n'
                       '                             symbols_enabled=ALLOWED_SYMBOLS, reconciliation=None)\n',
                       '            _acct=xtb.get_account() or {}   # [HEARTBEAT WORK ORDER 2026-09-05] None '
                       '= UNKNOWN -> keys dropped\n'
                       '            update_heartbeat(state, equity_guard.to_dict(), bridge_ok=_bridge_ok,\n'
                       '                             symbols_enabled=ALLOWED_SYMBOLS, reconciliation=None,\n'
                       '                             account_login=_acct.get("login"), '
                       'trade_mode=_acct.get("trade_mode"))\n')]}}

import os, py_compile, shutil, sys, time

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))


def main():
    plan, creates = {}, {}
    for rel, spec in FILES.items():
        tgt = os.path.join(ROOT, *rel.split("/"))
        if "create" in spec:                       # a NEW file: must not exist (or be identical already)
            if os.path.exists(tgt):
                if open(tgt, encoding="utf-8").read() == spec["create"]:
                    print(f"Already present (identical) -- skipping: {tgt}")
                    continue
                raise SystemExit(f"ABORT: {tgt} exists with different content. Nothing written anywhere.")
            compile(spec["create"], tgt, "exec")
            creates[tgt] = spec["create"]
            continue
        if not os.path.exists(tgt):
            raise SystemExit(f"ABORT: {tgt} not found. Nothing written anywhere.")
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
    if not plan and not creates:
        print("Nothing to do.")
        return
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for tgt, new in plan.items():
        bak = f"{tgt}.bak.{stamp}"
        shutil.copy2(tgt, bak)
        open(tgt, "w", encoding="utf-8", newline="").write(new)
        py_compile.compile(tgt, doraise=True)
        print(f"OK patched + compiled: {tgt}\n   backup: {bak}")
    for tgt, text in creates.items():
        os.makedirs(os.path.dirname(tgt), exist_ok=True)
        open(tgt, "w", encoding="utf-8", newline="").write(text)
        py_compile.compile(tgt, doraise=True)
        print(f"OK created + compiled: {tgt}   (new file; rollback = delete it)")
    print("rollback: copy each backup over its file (delete created files) and restart the service")


if __name__ == "__main__":
    main()
