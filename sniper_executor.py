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
import logging, os, re, sys, time, traceback
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

# ── READ-ENDPOINT KEY (optional; default OFF so nothing breaks on deploy) ────
# The platform proxies /candles server-side for the live chart, so this port
# is no longer reached only from our own box. When BRIDGE_KEY is set, the
# market-DATA reads require the X-Bridge-Key header.
#
# Deliberately NOT applied to /health, /positions or /history: the bot and the
# dashboard poll those, /positions is on the live trading path, and locking a
# trading dependency to gain nothing on public market data is a bad trade.
# Order placement is unaffected — it has always required WEBHOOK_SECRET.
BRIDGE_KEY = os.getenv("BRIDGE_KEY", "").strip()


def _key_ok() -> bool:
    """True when reads are allowed. Unset key = auth off = today's behaviour."""
    if not BRIDGE_KEY:
        return True
    import hmac
    return hmac.compare_digest(request.headers.get("X-Bridge-Key", ""), BRIDGE_KEY)


def _denied():
    """401 without ever echoing the supplied or expected key."""
    return jsonify({"status": "error", "msg": "bridge key required"}), 401

# Symbol mapping: bot's name → IC Markets MT5 symbol
SYMBOL_MAP = {
    # Metals
    "GOLD":"XAUUSD", "XAUUSD":"XAUUSD", "XAU":"XAUUSD",
    "SILVER":"XAGUSD", "XAGUSD":"XAGUSD", "XAG":"XAGUSD",
    # Crypto — ETH variants now mapped (was missing in v2)
    "BITCOIN":"BTCUSD", "BTCUSD":"BTCUSD", "BTC":"BTCUSD", "BTCUSDT":"BTCUSD",
    "ETHEREUM":"ETHUSD", "ETHUSD":"ETHUSD", "ETH":"ETHUSD", "ETHUSDT":"ETHUSD",
    "XRP":"XRPUSD", "XRPUSD":"XRPUSD", "XRPUSDT":"XRPUSD",
    # [08-19 BUG FOUND BY THE SPEC PROBE] The v7 BOT renames XRPUSD -> "RIPPLE"
    # and LTCUSD -> "LITECOIN" internally, then sends THAT name here. Neither
    # key existed in this map, so "RIPPLE" was passed to MT5 verbatim as an
    # unknown symbol and every v7 XRP/LTC order died at the broker — invisible
    # until an order was actually attempted. Aliases must cover the BOT's
    # vocabulary, not just the broker's.
    "RIPPLE":"XRPUSD",
    "LITECOIN":"LTCUSD", "LTCUSD":"LTCUSD", "LTC":"LTCUSD",
    # staging candidates (probe confirmed SOL/ADA exist and are FULL tradable)
    "SOLANA":"SOLUSD", "SOLUSD":"SOLUSD", "SOL":"SOLUSD",
    "CARDANO":"ADAUSD", "ADAUSD":"ADAUSD", "ADA":"ADAUSD",
    "CHAINLINK":"LINKUSD", "LINKUSD":"LINKUSD", "LINK":"LINKUSD",
    # Forex
    "EURUSD":"EURUSD", "USDJPY":"USDJPY", "GBPUSD":"GBPUSD",
    "AUDUSD":"AUDUSD", "USDCAD":"USDCAD", "USDCHF":"USDCHF",
    "NZDUSD":"NZDUSD", "EURJPY":"EURJPY", "GBPJPY":"GBPJPY",
    # Indices (just in case)
    "DXY":"USDX",
}

