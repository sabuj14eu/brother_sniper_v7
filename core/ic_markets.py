import os, logging, requests

log = logging.getLogger("sniper.icmarkets")

SYMBOL_MAP_CT = {
    "GOLD":"XAUUSD","SILVER":"XAGUSD","BITCOIN":"BTCUSD",
    "ETHEREUM":"ETHUSD","LITECOIN":"LTCUSD","RIPPLE":"XRPUSD",
    "USDJPY":"USDJPY","EURUSD":"EURUSD","GBPUSD":"GBPUSD","AUDUSD":"AUDUSD",
    "NZDUSD":"NZDUSD","USDCAD":"USDCAD","USDCHF":"USDCHF",
}

SECRET = os.getenv("WEBHOOK_SECRET","")

# Hoisted to module level (2026-08-18) so the symbol registry can overlay new
# instruments; values unchanged. Crypto list drives the 24/7 market-hours
# exemption; lot tables are the demo-mode safety caps from Patch E / F4.
CRYPTO_247 = ["BITCOIN","ETHEREUM","LITECOIN","RIPPLE","BTCUSD","ETHUSD"]
DEMO_MAX_LOT = {
    "GOLD": 0.50, "SILVER": 0.50,
    "BITCOIN": 0.10, "ETHEREUM": 0.50,
    "LITECOIN": 1.00, "RIPPLE": 1.00,
    "USDJPY": 1.00, "EURUSD": 1.00, "GBPUSD": 1.00,
    "AUDUSD": 1.00, "NZDUSD": 1.00, "USDCAD": 1.00, "USDCHF": 1.00,
    "US30": 1.00, "USTEC": 1.00,   # [F4 2026-07-02] were missing -> generic 0.10 cap masked bad sizing
}
MIN_LOT = {            # per-symbol broker minimum volume
    "US30": 0.10, "USTEC": 0.10, "US500": 0.10,   # index CFDs reject 0.01
}

