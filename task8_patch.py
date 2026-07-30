#!/usr/bin/env python3
"""
TASK 8 PATCH — Multi-asset concurrent trades + journal field additions.

What this script does (all atomic — aborts on any failure, no partial writes):
  1. Backs up bot.py and learning/trade_memory.py
  2. Refactors state["open_trade"] (single) → state["open_trades"] (dict by asset class)
  3. Adds 4 concurrent slots: metals / crypto / forex / other
  4. Migrates existing state.json on first load (backward-compatible)
  5. Updates monitor loop, orphan recovery, signal gate, close handler, health
  6. Adds these fields to TradeRecord (Stage 8B journal additions):
       asset_class, breakout_prob, breakout_strength, breakout_dir,
       hold_time_seconds, spread_at_entry, dxy_value, usdjpy_direction,
       signal_age_bars, regime, mae, mfe
  7. Compute hold_time_seconds at close (in monitor & orphan recovery)
  8. Validates Python syntax of both files before writing
  9. Reports patch count + rollback command

Run from /home/shyam/brother_sniper_v7/ directory.
"""
import shutil, sys, os, ast
from datetime import datetime

ROOT = "/home/shyam/brother_sniper_v7"
if not os.path.isdir(ROOT):
    print(f"❌ Directory not found: {ROOT}"); sys.exit(1)
os.chdir(ROOT)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
print(f"TASK 8 PATCH — timestamp {ts}\n{'='*60}")

# ── Step 1: Backup ─────────────────────────────────────────────────────────
print("[1/5] Backing up...")
for f in ["bot.py", "learning/trade_memory.py"]:
    if not os.path.exists(f):
        print(f"  ✗ Missing: {f}"); sys.exit(1)
    shutil.copy(f, f"{f}.bak_task8_{ts}")
    print(f"  ✓ {f}.bak_task8_{ts}")

# ── Step 2: Read files ─────────────────────────────────────────────────────
with open("bot.py") as f: bot = f.read()
with open("learning/trade_memory.py") as f: tm = f.read()

n_patches = 0
def patch(content, old, new, label):
    """Exact-match replace exactly once. Aborts if pattern not found or duplicated."""
    global n_patches
    cnt = content.count(old)
    if cnt == 0:
        print(f"  ✗ FAIL: {label}\n    Pattern not found. ABORTING — no files modified."); sys.exit(1)
    if cnt > 1:
        print(f"  ✗ FAIL: {label}\n    Pattern found {cnt} times (need 1). ABORTING."); sys.exit(1)
    n_patches += 1
    print(f"  ✓ [{n_patches}] {label}")
    return content.replace(old, new)

# ── Step 3: Patch trade_memory.py ──────────────────────────────────────────
print("\n[2/5] Patching learning/trade_memory.py...")

tm = patch(tm,
'''    timestamp_close:Optional[str]=None; close_price:Optional[float]=None
    gross_profit:Optional[float]=None; swap:Optional[float]=None; commission:Optional[float]=None
    net_profit:Optional[float]=None; won:Optional[bool]=None; outcome_ratio:Optional[float]=None
    retail_sl_would_have_died:Optional[bool]=None; version:str="v7"''',
'''    timestamp_close:Optional[str]=None; close_price:Optional[float]=None
    gross_profit:Optional[float]=None; swap:Optional[float]=None; commission:Optional[float]=None
    net_profit:Optional[float]=None; won:Optional[bool]=None; outcome_ratio:Optional[float]=None
    retail_sl_would_have_died:Optional[bool]=None
    # ── v8 / TASK 8 additions ─────────────────────────────────────────────
    asset_class:Optional[str]=None              # metals|crypto|forex|other
    breakout_prob:Optional[int]=None            # 0-100 from v9.7 Pine
    breakout_strength:Optional[str]=None        # Strong|Building|Weak|Fake
    breakout_dir:Optional[str]=None             # UP|DOWN|NONE
    hold_time_seconds:Optional[float]=None      # filled at close
    # Reserved fields (null until populated by future stages):
    spread_at_entry:Optional[float]=None
    dxy_value:Optional[float]=None
    usdjpy_direction:Optional[str]=None
    signal_age_bars:Optional[int]=None
    regime:Optional[str]=None
    mae:Optional[float]=None                    # max adverse excursion (needs poll loop)
    mfe:Optional[float]=None                    # max favorable excursion (needs poll loop)
    version:str="v8"''',
"TradeRecord: 12 new fields added (asset_class, breakout_*, hold_time, reserved nulls)")

