"""
Brother Sniper Executor v3 - Windows VPS
Replaces v2. Backwards-compatible with existing bot.py JSON contract.

Changes from v2:
  1. SYMBOL_MAP expanded — ETH (Ethereum, ETHUSD, ETH) + EUR/JPY pairs added
  2. /execute wrapped in try/except — never returns empty body, always JSON
  3. Reads BOTH "lot" and "volume" from payload (back-compat with bot's send)
  4. Auto-reconnect MT5 if order_send returns None or symbol_info_tick fails
  5. File logging to sniper_executor.log (rotating, 5MB max, keep 3 backups)
  6. /execute logs full request + response for every trade attempt
  7. Detects when MT5 lost broker connection and reports it cleanly
"""
from flask import Flask, request, jsonify
import MetaTrader5 as mt5
import json, logging, os, sys, threading, time, traceback
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

# v7 owns its OWN terminal — prevents grabbing v18's terminal/account
V7_MT5_PATH = r"C:\Program Files\MetaTrader 5 IC Markets EU\terminal64.exe"

# ── LOGGING ─────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sniper_executor.log")
log = logging.getLogger("executor")
log.setLevel(logging.INFO)
# Rotating file handler — 5MB per file, keep 3 backups (~15MB total)
fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
log.addHandler(fh)
# Also keep stdout for console visibility
sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
log.addHandler(sh)

app = Flask(__name__)

SECRET = os.getenv("WEBHOOK_SECRET", "")

# [ISO-03 2026-09-05] every v7 order carries v7's magic so the reconciler, the
# platform and /close /modify can tell v7's positions from anyone else's.
# A tag, not a risk number; documented in .env.example.
V7_MAGIC = int(os.getenv("V7_MAGIC_NUMBER", "70007"))


# [ISO-06 PROPOSAL 2026-09-05, ADR-004] (account_id, signal_id) memory: the same
# signal on the same account is ONE fill. A retried or duplicated POST answers 409
# and places nothing. The key is marked immediately BEFORE order_send; a definitive
# broker rejection un-marks it (a retry is legitimate); an ambiguous outcome (None
# result, exception mid-flight) stays marked - the reconciler settles it, a retry
# never does (fail closed). Store unreadable = UNKNOWN = refuse. TTL 6h like v18.
_SEEN_FILE = (os.getenv("V7_SEEN_FILE") or "").strip() or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "v7_seen_signals.json")
_SEEN_TTL_S = 6 * 3600
_seen_lock = threading.Lock()


def _seen_load():
    """dict of key -> record, expired entries dropped; None = store UNKNOWN."""
    try:
        with open(_SEEN_FILE, encoding="utf-8") as f:
            data = json.load(f)
        now = time.time()
        return {k: v for k, v in data.items() if now - float(v.get("ts", 0)) < _SEEN_TTL_S}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.error(f"[SEEN] store {_SEEN_FILE} unreadable ({e}) - UNKNOWN, refusing new orders")
        return None


def _seen_save(data):
    tmp = _SEEN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, _SEEN_FILE)


def _seen_check_and_mark(account, signal_id):
    """Returns (fresh, prior). fresh=False, prior=None means the store is UNKNOWN."""
    key = f"{account}:{signal_id}"
    with _seen_lock:
        data = _seen_load()
        if data is None:
            return False, None
        if key in data:
            return False, data[key]
        data[key] = {"ts": time.time(), "state": "in_flight", "ticket": None}
        _seen_save(data)
        return True, None


def _seen_set(account, signal_id, state, ticket=None):
    key = f"{account}:{signal_id}"
    with _seen_lock:
        data = _seen_load() or {}
        if state == "rejected":
            data.pop(key, None)        # the broker said no: a retry is legitimate
        else:
            data[key] = {"ts": time.time(), "state": state, "ticket": ticket}
        try:
            _seen_save(data)
        except Exception as e:
            log.error(f"[SEEN] store write failed after {state}: {e}")


# [ISO-16 2026-09-05, ADR-008] GLOBAL emergency stop: ONE file both executors on
# this box read before every new order. Present = STOP, absent = CLEAR, unreadable
# = UNKNOWN (treated as STOP). Identical logic lives in the v18 executor
# (executor_ic_markets/src/utils/global_stop.py); keep the two in step.
def _global_stop_path():
    p = (os.getenv("GLOBAL_STOP_FILE") or "").strip()
    if p:
        return p
    return r"C:\brotherbot\GLOBAL_STOP" if os.name == "nt" else "/var/lib/brotherbot/GLOBAL_STOP"