# ── MACRO MEASUREMENT LEGS (read-only; DATED CONTRACTS THAT ROLL) ────────────
# Probed 08-19 on this terminal: UST10Y_U6 "US T-Note 10 YR-September 26 CFD"
# and UST30Y_U6 "US T-Bond 30 YR-September 26 CFD".
#
# These exist so the event-reaction recorder can measure whether a macro shock
# TRANSMITTED — DXY + yields -> metals/indices — instead of only asking whether
# the dollar agreed. They are a measurement leg, never a signal: nothing here
# gives US10Y a vote in any trading decision.
#
# `_U6` is SEPTEMBER 2026. It WILL roll, the old symbol will stop printing new
# bars, and nothing will raise: a dead dated contract looks exactly like a
# quiet market. Hence env overrides — a roll is a config change and a restart,
# not a code deploy. The platform's Live Bridge page shows newest-bar age,
# which is the detector: if the yield leg's age stops moving, it has rolled.
SYMBOL_MAP.update({
    "US10Y":  os.getenv("MT5_US10Y_SYMBOL", "UST10Y_U6"),
    "UST10Y": os.getenv("MT5_US10Y_SYMBOL", "UST10Y_U6"),
    "US30Y":  os.getenv("MT5_US30Y_SYMBOL", "UST30Y_U6"),
    "UST30Y": os.getenv("MT5_US30Y_SYMBOL", "UST30Y_U6"),
    # [08-19 PROBED] DXY was mapped to USDX, which this terminal DOES NOT LIST
    # ("Terminal: Not found"). Every DXY read through this bridge has been
    # failing since the map was written — invisibly, because a missing symbol
    # and a quiet symbol look identical from the caller's side. DXY_U6 is
    # present and printing (bid 98.67 at the probe), and it is what the brain
    # box already reads, so both terminals now agree on one instrument.
    # Dated, like the others: it rolls, hence the override.
    "DXY":    os.getenv("MT5_DXY_SYMBOL", "DXY_U6"),
    "USDX":   os.getenv("MT5_DXY_SYMBOL", "DXY_U6"),
})

# ── FRONT-CONTRACT RESOLVER (macro read paths only) ─────────────────────────
# The static entries above name SEPTEMBER 2026 contracts. In a few weeks they
# expire, stop printing bars, and return nothing — with no error anywhere.
# That is the USDX bug's cousin: a name that resolves to a symbol the broker
# no longer serves is indistinguishable from a quiet market.
#
# So the macro roots resolve to their FRONT (nearest non-expired) contract at
# request time, refreshed hourly. When no valid contract exists the answer is
# NOTHING — the caller reports UNKNOWN. A silently expired contract is never
# served, and an expiring one is never "fixed" by guessing the next code.
#
# READ PATHS ONLY. /execute still uses SYMBOL_MAP directly: the trading path
# does not change because of a resolver written for analytics.
_MACRO_ROOTS = {"DXY": "DXY", "USDX": "DXY",
                "US10Y": "UST10Y", "UST10Y": "UST10Y",
                "US30Y": "UST30Y", "UST30Y": "UST30Y"}
_MONTH_CODES = "FGHJKMNQUVXZ"          # CME: F=Jan, G=Feb ... Z=Dec
_CONTRACT_RE = re.compile(r"^[A-Z0-9]+_([FGHJKMNQUVXZ])(\d{1,2})$")
_FRONT_TTL = 3600
_front_cache = {}