tm = patch(tm,
'''def close_trade(signal_id,close_price,gross_profit,swap,commission):
    net=gross_profit+swap+commission
    _append_raw({"_type":"close","signal_id":signal_id,
                 "timestamp_close":datetime.now(timezone.utc).isoformat(),
                 "close_price":close_price,"gross_profit":gross_profit,
                 "swap":swap,"commission":commission,
                 "net_profit":net,"won":net>0,"version":"v7"})
    log.info("MEMORY close: %s net=%.2f", signal_id, net)''',
'''def close_trade(signal_id,close_price,gross_profit,swap,commission,hold_time_seconds=None):
    net=gross_profit+swap+commission
    rec={"_type":"close","signal_id":signal_id,
         "timestamp_close":datetime.now(timezone.utc).isoformat(),
         "close_price":close_price,"gross_profit":gross_profit,
         "swap":swap,"commission":commission,
         "net_profit":net,"won":net>0,"version":"v8"}
    if hold_time_seconds is not None:
        rec["hold_time_seconds"]=round(hold_time_seconds,1)
    _append_raw(rec)
    log.info("MEMORY close: %s net=%.2f hold=%ss", signal_id, net, rec.get("hold_time_seconds","?"))''',
"close_trade: now accepts hold_time_seconds")

# ── Step 4: Patch bot.py ───────────────────────────────────────────────────
print("\n[3/5] Patching bot.py...")

# 4a: Inject asset_class helpers immediately before load_state
HELPERS = '''
# ━━ TASK 8: Multi-asset slot management ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ASSET_SLOTS = ("metals", "crypto", "forex", "other")
def asset_class(symbol):
    """Categorize a symbol into one of 4 concurrent trade slots."""
    if not symbol: return "other"
    s = str(symbol).upper().replace("USDT","").replace("USD","")
    if s in ("SILVER","GOLD","XAU","XAG","XAUUSD","XAGUSD","XAGEUR","XAUEUR"): return "metals"
    if s in ("BTC","ETH","XRP","ETHEREUM","BITCOIN","SOL","DOGE","ADA","BCH","LTC"): return "crypto"
    if s in ("EUR","JPY","GBP","CHF","AUD","NZD","CAD","EURJPY","GBPJPY","CHFJPY") or (len(s)==6 and s[:3] in ("EUR","GBP","AUD","NZD","USD","CHF","CAD","JPY")): return "forex"
    return "other"

def _empty_slots(): return {k: None for k in ASSET_SLOTS}

def get_open_trade(ac):
    return state.get("open_trades", {}).get(ac)

def set_open_trade(ac, trade):
    if "open_trades" not in state: state["open_trades"] = _empty_slots()
    state["open_trades"][ac] = trade

def clear_open_trade(ac):
    if "open_trades" in state: state["open_trades"][ac] = None

def all_open_trades():
    """Yield (asset_class, trade_dict) for every non-None slot."""
    for k, v in (state.get("open_trades") or {}).items():
        if v: yield k, v

def any_open_trade():
    return any(t for t in (state.get("open_trades") or {}).values() if t)
# ━━ End TASK 8 helpers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_state():'''

bot = patch(bot, "def load_state():", HELPERS,
            "Asset class helpers (asset_class/get/set/clear/all_open_trades/any_open_trade)")

# 4b: load_state with backward-compat migration
bot = patch(bot,
'''    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f: return json.load(f)
        except Exception as e: log.error(f"State corrupt: {e}")
    return {"consecutive_losses":0,"open_trade":None,"total_trades":0,
            "total_wins":0,"total_losses":0,"seen_signal_ids":{},"paused":False,"equity":None}''',
'''    s = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f: s = json.load(f)
        except Exception as e: log.error(f"State corrupt: {e}")
    if s is None:
        s = {"consecutive_losses":0,"open_trades":_empty_slots(),"total_trades":0,
             "total_wins":0,"total_losses":0,"seen_signal_ids":{},"paused":False,"equity":None}
    # ── TASK 8 migration: old open_trade (single) → open_trades (dict) ──
    if "open_trades" not in s:
        s["open_trades"] = _empty_slots()
        if s.get("open_trade"):
            old = s["open_trade"]
            ac = asset_class(old.get("symbol",""))
            old["asset_class"] = ac
            s["open_trades"][ac] = old
            log.info(f"[MIGRATE] open_trade -> open_trades[{ac}] ({old.get('symbol')})")
    s.pop("open_trade", None)
    return s''',
"load_state: backward-compat migration for state.json")