def _global_stop_state():
    try:
        return "STOP" if os.path.exists(_global_stop_path()) else "CLEAR"
    except Exception:
        return "UNKNOWN"


def _global_stop_engage(reason, who="sniper_executor_v7"):
    p = _global_stop_path()
    try:
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{datetime.utcnow().isoformat()}Z {who}: {reason}\n")
    except Exception as e:
        log.error(f"[GLOBAL-STOP] could not write {p}: {e}")
    return p


ADMIN_HALT_TOKEN = os.getenv("ADMIN_HALT_TOKEN", "").strip()


def _is_ours(pos) -> bool:
    """[ISO-05] a position is v7's if it carries V7_MAGIC or the legacy 'BS_' comment
    (positions opened before ISO-03 have magic 0 and a BS_<signal> comment)."""
    try:
        if int(getattr(pos, "magic", 0) or 0) == V7_MAGIC:
            return True
    except (TypeError, ValueError):
        pass
    return str(getattr(pos, "comment", "") or "").startswith("BS_")

# Symbol mapping: bot's name → IC Markets MT5 symbol
SYMBOL_MAP = {
    # Metals
    "GOLD":"XAUUSD", "XAUUSD":"XAUUSD", "XAU":"XAUUSD",
    "SILVER":"XAGUSD", "XAGUSD":"XAGUSD", "XAG":"XAGUSD",
    # Crypto — ETH variants now mapped (was missing in v2)
    "BITCOIN":"BTCUSD", "BTCUSD":"BTCUSD", "BTC":"BTCUSD", "BTCUSDT":"BTCUSD",
    "ETHEREUM":"ETHUSD", "ETHUSD":"ETHUSD", "ETH":"ETHUSD", "ETHUSDT":"ETHUSD",
    "XRP":"XRPUSD", "XRPUSD":"XRPUSD", "XRPUSDT":"XRPUSD",
    # Forex
    "EURUSD":"EURUSD", "USDJPY":"USDJPY", "GBPUSD":"GBPUSD",
    "AUDUSD":"AUDUSD", "USDCAD":"USDCAD", "USDCHF":"USDCHF",
    "NZDUSD":"NZDUSD", "EURJPY":"EURJPY", "GBPJPY":"GBPJPY",
    # Indices (just in case)
    "DXY":"USDX",
}

# ── MT5 CONNECTION MANAGEMENT ───────────────────────────────────────────────
# [ISO-01 2026-09-04] the ONE account this bridge may touch. No value = NOT
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
    log.warning("MT5 not connected — attempting initialize()")
    if not mt5.initialize(path=V7_MT5_PATH, timeout=60000):
        err = mt5.last_error()
        log.error(f"MT5 initialize failed: {err}")
        return False
    acc = mt5.account_info()
    if acc is None:
        log.error("MT5 still not connected after initialize()")
        return False
    log.info(f"MT5 reconnected: account {acc.login} balance {acc.balance}")
    return _identity_ok(acc)

# Initial connection
if not mt5.initialize(path=V7_MT5_PATH, timeout=60000):
    log.error(f"Initial MT5 init failed: {mt5.last_error()}")
else:
    acc = mt5.account_info()
    if acc:
        log.info(f"Executor v3 starting. MT5 account {acc.login} balance ${acc.balance:.2f}")
    else:
        log.warning("MT5 initialize() returned True but account_info() is None")

# ── ROUTES ──────────────────────────────────────────────────────────────────
# [OBS 2026-09-02] identity for the Git<->Production MATCH light.
# This file runs as a loose copy in C:\Users\Administrator, so "untracked"
# is the HONEST reading there until the service is repointed at the clone.
def _deploy_commit():
    try:
        import subprocess as _sp, os as _os
        return _sp.run(["git", "-C", _os.path.dirname(_os.path.abspath(__file__)),
                        "rev-parse", "--short", "HEAD"],
                       capture_output=True, text=True, timeout=5).stdout.strip() or "untracked"
    except Exception:
        return "untracked"


_GIT_COMMIT = _deploy_commit()


@app.route("/health", methods=["GET"])
def health():
    if not ensure_mt5():
        return jsonify({"status":"error","msg":"mt5 disconnected"}), 503
    acc = mt5.account_info()
    if acc:
        return jsonify({"status":"ok","account":acc.login,"balance":acc.balance,"equity":acc.equity,
                        "trade_mode":getattr(acc,"trade_mode",None),          # heartbeat work order item 1
                        "global_stop":_global_stop_state(),                    # [ISO-16]
                        "git_commit":_GIT_COMMIT,"service_version":"sniper-executor-v7"})
    return jsonify({"status":"error","msg":"no account info"}), 503