class ICMarketsClient:
    def __init__(self):
        self.executor_url = os.getenv("EXECUTOR_URL","")
        self._connected = False
        self._login_ok  = False

    def connect(self):
        try:
            url = self.executor_url.replace("/execute","/health")
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                self._connected = True
                self._login_ok  = True
                log.info(f"[CT] Connected OK — MT5 account {data.get('account')} balance ${data.get('balance')}")
            else:
                raise ConnectionError(f"Health check failed: {r.status_code}")
        except Exception as e:
            raise ConnectionError(f"[CT] Cannot reach executor: {e}")

    def disconnect(self):
        self._connected = False
        self._login_ok  = False

    def login(self): return self._connected and self._login_ok

    def ensure_connected(self, retries=3):
        # Just ping the executor - no reconnection needed
        try:
            self.ping()
        except: pass
        return

    def ping(self):
        try:
            url = self.executor_url.replace("/execute","/health")
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                self._connected = False
                self._login_ok  = False
        except:
            self._connected = False
            self._login_ok  = False

    def get_balance(self):
        try:
            url = self.executor_url.replace("/execute","/health")
            r = requests.get(url, timeout=5)
            return float(r.json().get("balance", 1000.0))
        except Exception as e:
            fb = float(os.getenv("ACCOUNT_BALANCE","6000.0"))
            log.warning(f"[CT] get_balance FAILED ({type(e).__name__}) - using conservative fallback {fb}")
            return fb

    def get_open_trades(self): return []
    def get_closed_trades(self, hours_back=48): return []

    def fetch_symbol_spec(self, symbol):
        specs = {
            "GOLD":    {"tickSize":0.01,  "tickValue":1.00,"lotMin":0.01,"lotMax":50.0, "lotStep":0.01,"_source":"mt5"},
            "SILVER":  {"tickSize":0.001, "tickValue":5.00,"lotMin":0.01,"lotMax":50.0, "lotStep":0.01,"_source":"mt5"},
            "BITCOIN": {"tickSize":1.00,  "tickValue":1.00,"lotMin":0.01,"lotMax":2.0,  "lotStep":0.01,"_source":"mt5"},
            "ETHEREUM":{"tickSize":0.10,  "tickValue":0.10,"lotMin":0.01,"lotMax":10.0, "lotStep":0.01,"_source":"mt5"},
            "LITECOIN":{"tickSize":0.01,  "tickValue":0.01,"lotMin":0.01,"lotMax":50.0, "lotStep":0.01,"_source":"mt5"},
            "RIPPLE":  {"tickSize":0.0001,"tickValue":0.0001,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"mt5"},
            "USDJPY":  {"tickSize":0.001,  "tickValue":0.65,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"mt5"},
            "EURUSD":  {"tickSize":0.00001,"tickValue":1.00,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"mt5"},
            "GBPUSD":  {"tickSize":0.00001,"tickValue":1.00,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"mt5"},
            "AUDUSD":  {"tickSize":0.00001,"tickValue":1.00,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"mt5"},
            "NZDUSD":  {"tickSize":0.00001,"tickValue":1.00,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"mt5"},
            "USDCAD":  {"tickSize":0.00001,"tickValue":0.75,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"mt5"},
            "USDCHF":  {"tickSize":0.00001,"tickValue":1.27,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"mt5"},
            # [F4 2026-07-02] indices added — were missing, unknown symbols fell back to GOLD's spec.
            # $1/point/lot assumed — VERIFY against MT5 symbol specification and correct if needed.
            "US30":    {"tickSize":1.0,   "tickValue":1.00,"lotMin":0.10,"lotMax":50.0, "lotStep":0.10,"_source":"mt5"},
            "USTEC":   {"tickSize":0.1,   "tickValue":0.10,"lotMin":0.10,"lotMax":50.0, "lotStep":0.10,"_source":"mt5"},
        }
        # [F4] unknown symbol -> {} (invalid) so get_spec falls through to bot SAFE_SPECS
        # instead of silently sizing with GOLD's tick math.
        return specs.get(symbol) or {}

    def is_market_open(self, symbol):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        weekday = now.weekday()  # 0=Monday, 6=Sunday
        hour = now.hour

        # Crypto trades 24/7
        if symbol in CRYPTO_247:
            return True

        # Metals/Forex closed Saturday and Sunday before 22:00 UTC
        if weekday == 5:  # Saturday - always closed
            return False
        if weekday == 6 and hour < 22:  # Sunday before 22:00 UTC
            return False
        if weekday == 4 and hour >= 22:  # Friday after 22:00 UTC
            return False

        return True

    def open_trade(self, symbol, direction, volume, sl, tp, comment="BS"):
        ct_symbol = SYMBOL_MAP_CT.get(symbol, symbol)
        # Patch E: respect calc_lot() output. Per-symbol safety caps in the
        # module-level DEMO_MAX_LOT / MIN_LOT tables above — demo-mode hard
        # ceilings that stop any wild calc_lot() blow-up on a $6k demo.
        vol = round(max(MIN_LOT.get(symbol, 0.01), min(volume, DEMO_MAX_LOT.get(symbol, 0.10))), 2)
        if vol != round(volume, 2):
            log.info(f"[CT] lot adjusted: requested {volume} → sent {vol} (cap={DEMO_MAX_LOT.get(symbol,0.10)})")

        # Check market hours
        if not self.is_market_open(symbol):
            log.warning(f"[CT] Market closed for {symbol} — skipping trade")
            return {"status": False, "errorDescr": f"Market closed for {symbol}"}

        log.info(f"[CT] Sending to MT5: {direction} {ct_symbol} vol={vol} sl={sl} tp={tp}")
        try:
            payload = {
                "secret":    SECRET,
                "symbol":    ct_symbol,
                "direction": direction,
                "lot":       vol,
                "sl":        sl,
                "tp":        tp,
                "signal_id": comment,
            }
            r = requests.post(self.executor_url, json=payload, timeout=15)
            data = r.json()
            log.info(f"[CT] MT5 response: {data}")
            if data.get("status") == "ok":
                _rd = {"order": data.get("order_id", 0), "volume": data.get("volume", vol)}
                # [TELEMETRY 08-01] pass the bridge's execution facts through to
                # the telemetry logger (was dropped here before). Log-only.
                for _k in ("price", "requested_price", "fill_price", "slippage",
                           "bid", "ask", "spread", "latency_ms", "fill_delay_ms",
                           "retcode", "retry_count", "requotes"):
                    if _k in data:
                        _rd[_k] = data[_k]
                return {"status": True, "returnData": _rd}
            return {"status": False, "errorDescr": data.get("msg","MT5 error")}
        except Exception as e:
            log.error(f"[CT] Executor error: {e}")
            return {"status": False, "errorDescr": str(e)}

    def close_trade(self, order_id, symbol, volume, direction):
        """Close a specific MT5 position. Returns {"status": bool, "raw": dict}."""
        try:
            url = self.executor_url.replace("/execute","/close")
            payload = {
                "secret": SECRET,
                "ticket": int(order_id),
                "symbol": symbol,
                "volume": float(volume),
                "direction": direction,
            }
            r = requests.post(url, json=payload, timeout=15)
            raw = r.json() if r.headers.get("content-type","").startswith("application/json") else {"text": r.text}
            # Real success = executor explicitly says ok / closed / success
            ok = (
                raw.get("status") in ("ok","closed","success",True) or
                raw.get("result") in ("ok","closed","success") or
                "closed" in str(raw).lower() and "error" not in str(raw).lower()
            )
            return {"status": bool(ok), "raw": raw, "http_code": r.status_code}
        except Exception as e:
            return {"status": False, "errorDescr": str(e), "raw": {}}

    def modify_sl(self, order_id, new_sl, new_tp=0.0):
        """Modify SL (and optionally TP) on an open position via executor /modify.
        Returns {"status": bool, "raw": dict}. Fail-safe: status False on any error."""
        try:
            url = self.executor_url.replace("/execute","/modify")
            payload = {"secret": SECRET, "ticket": int(order_id), "sl": float(new_sl)}
            if new_tp and float(new_tp) > 0:
                payload["tp"] = float(new_tp)
            r = requests.post(url, json=payload, timeout=15)
            raw = r.json() if r.headers.get("content-type","").startswith("application/json") else {"text": r.text}
            ok = raw.get("status") in ("ok","success",True)
            return {"status": bool(ok), "raw": raw, "http_code": r.status_code}
        except Exception as e:
            return {"status": False, "errorDescr": str(e), "raw": {}}