# 4c: Monitor loop — multi-trade iteration
bot = patch(bot,
'''def _monitor():
    mon_lock = threading.Lock()
    while not _shutdown.is_set():
        _shutdown.wait(60)
        if _shutdown.is_set() or not state.get("open_trade"): continue
        try:
            with mon_lock:
                tracked=state.get("open_trade")
                if not tracked: continue
                oid=tracked.get("order_id"); comment=tracked.get("comment","")
                # Check MT5 positions
                import requests as _rq
                _base=os.getenv("EXECUTOR_URL","").replace("/execute","")
                try:
                    _r=_rq.get(_base+"/positions",timeout=5)
                    _tickets={p.get("ticket") for p in _r.json().get("positions",[])}
                    if oid in _tickets: continue
                except Exception as _e:
                    log.warning(f"[MON] MT5 positions check failed: {_e}"); continue
                # Trade closed — fetch real close data from /history
                cp=tracked.get("entry",0); profit=0.0; swap=0.0; comm=0.0; close_reason="unknown"
                try:
                    _hr=_rq.get(_base+"/history?hours=24",timeout=10).json()
                    deal=next((d for d in _hr.get("deals",[]) if d.get("position_id")==oid),None)
                    if deal:
                        cp=float(deal.get("close_price") or tracked.get("entry",0))
                        profit=float(deal.get("profit",0)); swap=float(deal.get("swap",0)); comm=float(deal.get("commission",0))
                        close_reason=deal.get("close_comment","").lower()
                        log.info(f"[MON] Trade {oid} closed: close={cp} profit={profit} reason={close_reason}")
                    else:
                        log.warning(f"[MON] Trade {oid} not in history yet — using entry as fallback")
                except Exception as _e:
                    log.warning(f"[MON] history fetch failed: {_e}")
                net=profit+swap+comm
                won=net>0
                state["open_trade"]=None; state["total_trades"]=state.get("total_trades",0)+1
                if won: state["consecutive_losses"]=0; state["total_wins"]=state.get("total_wins",0)+1; emoji,tag="✅",f"WIN +${net:.2f}"
                else: state["consecutive_losses"]=state.get("consecutive_losses",0)+1; state["total_losses"]=state.get("total_losses",0)+1; emoji,tag="❌",f"LOSS ${net:.2f}"

                mem_close(tracked.get("signal_id","?"), float(cp), profit, swap, comm)
                equity_guard.record_trade(net, tracked["symbol"])
                state["equity"]=equity_guard.to_dict(); save_state()
                bal=xtb.get_balance(); equity_guard.update_balance(bal)''',
'''def _monitor():
    mon_lock = threading.Lock()
    while not _shutdown.is_set():
        _shutdown.wait(60)
        if _shutdown.is_set(): continue
        if not any_open_trade(): continue
        try:
            with mon_lock:
                # Fetch MT5 positions ONCE for all slots
                import requests as _rq
                from datetime import datetime as _dt, timezone as _tz
                _base=os.getenv("EXECUTOR_URL","").replace("/execute","")
                try:
                    _r=_rq.get(_base+"/positions",timeout=5)
                    _tickets={p.get("ticket") for p in _r.json().get("positions",[])}
                except Exception as _e:
                    log.warning(f"[MON] MT5 positions check failed: {_e}"); continue
                # Snapshot to avoid mutation during iteration
                open_snapshot = list(all_open_trades())
                _hr_cached = None  # /history fetched lazily, only if at least one slot closed
                for ac, tracked in open_snapshot:
                    oid=tracked.get("order_id"); comment=tracked.get("comment","")
                    if oid in _tickets: continue  # still open in MT5
                    # Closed — fetch /history (cached across slots)
                    if _hr_cached is None:
                        try:
                            _hr_cached=_rq.get(_base+"/history?hours=24",timeout=10).json()
                        except Exception as _e:
                            log.warning(f"[MON] history fetch failed: {_e}"); _hr_cached={"deals":[]}
                    cp=tracked.get("entry",0); profit=0.0; swap=0.0; comm=0.0; close_reason="unknown"
                    deal=next((d for d in _hr_cached.get("deals",[]) if d.get("position_id")==oid),None)
                    if deal:
                        cp=float(deal.get("close_price") or tracked.get("entry",0))
                        profit=float(deal.get("profit",0)); swap=float(deal.get("swap",0)); comm=float(deal.get("commission",0))
                        close_reason=deal.get("close_comment","").lower()
                        log.info(f"[MON] {ac}/{tracked.get('symbol','?')} {oid} closed: close={cp} profit={profit} reason={close_reason}")
                    else:
                        log.warning(f"[MON] Trade {oid} ({ac}/{tracked.get('symbol','?')}) not in history yet — using entry as fallback")
                    # Compute hold time
                    _hold=None
                    try:
                        _opened=tracked.get("opened_at")
                        if _opened:
                            _hold=(_dt.now(_tz.utc) - _dt.fromisoformat(_opened)).total_seconds()
                    except Exception: pass
                    net=profit+swap+comm
                    won=net>0
                    clear_open_trade(ac)
                    state["total_trades"]=state.get("total_trades",0)+1
                    if won: state["consecutive_losses"]=0; state["total_wins"]=state.get("total_wins",0)+1; emoji,tag="✅",f"WIN +${net:.2f}"
                    else: state["consecutive_losses"]=state.get("consecutive_losses",0)+1; state["total_losses"]=state.get("total_losses",0)+1; emoji,tag="❌",f"LOSS ${net:.2f}"
                    mem_close(tracked.get("signal_id","?"), float(cp), profit, swap, comm, hold_time_seconds=_hold)
                    equity_guard.record_trade(net, tracked["symbol"])
                    state["equity"]=equity_guard.to_dict(); save_state()
                    bal=xtb.get_balance(); equity_guard.update_balance(bal)''',
"Monitor loop: iterates all open slots, single /positions fetch, computes hold_time")