@app.route("/positions", methods=["GET"])
def positions():
    try:
        if not ensure_mt5():
            return jsonify({"status":"error","msg":"mt5 disconnected"}), 503
        pos = mt5.positions_get()
        if pos is None:
            return jsonify({"status":"error","msg":"positions_get None (mt5 not ready)"}), 503
        if pos:
            return jsonify({"count":len(pos),"positions":[
                {"ticket":p.ticket,"symbol":p.symbol,"profit":p.profit,
                 "volume":p.volume,"type":"BUY" if p.type==0 else "SELL",
                 "price_open":p.price_open,"price_current":p.price_current,"sl":p.sl,"tp":p.tp,"comment":p.comment,
                 "magic":getattr(p,"magic",None),"ours":_is_ours(p)}   # [ISO-03/05] append-only
                for p in pos]})
        return jsonify({"count":0,"positions":[]})
    except Exception as e:
        log.error(f"/positions error: {e}\n{traceback.format_exc()}")
        return jsonify({"status":"error","msg":str(e)}), 500

@app.route("/history", methods=["GET"])
def history():
    """Returns closed deals from last N hours (default 48). Uses UTC for MT5 broker time."""
    try:
        ensure_mt5()
        try:
            hours = int(request.args.get("hours", 48))
        except:
            hours = 48
        now_utc = datetime.utcnow()
        since = now_utc - timedelta(hours=hours)
        until = now_utc + timedelta(hours=24)
        log.info(f"[HISTORY] querying {since} to {until}")
        deals = mt5.history_deals_get(since, until)
        if deals is None:
            log.warning(f"history_deals_get returned None: {mt5.last_error()}")
            deals = []

        by_position = {}
        for d in deals:
            pid = d.position_id
            if pid not in by_position:
                by_position[pid] = {"position_id":pid,"symbol":d.symbol,"deals":[],
                                    "profit":0.0,"swap":0.0,"commission":0.0,
                                    "open_price":None,"close_price":None,"close_time":None,
                                    "comment":d.comment,"volume":0.0}
            by_position[pid]["deals"].append({"ticket":d.ticket,"type":d.type,"price":d.price,"time":d.time,"profit":d.profit})
            by_position[pid]["profit"] += d.profit
            by_position[pid]["swap"] += d.swap
            by_position[pid]["commission"] += d.commission
            if d.entry == 0:
                by_position[pid]["open_price"] = d.price
                by_position[pid]["volume"] = d.volume
            elif d.entry == 1:
                by_position[pid]["close_price"] = d.price
                by_position[pid]["close_time"] = d.time
                by_position[pid]["close_comment"] = d.comment

        closed = [v for v in by_position.values() if v["close_price"] is not None]
        return jsonify({"count":len(closed),"deals":closed})
    except Exception as e:
        log.error(f"/history error: {e}\n{traceback.format_exc()}")
        return jsonify({"status":"error","msg":str(e)}), 500

