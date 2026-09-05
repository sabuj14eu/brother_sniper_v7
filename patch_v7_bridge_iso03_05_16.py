r"""
patch_v7_bridge_iso03_05_16.py -- v7 Windows bridge (C:\Users\Administrator\sniper_executor.py) ONLY.
Findings ISO-03, ISO-05, ISO-16 + heartbeat work order item 1. Pre-state: the ISO-01-patched file.

  ISO-03  /execute requires account_id == V7_MT5_LOGIN (400 no_account_id / 403 account_mismatch);
          every order carries magic V7_MAGIC_NUMBER (default 70007).
  ISO-05  /close and /modify act only on v7's own positions (magic 70007 or comment BS_*): 403 not_ours.
  ISO-16  ONE shared stop file (GLOBAL_STOP_FILE, default C:\brotherbot\GLOBAL_STOP) refuses every new
          order (UNKNOWN = STOP); POST /admin/halt (X-Admin-Token == ADMIN_HALT_TOKEN) engages it;
          /admin/status; /health gains trade_mode, global_stop, magic.

Run on the Windows box, PowerShell as Administrator, pointing at the DIRECTORY holding the file:
    python patch_v7_bridge_iso03_05_16.py C:\Users\Administrator
Safe: every anchor must match exactly once or NOTHING is written; backup <file>.bak.<stamp>;
py_compile; idempotent. ORDER: deploy the v7 BOT patch (patch_v7_bot_iso03_24_heartbeat.py) and
V7_MT5_LOGIN in the bot .env FIRST - after this patch the bridge refuses orders without account_id.
Service env (NSSM AppEnvironmentExtra REPLACES the set): V7_MT5_LOGIN=52834417 V7_MAGIC_NUMBER=70007
ADMIN_HALT_TOKEN=<secret>. Create C:\brotherbot before restart. Verify: /health shows account, magic,
trade_mode, global_stop CLEAR. Evidence: tests/audit/2026-09-05_deploy_v7_bridge.
"""
FILES = {'sniper_executor.py': {'mark': '[ISO-16',
                        'hunks': [('SECRET = os.getenv("WEBHOOK_SECRET", "")\n\n',
                                   'SECRET = os.getenv("WEBHOOK_SECRET", "")\n'
                                   '\n'
                                   "# [ISO-03 2026-09-05] every v7 order carries v7's magic so the "
                                   'reconciler, the\n'
                                   "# platform and /close /modify can tell v7's positions from anyone "
                                   "else's.\n"
                                   '# A tag, not a risk number; documented in .env.example.\n'
                                   'V7_MAGIC = int(os.getenv("V7_MAGIC_NUMBER", "70007"))\n'
                                   '\n'
                                   '\n'
                                   '# [ISO-16 2026-09-05, ADR-008] GLOBAL emergency stop: ONE file both '
                                   'executors on\n'
                                   '# this box read before every new order. Present = STOP, absent = CLEAR, '
                                   'unreadable\n'
                                   '# = UNKNOWN (treated as STOP). Identical logic lives in the v18 '
                                   'executor\n'
                                   '# (executor_ic_markets/src/utils/global_stop.py); keep the two in step.\n'
                                   'def _global_stop_path():\n'
                                   '    p = (os.getenv("GLOBAL_STOP_FILE") or "").strip()\n'
                                   '    if p:\n'
                                   '        return p\n'
                                   '    return r"C:\\brotherbot\\GLOBAL_STOP" if os.name == "nt" else '
                                   '"/var/lib/brotherbot/GLOBAL_STOP"\n'
                                   '\n'
                                   '\n'
                                   'def _global_stop_state():\n'
                                   '    try:\n'
                                   '        return "STOP" if os.path.exists(_global_stop_path()) else '
                                   '"CLEAR"\n'
                                   '    except Exception:\n'
                                   '        return "UNKNOWN"\n'
                                   '\n'
                                   '\n'
                                   'def _global_stop_engage(reason, who="sniper_executor_v7"):\n'
                                   '    p = _global_stop_path()\n'
                                   '    try:\n'
                                   '        d = os.path.dirname(p)\n'
                                   '        if d:\n'
                                   '            os.makedirs(d, exist_ok=True)\n'
                                   '        with open(p, "a", encoding="utf-8") as f:\n'
                                   '            f.write(f"{datetime.utcnow().isoformat()}Z {who}: '
                                   '{reason}\\n")\n'
                                   '    except Exception as e:\n'
                                   '        log.error(f"[GLOBAL-STOP] could not write {p}: {e}")\n'
                                   '    return p\n'
                                   '\n'
                                   '\n'
                                   'ADMIN_HALT_TOKEN = os.getenv("ADMIN_HALT_TOKEN", "").strip()\n'
                                   '\n'
                                   '\n'
                                   'def _is_ours(pos) -> bool:\n'
                                   '    """[ISO-05] a position is v7\'s if it carries V7_MAGIC or the legacy '
                                   "'BS_' comment\n"
                                   '    (positions opened before ISO-03 have magic 0 and a BS_<signal> '
                                   'comment)."""\n'
                                   '    try:\n'
                                   '        if int(getattr(pos, "magic", 0) or 0) == V7_MAGIC:\n'
                                   '            return True\n'
                                   '    except (TypeError, ValueError):\n'
                                   '        pass\n'
                                   '    return str(getattr(pos, "comment", "") or "").startswith("BS_")\n'
                                   '\n'),
                                  ('        return '
                                   'jsonify({"status":"ok","account":acc.login,"balance":acc.balance,"equity":acc.equity,"git_commit":_GIT_COMMIT,"service_version":"sniper-executor-v7"})\n',
                                   '        return '
                                   'jsonify({"status":"ok","account":acc.login,"balance":acc.balance,"equity":acc.equity,\n'
                                   '                        '
                                   '"trade_mode":getattr(acc,"trade_mode",None),          # heartbeat work '
                                   'order item 1\n'
                                   '                        '
                                   '"global_stop":_global_stop_state(),                    # [ISO-16]\n'
                                   '                        '
                                   '"git_commit":_GIT_COMMIT,"service_version":"sniper-executor-v7"})\n'),
                                  ('                 '
                                   '"price_open":p.price_open,"price_current":p.price_current,"sl":p.sl,"tp":p.tp,"comment":p.comment}\n',
                                   '                 '
                                   '"price_open":p.price_open,"price_current":p.price_current,"sl":p.sl,"tp":p.tp,"comment":p.comment,\n'
                                   '                 "magic":getattr(p,"magic",None),"ours":_is_ours(p)}   # '
                                   '[ISO-03/05] append-only\n'),
                                  ('\n        # Symbol resolution\n',
                                   '\n'
                                   '        # [ISO-03] the caller must name the account it means; it must be '
                                   'the one this\n'
                                   '        # bridge asserts (ISO-01). Missing or different = no execution '
                                   '(ADR-004).\n'
                                   '        _acct = str(data.get("account_id") or "").strip()\n'
                                   '        if not _acct:\n'
                                   '            log.error(f"[EXEC] {signal_id} no account_id in request - '
                                   'refusing")\n'
                                   '            return jsonify({"status":"error","msg":"no_account_id"}), '
                                   '400\n'
                                   '        if _acct != V7_MT5_LOGIN:\n'
                                   '            log.critical(f"[EXEC] {signal_id} account_mismatch: request '
                                   'says {_acct}, bridge asserts {V7_MT5_LOGIN} - refusing")\n'
                                   '            return jsonify({"status":"error","msg":"account_mismatch"}), '
                                   '403\n'
                                   '\n'
                                   '        # [ISO-16] the GLOBAL stop refuses every new order on this box '
                                   '(UNKNOWN = STOP)\n'
                                   '        _gs = _global_stop_state()\n'
                                   '        if _gs != "CLEAR":\n'
                                   '            log.critical(f"[EXEC] {signal_id} GLOBAL STOP {_gs} '
                                   '({_global_stop_path()}) - refusing")\n'
                                   '            return '
                                   'jsonify({"status":"error","msg":"global_stop","state":_gs}), 503\n'
                                   '\n'
                                   '        # Symbol resolution\n'),
                                  ('            "comment": "BS_" + '
                                   '__import__("hashlib").md5(str(signal_id).encode()).hexdigest()[:8],\n'
                                   '            "type_time": mt5.ORDER_TIME_GTC,\n'
                                   '            "type_filling": mt5.ORDER_FILLING_IOC,\n'
                                   '        }\n'
                                   '        log.info(f"[EXEC] {signal_id} order_send: {direction} {symbol} '
                                   'vol={volume} px={price} sl={sl} tp={tp}")\n',
                                   '            "magic": V7_MAGIC,   # [ISO-03] v7\'s positions are no '
                                   'longer anonymous\n'
                                   '            "comment": "BS_" + '
                                   '__import__("hashlib").md5(str(signal_id).encode()).hexdigest()[:8],\n'
                                   '            "type_time": mt5.ORDER_TIME_GTC,\n'
                                   '            "type_filling": mt5.ORDER_FILLING_IOC,\n'
                                   '        }\n'
                                   '        log.info(f"[EXEC] {signal_id} order_send: {direction} {symbol} '
                                   'vol={volume} px={price} sl={sl} tp={tp} magic={V7_MAGIC} '
                                   'account={_acct}")\n'),
                                  ('        pos = positions[0]\n        _req_vol = data.get("volume")\n',
                                   '        pos = positions[0]\n'
                                   '        if not _is_ours(pos):   # [ISO-05] never close what v7 did not '
                                   'open\n'
                                   '            log.critical(f"[CLOSE] ticket {ticket} '
                                   "magic={getattr(pos,'magic',None)} comment={pos.comment!r} is not v7's - "
                                   'refusing")\n'
                                   '            return jsonify({"status":"error","msg":"not_ours"}), 403\n'
                                   '        _req_vol = data.get("volume")\n'),
                                  ('        pos = positions[0]\n'
                                   '        new_sl = float(data.get("sl", pos.sl))\n',
                                   '        pos = positions[0]\n'
                                   '        if not _is_ours(pos):   # [ISO-05] never re-stop what v7 did not '
                                   'open\n'
                                   '            log.critical(f"[MODIFY] ticket {ticket} '
                                   "magic={getattr(pos,'magic',None)} comment={pos.comment!r} is not v7's - "
                                   'refusing")\n'
                                   '            return jsonify({"status":"error","msg":"not_ours"}), 403\n'
                                   '        new_sl = float(data.get("sl", pos.sl))\n'),
                                  ('\nif __name__ == "__main__":\n',
                                   '\n'
                                   "# [ISO-16] panic button with the same contract as the v18 executor's "
                                   'halt_admin.py:\n'
                                   '# X-Admin-Token header, 503 when no token is configured, 401 when wrong. '
                                   'Engaging\n'
                                   "# writes the shared witness, so it stops the v18 executor's new orders "
                                   'as well.\n'
                                   '@app.route("/admin/halt", methods=["POST"])\n'
                                   'def admin_halt():\n'
                                   '    if not ADMIN_HALT_TOKEN:\n'
                                   '        return jsonify({"status":"error","msg":"ADMIN_HALT_TOKEN not '
                                   'configured"}), 503\n'
                                   '    if not '
                                   '__import__("secrets").compare_digest(request.headers.get("X-Admin-Token", '
                                   '""), ADMIN_HALT_TOKEN):\n'
                                   '        return jsonify({"status":"error","msg":"bad admin token"}), 401\n'
                                   '    data = request.get_json(silent=True) or {}\n'
                                   '    reason = str(data.get("reason") or "manual_admin_halt")\n'
                                   '    p = _global_stop_engage(reason)\n'
                                   '    log.critical(f"[GLOBAL-STOP] engaged by admin: {reason} -> {p}")\n'
                                   '    return '
                                   'jsonify({"status":"halted","reason":reason,"global_stop":_global_stop_state(),"file":p})\n'
                                   '\n'
                                   '\n'
                                   '@app.route("/admin/status", methods=["GET"])\n'
                                   'def admin_status():\n'
                                   '    if not ADMIN_HALT_TOKEN:\n'
                                   '        return jsonify({"status":"error","msg":"ADMIN_HALT_TOKEN not '
                                   'configured"}), 503\n'
                                   '    if not '
                                   '__import__("secrets").compare_digest(request.headers.get("X-Admin-Token", '
                                   '""), ADMIN_HALT_TOKEN):\n'
                                   '        return jsonify({"status":"error","msg":"bad admin token"}), 401\n'
                                   '    return '
                                   'jsonify({"global_stop":_global_stop_state(),"file":_global_stop_path(),\n'
                                   '                    "asserted_login":V7_MT5_LOGIN,"magic":V7_MAGIC})\n'
                                   '\n'
                                   '\n'
                                   'if __name__ == "__main__":\n')]}}

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