# 4d: Signal gate — per-asset-class
bot = patch(bot,
'''    if state.get("paused") or state.get("consecutive_losses",0)>=3:
        return {"status":"paused","msg":"paused — POST /reset"}
    if state.get("open_trade"): return {"status":"skipped","msg":"position open"}''',
'''    if state.get("paused") or state.get("consecutive_losses",0)>=3:
        return {"status":"paused","msg":"paused — POST /reset"}
    # TASK 8: per-asset-class slot check (allow concurrent trades across classes)
    _ac = asset_class(symbol)
    if get_open_trade(_ac):
        return {"status":"skipped","msg":f"{_ac} slot already open"}''',
"Signal gate: per-asset-class skip (was global open_trade)")

# 4e: Trade open — write to right slot + add asset_class field
bot = patch(bot,
'''        if resp.get("status"):
            order_id=resp.get("returnData",{}).get("order")
            state["open_trade"]={
                "order_id":order_id,"symbol":symbol,"direction":direction,
                "volume":lot,"entry":entry,"sl":inst_sl,"raw_sl":raw_sl,"tp":tp,
                "signal_id":sid,"comment":comment,"cluster_key":cluster.cluster_key,
                "opened_at":now_utc.isoformat(),
            }
            state["equity"]=equity_guard.to_dict(); save_state()''',
'''        if resp.get("status"):
            order_id=resp.get("returnData",{}).get("order")
            _ac = asset_class(symbol)
            set_open_trade(_ac, {
                "order_id":order_id,"symbol":symbol,"direction":direction,
                "volume":lot,"entry":entry,"sl":inst_sl,"raw_sl":raw_sl,"tp":tp,
                "signal_id":sid,"comment":comment,"cluster_key":cluster.cluster_key,
                "opened_at":now_utc.isoformat(),
                "asset_class":_ac,
            })
            state["equity"]=equity_guard.to_dict(); save_state()''',
"Trade open: writes to set_open_trade(ac, ...) with asset_class tag")