@app.route("/execute", methods=["POST"])
def execute():
    """Place a market order. Wrapped to never return empty body."""
    try:
        data = request.get_json(silent=True) or {}
        signal_id = data.get("signal_id","unknown")
        log.info(f"[EXEC] request: {data}")

        if not data:
            return jsonify({"status":"error","msg":"no data"}), 400
        if data.get("secret") != SECRET:
            return jsonify({"status":"error","msg":"unauthorized"}), 403

        # [ISO-03] the caller must name the account it means; it must be the one this
        # bridge asserts (ISO-01). Missing or different = no execution (ADR-004).
        _acct = str(data.get("account_id") or "").strip()
        if not _acct:
            log.error(f"[EXEC] {signal_id} no account_id in request - refusing")
            return jsonify({"status":"error","msg":"no_account_id"}), 400
        if _acct != V7_MT5_LOGIN:
            log.critical(f"[EXEC] {signal_id} account_mismatch: request says {_acct}, bridge asserts {V7_MT5_LOGIN} - refusing")
            return jsonify({"status":"error","msg":"account_mismatch"}), 403

        # [ISO-16] the GLOBAL stop refuses every new order on this box (UNKNOWN = STOP)
        _gs = _global_stop_state()
        if _gs != "CLEAR":
            log.critical(f"[EXEC] {signal_id} GLOBAL STOP {_gs} ({_global_stop_path()}) - refusing")
            return jsonify({"status":"error","msg":"global_stop","state":_gs}), 503

        # Symbol resolution
        raw_sym = (data.get("symbol") or "").upper()
        symbol = SYMBOL_MAP.get(raw_sym, raw_sym)
        direction = (data.get("direction") or "").upper()

        # Volume — read both "lot" and "volume" for back-compat
        try:
            volume = float(data.get("lot") or data.get("volume") or 0.01)
            sl = float(data.get("sl") or 0)
            tp = float(data.get("tp") or 0)
        except (ValueError, TypeError) as e:
            log.error(f"[EXEC] {signal_id} invalid sl/tp/lot: {e}")
            return jsonify({"status":"error","msg":f"invalid sl/tp/lot: {e}"}), 400

        # NaN check (NaN != NaN in Python)
        if sl != sl or tp != tp or volume != volume:
            log.error(f"[EXEC] {signal_id} NaN detected: sl={sl} tp={tp} vol={volume}")
            return jsonify({"status":"error","msg":"NaN sl/tp/volume"}), 400

        if direction not in ("BUY","SELL"):
            log.error(f"[EXEC] {signal_id} bad direction: {direction}")
            return jsonify({"status":"error","msg":f"unknown direction: {direction}"}), 400

        # Ensure MT5 alive before doing anything
        if not ensure_mt5():
            log.error(f"[EXEC] {signal_id} MT5 not connected, rejecting")
            return jsonify({"status":"error","msg":"mt5 disconnected, retry"}), 503

        # Select symbol and get tick
        if not mt5.symbol_select(symbol, True):
            log.error(f"[EXEC] {signal_id} symbol_select failed for {symbol}: {mt5.last_error()}")
            return jsonify({"status":"error","msg":f"symbol select failed: {symbol}",
                            "last_error":str(mt5.last_error())}), 400

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            log.error(f"[EXEC] {signal_id} no tick for {symbol}: {mt5.last_error()}")
            return jsonify({"status":"error","msg":f"no tick for {symbol}",
                            "last_error":str(mt5.last_error())}), 400

        if direction == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "magic": V7_MAGIC,   # [ISO-03] v7's positions are no longer anonymous
            "comment": "BS_" + __import__("hashlib").md5(str(signal_id).encode()).hexdigest()[:8],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        # [ISO-06] one fill per (account, signal_id). Checked after every validation so a
        # rejected request never burns the id; marked BEFORE order_send so a duplicate that
        # arrives mid-flight is refused too. UNKNOWN store = refuse.
        if not signal_id or signal_id == "unknown":
            log.error("[EXEC] no signal_id in request - refusing (ISO-06)")
            return jsonify({"status":"error","msg":"no_signal_id"}), 400
        _fresh, _prior = _seen_check_and_mark(_acct, signal_id)
        if not _fresh:
            if _prior is None:
                log.critical(f"[EXEC] {signal_id} seen-store UNKNOWN - refusing")
                return jsonify({"status":"error","msg":"seen_store_unknown"}), 503
            log.critical(f"[EXEC] {signal_id} DUPLICATE on {_acct}: first seen {_prior} - refusing")
            return jsonify({"status":"error","msg":"duplicate_signal","signal_id":signal_id,"first":_prior}), 409

        log.info(f"[EXEC] {signal_id} order_send: {direction} {symbol} vol={volume} px={price} sl={sl} tp={tp} magic={V7_MAGIC} account={_acct}")

        # [TELEMETRY 08-01] time the broker round-trip. Log-only: the request
        # above and order_send below are byte-identical to before.
        _t0 = datetime.utcnow()
        result = mt5.order_send(req)
        _latency_ms = round((datetime.utcnow() - _t0).total_seconds() * 1000.0, 1)

        # Handle MT5 returning None (connection issue mid-flight)
        if result is None:
            err = mt5.last_error()
            log.error(f"[EXEC] {signal_id} order_send returned None, mt5.last_error={err}")
            _seen_set(_acct, signal_id, "ambiguous")   # [ISO-06] may have filled: retry refused, reconciler settles it
            return jsonify({"status":"error","msg":"order_send returned None",
                            "last_error":str(err)}), 502

        log.info(f"[EXEC] {signal_id} retcode={result.retcode} comment={result.comment} order={result.order}")

        if result.retcode == 10009:  # TRADE_RETCODE_DONE
            # [TELEMETRY 08-01] execution facts for the feature store (log-only).
            # slippage: positive = filled WORSE than the requested price.
            _fill = float(result.price)
            _seen_set(_acct, signal_id, "filled", result.order)   # [ISO-06]
            _slip = round((_fill - price) if direction == "BUY" else (price - _fill), 6)
            return jsonify({"status":"ok","order_id":result.order,"volume":result.volume,
                            "price":_fill,"signal_id":signal_id,
                            "requested_price":price,"fill_price":_fill,"slippage":_slip,
                            "bid":tick.bid,"ask":tick.ask,
                            "spread":round(tick.ask - tick.bid, 6),
                            "latency_ms":_latency_ms,"retcode":result.retcode,
                            "retry_count":0,"requotes":0})
        _seen_set(_acct, signal_id, "rejected")   # [ISO-06] broker said no: a retry is legitimate
        return jsonify({"status":"error","retcode":result.retcode,
                        "msg":result.comment,"signal_id":signal_id})

    except Exception as e:
        # Catch-all: never return empty body to bot
        tb = traceback.format_exc()
        log.error(f"[EXEC] UNHANDLED EXCEPTION: {e}\n{tb}")
        return jsonify({"status":"error","msg":f"executor exception: {e}",
                        "type":type(e).__name__}), 500

