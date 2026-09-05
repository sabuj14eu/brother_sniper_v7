# EVIDENCE — the ISO-06 proposal as anchor hunks over the CURRENT sniper_executor.py. NOT applied.
"""apply(text) turns today's sniper_executor.py into fixtures/proposed_sniper_executor_iso06.py
byte-for-byte (pinned by test_proposal_applies_cleanly_to_the_current_source). When the gate
says GO these hunks become patch_iso06_idempotency.py with the ISO-01/02/09 script body."""
HUNKS = [('import logging, os, sys, traceback\n', 'import json, logging, os, sys, threading, time, traceback\n'),
 ('V7_MAGIC = int(os.getenv("V7_MAGIC_NUMBER", "70007"))\n\n',
  'V7_MAGIC = int(os.getenv("V7_MAGIC_NUMBER", "70007"))\n'
  '\n'
  '\n'
  '# [ISO-06 PROPOSAL 2026-09-05, ADR-004] (account_id, signal_id) memory: the same\n'
  '# signal on the same account is ONE fill. A retried or duplicated POST answers 409\n'
  '# and places nothing. The key is marked immediately BEFORE order_send; a definitive\n'
  '# broker rejection un-marks it (a retry is legitimate); an ambiguous outcome (None\n'
  '# result, exception mid-flight) stays marked - the reconciler settles it, a retry\n'
  '# never does (fail closed). Store unreadable = UNKNOWN = refuse. TTL 6h like v18.\n'
  '_SEEN_FILE = (os.getenv("V7_SEEN_FILE") or "").strip() or os.path.join(\n'
  '    os.path.dirname(os.path.abspath(__file__)), "v7_seen_signals.json")\n'
  '_SEEN_TTL_S = 6 * 3600\n'
  '_seen_lock = threading.Lock()\n'
  '\n'
  '\n'
  'def _seen_load():\n'
  '    """dict of key -> record, expired entries dropped; None = store UNKNOWN."""\n'
  '    try:\n'
  '        with open(_SEEN_FILE, encoding="utf-8") as f:\n'
  '            data = json.load(f)\n'
  '        now = time.time()\n'
  '        return {k: v for k, v in data.items() if now - float(v.get("ts", 0)) < _SEEN_TTL_S}\n'
  '    except FileNotFoundError:\n'
  '        return {}\n'
  '    except Exception as e:\n'
  '        log.error(f"[SEEN] store {_SEEN_FILE} unreadable ({e}) - UNKNOWN, refusing new orders")\n'
  '        return None\n'
  '\n'
  '\n'
  'def _seen_save(data):\n'
  '    tmp = _SEEN_FILE + ".tmp"\n'
  '    with open(tmp, "w", encoding="utf-8") as f:\n'
  '        json.dump(data, f)\n'
  '    os.replace(tmp, _SEEN_FILE)\n'
  '\n'
  '\n'
  'def _seen_check_and_mark(account, signal_id):\n'
  '    """Returns (fresh, prior). fresh=False, prior=None means the store is UNKNOWN."""\n'
  '    key = f"{account}:{signal_id}"\n'
  '    with _seen_lock:\n'
  '        data = _seen_load()\n'
  '        if data is None:\n'
  '            return False, None\n'
  '        if key in data:\n'
  '            return False, data[key]\n'
  '        data[key] = {"ts": time.time(), "state": "in_flight", "ticket": None}\n'
  '        _seen_save(data)\n'
  '        return True, None\n'
  '\n'
  '\n'
  'def _seen_set(account, signal_id, state, ticket=None):\n'
  '    key = f"{account}:{signal_id}"\n'
  '    with _seen_lock:\n'
  '        data = _seen_load() or {}\n'
  '        if state == "rejected":\n'
  '            data.pop(key, None)        # the broker said no: a retry is legitimate\n'
  '        else:\n'
  '            data[key] = {"ts": time.time(), "state": state, "ticket": ticket}\n'
  '        try:\n'
  '            _seen_save(data)\n'
  '        except Exception as e:\n'
  '            log.error(f"[SEEN] store write failed after {state}: {e}")\n'
  '\n'),
 ('        }\n'
  '        log.info(f"[EXEC] {signal_id} order_send: {direction} {symbol} vol={volume} px={price} sl={sl} '
  'tp={tp} magic={V7_MAGIC} account={_acct}")\n',
  '        }\n'
  '        # [ISO-06] one fill per (account, signal_id). Checked after every validation so a\n'
  '        # rejected request never burns the id; marked BEFORE order_send so a duplicate that\n'
  '        # arrives mid-flight is refused too. UNKNOWN store = refuse.\n'
  '        if not signal_id or signal_id == "unknown":\n'
  '            log.error("[EXEC] no signal_id in request - refusing (ISO-06)")\n'
  '            return jsonify({"status":"error","msg":"no_signal_id"}), 400\n'
  '        _fresh, _prior = _seen_check_and_mark(_acct, signal_id)\n'
  '        if not _fresh:\n'
  '            if _prior is None:\n'
  '                log.critical(f"[EXEC] {signal_id} seen-store UNKNOWN - refusing")\n'
  '                return jsonify({"status":"error","msg":"seen_store_unknown"}), 503\n'
  '            log.critical(f"[EXEC] {signal_id} DUPLICATE on {_acct}: first seen {_prior} - refusing")\n'
  '            return '
  'jsonify({"status":"error","msg":"duplicate_signal","signal_id":signal_id,"first":_prior}), 409\n'
  '\n'
  '        log.info(f"[EXEC] {signal_id} order_send: {direction} {symbol} vol={volume} px={price} sl={sl} '
  'tp={tp} magic={V7_MAGIC} account={_acct}")\n'),
 ('            log.error(f"[EXEC] {signal_id} order_send returned None, mt5.last_error={err}")\n'
  '            return jsonify({"status":"error","msg":"order_send returned None",\n',
  '            log.error(f"[EXEC] {signal_id} order_send returned None, mt5.last_error={err}")\n'
  '            _seen_set(_acct, signal_id, "ambiguous")   # [ISO-06] may have filled: retry refused, '
  'reconciler settles it\n'
  '            return jsonify({"status":"error","msg":"order_send returned None",\n'),
 ('            _fill = float(result.price)\n'
  '            _slip = round((_fill - price) if direction == "BUY" else (price - _fill), 6)\n',
  '            _fill = float(result.price)\n'
  '            _seen_set(_acct, signal_id, "filled", result.order)   # [ISO-06]\n'
  '            _slip = round((_fill - price) if direction == "BUY" else (price - _fill), 6)\n'),
 ('                            "retry_count":0,"requotes":0})\n'
  '        return jsonify({"status":"error","retcode":result.retcode,\n',
  '                            "retry_count":0,"requotes":0})\n'
  '        _seen_set(_acct, signal_id, "rejected")   # [ISO-06] broker said no: a retry is legitimate\n'
  '        return jsonify({"status":"error","retcode":result.retcode,\n')]


def apply(text: str) -> str:
    for old, new in HUNKS:
        assert text.count(old) == 1, old[:80]
        text = text.replace(old, new, 1)
    return text