# 4f: Health endpoint — show per-class status
bot = patch(bot,
'''        "paused":state.get("paused"),"open_trade":bool(state.get("open_trade")),''',
'''        "paused":state.get("paused"),
        "open_trade":any_open_trade(),
        "open_trades":{k:bool(v) for k,v in (state.get("open_trades") or {}).items()},''',
"Health endpoint: per-asset-class open_trades dict")

# 4g: Close handler — accept asset_class param (defaults to single slot if only one open)
bot = patch(bot,
'''@app.route("/close",methods=["POST"])
def close_route():
    if (request.get_json(force=True) or {}).get("secret")!=WEBHOOK_SECRET: abort(403)
    t=state.get("open_trade")
    if not t: return jsonify({"status":"error","msg":"no tracked trade"})
    try:
        resp=xtb.close_trade(t["order_id"],t["symbol"],t["volume"],t["direction"])
        state["open_trade"]=None; save_state()
        send_telegram(f"🔒 <b>Closed manually</b>\\n{t['symbol']}")
        return jsonify({"status":"ok","xtb":resp})
    except Exception as e: return jsonify({"status":"error","msg":str(e)})''',
'''@app.route("/close",methods=["POST"])
def close_route():
    body=request.get_json(force=True) or {}
    if body.get("secret")!=WEBHOOK_SECRET: abort(403)
    target=body.get("asset_class") or body.get("slot")  # metals|crypto|forex|other|all
    open_now=list(all_open_trades())
    if not open_now: return jsonify({"status":"error","msg":"no tracked trades"})
    if not target and len(open_now)==1: target=open_now[0][0]  # default to the one open
    elif not target: return jsonify({"status":"error","msg":f"specify asset_class","open":[ac for ac,_ in open_now]})
    closed=[]; errors=[]
    for ac, t in open_now:
        if target!="all" and ac!=target: continue
        try:
            resp=xtb.close_trade(t["order_id"],t["symbol"],t["volume"],t["direction"])
            clear_open_trade(ac); save_state()
            send_telegram(f"🔒 <b>Closed manually ({ac})</b>\\n{t['symbol']}")
            closed.append({"asset_class":ac,"symbol":t["symbol"],"xtb":resp})
        except Exception as e:
            errors.append({"asset_class":ac,"err":str(e)})
    return jsonify({"status":("ok" if closed and not errors else ("partial" if closed else "error")),
                    "closed":closed,"errors":errors})''',
"Close handler: per-asset-class close (or 'all')")