@app.route("/close", methods=["POST"])
def close():
    try:
        data = request.get_json(silent=True) or {}
        if data.get("secret") != SECRET:
            return jsonify({"status":"error","msg":"unauthorized"}), 403

        ticket = data.get("ticket") or data.get("order_id")
        if not ticket:
            return jsonify({"status":"error","msg":"ticket required"}), 400

        if not ensure_mt5():
            return jsonify({"status":"error","msg":"mt5 disconnected"}), 503

        positions = mt5.positions_get(ticket=int(ticket))
        if not positions:
            return jsonify({"status":"error","msg":f"position {ticket} not found"})

        pos = positions[0]
        if not _is_ours(pos):   # [ISO-05] never close what v7 did not open
            log.critical(f"[CLOSE] ticket {ticket} magic={getattr(pos,'magic',None)} comment={pos.comment!r} is not v7's - refusing")
            return jsonify({"status":"error","msg":"not_ours"}), 403
        _req_vol = data.get("volume")
        _close_vol = pos.volume if _req_vol is None else max(0.0, min(float(_req_vol), pos.volume))
        if _close_vol <= 0:
            return jsonify({"status":"error","msg":"invalid close volume"}), 400
        tick = mt5.symbol_info_tick(pos.symbol)
        if not tick:
            return jsonify({"status":"error","msg":f"no tick for {pos.symbol}"}), 400

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": _close_vol,
            "type": mt5.ORDER_TYPE_SELL if pos.type==0 else mt5.ORDER_TYPE_BUY,
            "position": pos.ticket,
            "price": tick.bid if pos.type==0 else tick.ask,
            "comment": "BS_close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        if result is None:
            return jsonify({"status":"error","msg":"order_send None","last_error":str(mt5.last_error())}), 502
        if result.retcode == 10009:
            return jsonify({"status":"ok","ticket":ticket,"close_price":result.price})
        return jsonify({"status":"error","retcode":result.retcode,"msg":result.comment})
    except Exception as e:
        log.error(f"/close exception: {e}\n{traceback.format_exc()}")
        return jsonify({"status":"error","msg":str(e)}), 500

@app.route("/candles", methods=["GET"])
def candles():
    try:
        if not ensure_mt5():
            return jsonify({"status":"error","msg":"mt5 not connected"}), 503
        raw_sym = (request.args.get("symbol") or "").upper()
        symbol = SYMBOL_MAP.get(raw_sym, raw_sym)
        tf_str = (request.args.get("tf") or "15").strip()
        n = int(request.args.get("n") or 100)
        n = max(1, min(n, 5000))
        tf_map = {"1":mt5.TIMEFRAME_M1, "5":mt5.TIMEFRAME_M5, "15":mt5.TIMEFRAME_M15,
                  "30":mt5.TIMEFRAME_M30, "60":mt5.TIMEFRAME_H1, "240":mt5.TIMEFRAME_H4,
                  "1440":mt5.TIMEFRAME_D1}
        tf = tf_map.get(tf_str, mt5.TIMEFRAME_M15)
        if not mt5.symbol_select(symbol, True):
            return jsonify({"status":"error","msg":f"symbol select failed: {symbol}"}), 400
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
        if rates is None or len(rates) == 0:
            return jsonify({"status":"error","msg":f"no candles for {symbol}",
                            "last_error":str(mt5.last_error())}), 400
        rows = [{"time":int(r["time"]), "open":float(r["open"]), "high":float(r["high"]),
                 "low":float(r["low"]), "close":float(r["close"]),
                 "volume":int(r["tick_volume"])} for r in rates]
        return jsonify({"status":"ok","symbol":symbol,"tf":tf_str,"count":len(rows),"rows":rows})
    except Exception as e:
        log.error(f"[CANDLES] error: {e}")
        return jsonify({"status":"error","msg":str(e)}), 500