def parse_contract_expiry(name, now_ts):
    """Approximate expiry from a CME-style suffix (DXY_U6 -> end of Sep 2026).

    Fallback only — MT5's own expiration_time wins when the broker supplies
    it. A single-digit year is read into the current decade, rolling forward
    when that would place the contract in the past."""
    m = _CONTRACT_RE.match(str(name or "").upper())
    if not m:
        return None
    month = _MONTH_CODES.index(m.group(1)) + 1
    yr = m.group(2)
    now = datetime.utcfromtimestamp(now_ts)
    if len(yr) == 2:
        year = 2000 + int(yr)
    else:
        year = (now.year // 10) * 10 + int(yr)
        if year < now.year - 1:
            year += 10
    # Valid through the END of its month: the first instant of the next one.
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    return (datetime(ny, nm, 1) - datetime(1970, 1, 1)).total_seconds()


def pick_front(candidates, now_ts):
    """[(name, expiration_ts)] -> the nearest contract that has NOT expired.

    None when every candidate is expired or unreadable. Returning None is the
    point: the caller must then say UNKNOWN rather than serve a dead series."""
    live = []
    for name, exp in candidates or []:
        e = exp if exp and exp > 0 else parse_contract_expiry(name, now_ts)
        if e and e > now_ts:
            live.append((e, name))
    if not live:
        return None
    return min(live)[1]


def _macro_front(root):
    """Front contract for one macro root, cached for an hour. Never raises."""
    now = time.time()
    hit = _front_cache.get(root)
    if hit and now - hit[1] < _FRONT_TTL:
        return hit[0]
    best = None
    try:
        cands = []
        for s in (mt5.symbols_get(f"*{root}*") or []):
            nm = str(getattr(s, "name", "") or "").upper()
            if nm.startswith(root + "_") and _CONTRACT_RE.match(nm):
                cands.append((nm, int(getattr(s, "expiration_time", 0) or 0)))
        best = pick_front(cands, now)
        prev = (hit or (None,))[0]
        if best != prev:
            log.warning(f"[MACRO] {root} front contract -> {best or 'NONE'} "
                        f"(was {prev or 'unset'}; {len(cands)} candidates)")
    except Exception as e:
        log.warning(f"[MACRO] {root} front-contract lookup failed: {e}")
    _front_cache[root] = (best, now)
    return best


def _resolve_symbol(raw):
    """Read-path resolution. Macro roots -> front dated contract (or "" when
    none is live); everything else -> the static map, unchanged."""
    up = str(raw or "").upper()
    root = _MACRO_ROOTS.get(up)
    if not root:
        return SYMBOL_MAP.get(up, up)
    override = os.getenv(f"MT5_{up}_SYMBOL", "").strip()
    return override or (_macro_front(root) or "")

# ── MT5 CONNECTION MANAGEMENT ───────────────────────────────────────────────
_off_cache = {"t": 0.0, "off": 0}
def _broker_utc_offset():
    """Broker-clock minus UTC, seconds (cached 1h). BTCUSD ticks 24/7 so its
    tick time is a live broker clock. [AUDIT BOT-P0-4] candle epochs are
    broker time; consumers compare against UTC — normalize at the source."""
    import time as _t
    now = _t.time()
    if now - _off_cache["t"] < 3600:
        return _off_cache["off"]
    try:
        tk = mt5.symbol_info_tick("BTCUSD")
        if tk and tk.time and abs(tk.time - now) < 6 * 3600:
            _off_cache.update(t=now, off=int(round((tk.time - now) / 1800.0) * 1800))
    except Exception:
        pass
    return _off_cache["off"]

def _tick_spread(symbol):
    """Live bid/ask/spread for one broker symbol. Read-only, never raises —
    the analytics spread-at-decision source (Pine's v6_spread is only a
    range-stress proxy, not real spread)."""
    try:
        sym = _resolve_symbol(symbol)
        if not sym:
            return {"symbol": str(symbol or "").upper(), "spread": None,
                    "reason": "no live contract (dated contract rolled?)"}
        tk = mt5.symbol_info_tick(sym)
        info = mt5.symbol_info(sym)
        if not tk or not tk.bid or not tk.ask:
            return {"symbol": sym, "spread": None}
        spread = float(tk.ask) - float(tk.bid)
        point = float(getattr(info, "point", 0) or 0)
        return {"symbol": sym, "bid": float(tk.bid), "ask": float(tk.ask),
                "spread": round(spread, 8),
                "spread_points": round(spread / point, 1) if point > 0 else None}
    except Exception:
        return {"symbol": symbol, "spread": None}


def ensure_mt5():
    """Ensure MT5 is connected. Returns True if healthy, False if dead."""
    acc = mt5.account_info()
    if acc is not None:
        return True
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
    return True

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
@app.route("/symbolspec", methods=["GET"])
def symbolspec_route():
    """Read-only broker truth for one symbol: decimals, tick size/value, lot
    bounds, and whether it is actually tradable. Exists because a wrong
    decimal count collapses two tradable levels into one displayed price —
    so no coin goes live until these numbers are confirmed against the
    platform's display config. Never places anything."""
    if not _key_ok():
        return _denied()
    sym_in = str(request.args.get("symbol", "") or "").upper()
    sym = _resolve_symbol(sym_in)
    if not sym:
        return jsonify({"requested": sym_in, "ok": False,
                        "reason": "no_live_contract",
                        "detail": "dated contract rolled and no successor is "
                                  "listed — reporting UNKNOWN, not a dead series"}), 404
    try:
        if not ensure_mt5():
            return jsonify({"symbol": sym, "ok": False, "reason": "mt5_not_connected"}), 503
        mt5.symbol_select(sym, True)          # a hidden symbol has no spec until selected
        info = mt5.symbol_info(sym)
        if info is None:
            return jsonify({"symbol": sym, "requested": sym_in, "ok": False,
                            "reason": "unknown_symbol",
                            "last_error": str(mt5.last_error())}), 404
        _MODES = {0: "DISABLED", 1: "LONG_ONLY", 2: "SHORT_ONLY",
                  3: "CLOSE_ONLY", 4: "FULL"}
        tk = mt5.symbol_info_tick(sym)
        return jsonify({
            "ok": True, "requested": sym_in, "symbol": sym,
            "digits": info.digits,                    # <- the decimals the platform must match
            "point": info.point,
            "tick_size": info.trade_tick_size,
            "tick_value": info.trade_tick_value,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "trade_mode": _MODES.get(getattr(info, "trade_mode", None), "UNKNOWN"),
            "tradable": _MODES.get(getattr(info, "trade_mode", None)) == "FULL",
            "visible": bool(getattr(info, "visible", False)),
            "spread_points": getattr(info, "spread", None),
            "bid": float(tk.bid) if tk and tk.bid else None,
            "ask": float(tk.ask) if tk and tk.ask else None,
        })
    except Exception as e:
        return jsonify({"symbol": sym, "ok": False, "reason": type(e).__name__}), 500


@app.route("/spread", methods=["GET"])
def spread_route():
    if not _key_ok():
        return _denied()
    return jsonify(_tick_spread(request.args.get("symbol", "")))


@app.route("/health", methods=["GET"])
def health():
    if not ensure_mt5():
        return jsonify({"status":"error","msg":"mt5 disconnected"}), 503
    acc = mt5.account_info()
    if acc:
        return jsonify({"status":"ok","account":acc.login,"balance":acc.balance,"equity":acc.equity})
    return jsonify({"status":"error","msg":"no account info"}), 503

@app.route("/positions", methods=["GET"])
def positions():
    try:
        ensure_mt5()
        pos = mt5.positions_get()
        if pos:
            return jsonify({"count":len(pos),"positions":[
                {"ticket":p.ticket,"symbol":p.symbol,"profit":p.profit,
                 "volume":p.volume,"type":"BUY" if p.type==0 else "SELL",
                 "price_open":p.price_open,"price_current":p.price_current,"sl":p.sl,"tp":p.tp,"comment":p.comment}
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
            "comment": "BS_" + __import__("hashlib").md5(str(signal_id).encode()).hexdigest()[:8],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        log.info(f"[EXEC] {signal_id} order_send: {direction} {symbol} vol={volume} px={price} sl={sl} tp={tp}")

        # [TELEMETRY 08-01] time the broker round-trip. Log-only: the request
        # above and order_send below are byte-identical to before.
        _t0 = datetime.utcnow()
        result = mt5.order_send(req)
        _latency_ms = round((datetime.utcnow() - _t0).total_seconds() * 1000.0, 1)

        # Handle MT5 returning None (connection issue mid-flight)
        if result is None:
            err = mt5.last_error()
            log.error(f"[EXEC] {signal_id} order_send returned None, mt5.last_error={err}")
            return jsonify({"status":"error","msg":"order_send returned None",
                            "last_error":str(err)}), 502

        log.info(f"[EXEC] {signal_id} retcode={result.retcode} comment={result.comment} order={result.order}")

        if result.retcode == 10009:  # TRADE_RETCODE_DONE
            # [TELEMETRY 08-01] execution facts for the feature store (log-only).
            # slippage: positive = filled WORSE than the requested price.
            _fill = float(result.price)
            _slip = round((_fill - price) if direction == "BUY" else (price - _fill), 6)
            return jsonify({"status":"ok","order_id":result.order,"volume":result.volume,
                            "price":_fill,"signal_id":signal_id,
                            "requested_price":price,"fill_price":_fill,"slippage":_slip,
                            "bid":tick.bid,"ask":tick.ask,
                            "spread":round(tick.ask - tick.bid, 6),
                            "latency_ms":_latency_ms,"retcode":result.retcode,
                            "retry_count":0,"requotes":0})
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
        symbol = _resolve_symbol(raw_sym)
        if not symbol:
            return jsonify({"status":"error","msg":f"no live contract for {raw_sym} "
                            "— the dated contract rolled and no successor is listed",
                            "macro_unresolved":True}), 404
        tf_str = (request.args.get("tf") or "15").strip()
        n = int(request.args.get("n") or 100)
        n = max(1, min(n, 5000))
        tf_map = {"1":mt5.TIMEFRAME_M1, "5":mt5.TIMEFRAME_M5, "15":mt5.TIMEFRAME_M15,
                  "30":mt5.TIMEFRAME_M30, "60":mt5.TIMEFRAME_H1, "240":mt5.TIMEFRAME_H4,
                  "1440":mt5.TIMEFRAME_D1}
        tf = tf_map.get(tf_str, mt5.TIMEFRAME_M15)
        if not mt5.symbol_select(symbol, True):
            return jsonify({"status":"error","msg":f"symbol select failed: {symbol}"}), 400
        # [AUDIT BOT-P0-3] start=1: CLOSED bars only — the live bar repaints,
        # and a repainting bar in an analytics window is a fabricated result.
        # ?live=1 opts INTO the forming bar for one purpose only: drawing a
        # live chart, where a candle that is still moving is the point. It is
        # flagged in the payload and on the row, never silently mixed in, so
        # no analytics caller can consume it by accident.
        live = str(request.args.get("live") or "").lower() in ("1", "true", "yes")
        # The KEY guards the LIVE path only, and that is not a compromise —
        # it is where the exposure actually is. Closed bars have been served
        # openly on this port since day one and are read by the trading bot
        # itself (bot.py fetch_atr, ATR when Pine omits it), by analyst_eye and
        # by the status dashboard, none of which carry a key. Gating them would
        # have put a credential in front of a live trading dependency to
        # protect public market data — silently, since fetch_atr fails safe to
        # None. The forming bar is the new capability, the platform proxy is
        # its only caller, and it is fully authenticated.
        if live and not _key_ok():
            return _denied()
        rates = mt5.copy_rates_from_pos(symbol, tf, 0 if live else 1, n)
        if rates is None or len(rates) == 0:
            return jsonify({"status":"error","msg":f"no candles for {symbol}",
                            "last_error":str(mt5.last_error())}), 400
        _off = _broker_utc_offset()
        rows = [{"time":int(r["time"]) - _off, "open":float(r["open"]), "high":float(r["high"]),
                 "low":float(r["low"]), "close":float(r["close"]),
                 "volume":int(r["tick_volume"])} for r in rates]
        if live and rows:
            rows[-1]["forming"] = True      # still moving; will repaint
        _sp = _tick_spread(symbol)
        return jsonify({"status":"ok","symbol":symbol,"tf":tf_str,"count":len(rows),"rows":rows,
                        "closed_only":not live,"utc_normalized":True,
                        "forming_last":bool(live and rows),
                        "spread":_sp.get("spread"),"spread_points":_sp.get("spread_points"),
                        "bid":_sp.get("bid"),"ask":_sp.get("ask")})
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

if __name__ == "__main__":
    log.info("Brother Sniper Executor v3 starting on 0.0.0.0:5001")
    print("Brother Sniper Executor v3 - Windows VPS (with logging + reconnect)")
    print(f"Log file: {LOG_FILE}")
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