# 4h: Orphan recovery — iterate all slots
bot = patch(bot,
'''        _orphan = state.get("open_trade")
        if _orphan:
            import requests as _orq
            _base = os.getenv("EXECUTOR_URL","").replace("/execute","")
            _oid = _orphan.get("order_id")
            _pos = _orq.get(_base+"/positions", timeout=5).json()
            _tix = {p.get("ticket") for p in _pos.get("positions",[])}
            if _oid not in _tix:
                log.warning(f"[STARTUP] Orphan trade {_oid} in state but not in MT5 — recovering")
                _hist = _orq.get(_base+"/history?hours=168", timeout=10).json()
                _deal = next((d for d in _hist.get("deals",[]) if d.get("position_id")==_oid), None)
                if _deal:
                    _net = float(_deal.get("profit",0)) + float(_deal.get("swap",0)) + float(_deal.get("commission",0))
                    log.info(f"[STARTUP] Recovered orphan {_oid}: net={_net:.2f}")
                    try:
                        from learning.trade_memory import close_trade as _mclose
                        _mclose(_orphan.get("signal_id","?"), float(_deal.get("close_price",0)), float(_deal.get("profit",0)), float(_deal.get("swap",0)), float(_deal.get("commission",0)))
                    except Exception as _me:
                        log.warning(f"[STARTUP] mem_close failed: {_me}")
                    if _net > 0:
                        state["total_wins"] = state.get("total_wins",0)+1
                        state["consecutive_losses"] = 0
                    else:
                        state["total_losses"] = state.get("total_losses",0)+1
                        state["consecutive_losses"] = state.get("consecutive_losses",0)+1
                    state["total_trades"] = state.get("total_trades",0)+1
                else:
                    log.warning(f"[STARTUP] Orphan {_oid} not in 7-day history — clearing without record")
                state["open_trade"] = None
                save_state()''',
'''        _orphans = list(all_open_trades())
        if _orphans:
            import requests as _orq
            from datetime import datetime as _odt, timezone as _otz
            _base = os.getenv("EXECUTOR_URL","").replace("/execute","")
            _pos = _orq.get(_base+"/positions", timeout=5).json()
            _tix = {p.get("ticket") for p in _pos.get("positions",[])}
            _hist = None
            for _ac, _orphan in _orphans:
                _oid = _orphan.get("order_id")
                if _oid in _tix: continue  # still open in MT5
                log.warning(f"[STARTUP] Orphan {_ac} trade {_oid} not in MT5 — recovering")
                if _hist is None:
                    _hist = _orq.get(_base+"/history?hours=168", timeout=10).json()
                _deal = next((d for d in _hist.get("deals",[]) if d.get("position_id")==_oid), None)
                if _deal:
                    _net = float(_deal.get("profit",0)) + float(_deal.get("swap",0)) + float(_deal.get("commission",0))
                    log.info(f"[STARTUP] Recovered orphan {_ac} {_oid}: net={_net:.2f}")
                    try:
                        from learning.trade_memory import close_trade as _mclose
                        _hold=None
                        try:
                            _opened=_orphan.get("opened_at")
                            if _opened:
                                _hold=(_odt.now(_otz.utc) - _odt.fromisoformat(_opened)).total_seconds()
                        except Exception: pass
                        _mclose(_orphan.get("signal_id","?"), float(_deal.get("close_price",0)),
                                float(_deal.get("profit",0)), float(_deal.get("swap",0)),
                                float(_deal.get("commission",0)), hold_time_seconds=_hold)
                    except Exception as _me:
                        log.warning(f"[STARTUP] mem_close failed: {_me}")
                    if _net > 0:
                        state["total_wins"] = state.get("total_wins",0)+1
                        state["consecutive_losses"] = 0
                    else:
                        state["total_losses"] = state.get("total_losses",0)+1
                        state["consecutive_losses"] = state.get("consecutive_losses",0)+1
                    state["total_trades"] = state.get("total_trades",0)+1
                else:
                    log.warning(f"[STARTUP] Orphan {_ac} {_oid} not in 7-day history — clearing without record")
                clear_open_trade(_ac)
                save_state()''',
"Orphan recovery: iterates all asset slots, computes hold_time")

# ── Step 5: Validate Python syntax ─────────────────────────────────────────
print("\n[4/5] Validating Python syntax...")
try:
    ast.parse(bot)
    print("  ✓ bot.py syntax OK")
except SyntaxError as e:
    print(f"  ✗ bot.py SYNTAX ERROR at line {e.lineno}: {e.msg}\n    ABORTING — no files modified."); sys.exit(1)
try:
    ast.parse(tm)
    print("  ✓ trade_memory.py syntax OK")
except SyntaxError as e:
    print(f"  ✗ trade_memory.py SYNTAX ERROR at line {e.lineno}: {e.msg}\n    ABORTING — no files modified."); sys.exit(1)

# ── Step 6: Write new files ────────────────────────────────────────────────
print("\n[5/5] Writing patched files...")
with open("bot.py", "w") as f: f.write(bot)
with open("learning/trade_memory.py", "w") as f: f.write(tm)
print("  ✓ bot.py written")
print("  ✓ learning/trade_memory.py written")

print(f"\n{'='*60}")
print(f"✅ TASK 8 PATCH COMPLETE — {n_patches} patches applied")
print(f"{'='*60}")
print(f"Backup suffix: bak_task8_{ts}")
print(f"\nNext steps (run in order):")
print(f"  1. sudo systemctl restart sniper-bot")
print(f"  2. sleep 3 && sudo systemctl status sniper-bot --no-pager | head -15")
print(f"  3. curl -s http://localhost:5000/health | python3 -m json.tool")
print(f"  4. tail -30 logs/sniper.log  (watch for [MIGRATE] line)")
print(f"\nROLLBACK if anything goes wrong:")
print(f"  cp bot.py.bak_task8_{ts} bot.py && cp learning/trade_memory.py.bak_task8_{ts} learning/trade_memory.py && sudo systemctl restart sniper-bot")