@app.route("/modify", methods=["POST"])
def modify():
    try:
        data = request.get_json(silent=True) or {}
        if data.get("secret") != SECRET:
            return jsonify({"status":"error","msg":"unauthorized"}), 403
        ticket = data.get("ticket")
        if ticket is None:
            return jsonify({"status":"error","msg":"no ticket"}), 400
        if not ensure_mt5():
            return jsonify({"status":"error","msg":"mt5 not connected"}), 503
        positions = mt5.positions_get(ticket=int(ticket))
        if not positions:
            return jsonify({"status":"error","msg":f"position {ticket} not found"})
        pos = positions[0]
        if not _is_ours(pos):   # [ISO-05] never re-stop what v7 did not open
            log.critical(f"[MODIFY] ticket {ticket} magic={getattr(pos,'magic',None)} comment={pos.comment!r} is not v7's - refusing")
            return jsonify({"status":"error","msg":"not_ours"}), 403
        new_sl = float(data.get("sl", pos.sl))
        new_tp = float(data.get("tp", pos.tp))
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": pos.ticket,
            "sl": new_sl,
            "tp": new_tp,
        }
        log.info(f"[MODIFY] ticket={ticket} {pos.symbol} sl={pos.sl}->{new_sl} tp={pos.tp}->{new_tp}")
        result = mt5.order_send(req)
        if result is None:
            return jsonify({"status":"error","msg":"order_send None","last_error":str(mt5.last_error())}), 502
        if result.retcode == 10009:
            return jsonify({"status":"ok","ticket":ticket,"sl":new_sl,"tp":new_tp})
        return jsonify({"status":"error","retcode":result.retcode,"msg":result.comment})
    except Exception as e:
        log.error(f"[MODIFY] error: {e}")
        return jsonify({"status":"error","msg":str(e)}), 500

# [ISO-16] panic button with the same contract as the v18 executor's halt_admin.py:
# X-Admin-Token header, 503 when no token is configured, 401 when wrong. Engaging
# writes the shared witness, so it stops the v18 executor's new orders as well.
@app.route("/admin/halt", methods=["POST"])
def admin_halt():
    if not ADMIN_HALT_TOKEN:
        return jsonify({"status":"error","msg":"ADMIN_HALT_TOKEN not configured"}), 503
    if not __import__("secrets").compare_digest(request.headers.get("X-Admin-Token", ""), ADMIN_HALT_TOKEN):
        return jsonify({"status":"error","msg":"bad admin token"}), 401
    data = request.get_json(silent=True) or {}
    reason = str(data.get("reason") or "manual_admin_halt")
    p = _global_stop_engage(reason)
    log.critical(f"[GLOBAL-STOP] engaged by admin: {reason} -> {p}")
    return jsonify({"status":"halted","reason":reason,"global_stop":_global_stop_state(),"file":p})


@app.route("/admin/status", methods=["GET"])
def admin_status():
    if not ADMIN_HALT_TOKEN:
        return jsonify({"status":"error","msg":"ADMIN_HALT_TOKEN not configured"}), 503
    if not __import__("secrets").compare_digest(request.headers.get("X-Admin-Token", ""), ADMIN_HALT_TOKEN):
        return jsonify({"status":"error","msg":"bad admin token"}), 401
    return jsonify({"global_stop":_global_stop_state(),"file":_global_stop_path(),
                    "asserted_login":V7_MT5_LOGIN,"magic":V7_MAGIC})


if __name__ == "__main__":
    log.info("Brother Sniper Executor v3 starting on 0.0.0.0:5001")
    print("Brother Sniper Executor v3 - Windows VPS (with logging + reconnect)")
    print(f"Log file: {LOG_FILE}")
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
