"""
Brother Sniper Bot v7 — Self-Adjusting Decision System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
New in v7:
  governance/discipline.py  — anti-overfitting, weight freeze, decay cap
  learning/cluster_engine.py — setup clustering + expectancy scoring
  learning/weight_engine.py v2 — discipline-aware calibration + cluster rebuild

Signal decision priority (explicit):
  1. EquityGuard       → hard block (capital protection)
  2. News filter       → hard block (event risk)
  3. Discipline/EV     → hard block (negative expected value)
  4. Regime detect     → adapts SL mult + threshold + position scale
  5. AI filter         → soft block (learned weights, regime-aware threshold)
  6. SL engine         → execution modifier
  7. R:R validator     → execution gate
  8. Discipline pos scale → final lot size adjustment

Telegram on trade open now shows:
  EV score (cluster expectancy)
  Cluster key + sample count
  Weights calibration date
  Regime confidence + position scale
"""

import json, time, hmac, hashlib, ipaddress
import threading, logging, logging.handlers, os, signal
import tempfile, shutil, requests
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, abort
from dotenv import load_dotenv

# ── Local modules ──────────────────────────────────────────────────────────────
from core.sl_engine          import calculate_institutional_sl, validate_rr, SLResult
from core import signal_memory as mem
from core.ic_markets         import ICMarketsClient
from filters.ai_filter        import score_signal, FilterResult

# ── Phase 2 (log-only): Market Flow Vector from Pine payload fields ──
def compute_flow_vector(payload):
    """Classify macro regime from Pine's fields. Log-only — never affects trades."""
    dxy=str(payload.get("dxy_dir","")).upper(); yld=str(payload.get("yield_dir","")).upper()
    vol=str(payload.get("vol_regime","")).upper(); adx=float(payload.get("adx") or 0)
    macro=int(payload.get("macro_score") or 0); trend_day=bool(payload.get("trend_day"))
    ny=str(payload.get("ny_regime","")).upper()
    dxy_up="RISING" in dxy; dxy_dn="FALLING" in dxy
    yld_up="RISING" in yld; yld_dn="FALLING" in yld
    if dxy_up and yld_up:   vector="RISK_OFF_USD"
    elif dxy_dn and yld_dn: vector="RISK_ON"
    elif dxy_up and yld_dn: vector="INFLATION_DEFENSIVE"
    elif dxy_dn and yld_up: vector="GROWTH_REFLATION"
    else:                   vector="MIXED"
    if "HIGH" in vol and adx<20:        vector="CHOP"
    elif ny=="TREND" and trend_day:     vector="TREND_DAY"
    return {"vector":vector,"dxy_dir":dxy,"yield_dir":yld,"vol_regime":vol,
            "adx":adx,"macro_score":macro,"ny_regime":ny,"trend_day":trend_day}


# ── Phase 1: live ATR from executor /candles (computes when Pine omits atr) ──
def fetch_atr(symbol, tf="15", n=30, period=14):
    """ATR(14) from executor candles. Returns None on any failure (fail-safe).
    Guards stale feeds: rejects if newest candle older than ~3 bars."""
    import time as _t
    try:
        base = os.getenv("EXECUTOR_URL", "").replace("/execute", "")
        if not base:
            return None
        r = requests.get(f"{base}/candles",
                         params={"symbol": symbol, "tf": tf, "n": n}, timeout=8)
        d = r.json()
        rows = d.get("rows") or []
        if len(rows) < period + 1:
            return None
        # stale guard: newest candle must be within 3 bars of now
        bar_s = int(tf) * 60 if str(tf).isdigit() else 900
        if _t.time() - int(rows[-1]["time"]) > bar_s * 3:
            log.warning(f"[ATR] {symbol} stale candles (newest {rows[-1]['time']}) — skipping")
            return None
        trs = []
        for i in range(1, len(rows)):
            h, l = rows[i]["high"], rows[i]["low"]
            pc = rows[i-1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr_val = sum(trs[-period:]) / period
        log.info(f"[ATR] {symbol} computed ATR({period})={atr_val:.5f} from {len(rows)} candles")
        return atr_val
    except Exception as e:
        log.warning(f"[ATR] {symbol} fetch failed: {e}")
        return None

from risk.equity_guard        import EquityGuard
from learning.trade_memory    import (TradeRecord, open_trade as mem_open,
                                      close_trade as mem_close, stats_summary)
from learning.weight_engine   import recalibrate, format_calibration_telegram, load_weights
from learning.regime_detector import detect_regime, RegimeResult
from learning.cluster_engine  import lookup_cluster, ClusterLookup
from governance.discipline    import DisciplineGovernor, DisciplineResult

load_dotenv()

# ━━ Logging ────────────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for d in ("logs", "learning", "governance"):
    os.makedirs(d, exist_ok=True)

log = logging.getLogger("sniper")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_fh  = logging.handlers.RotatingFileHandler("logs/bot.log", maxBytes=5_000_000, backupCount=3)
_fh.setFormatter(_fmt)
_sh  = logging.StreamHandler(); _sh.setFormatter(_fmt)
log.addHandler(_fh); log.addHandler(_sh)

app = Flask(__name__)

# ━━ Config ─────────────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _req(k, h=""):
    v = os.getenv(k, "").strip()
    if not v: raise SystemExit(f"ERROR: Missing env var {k}" + (f" — {h}" if h else ""))
    return v

def _opt(k, d=""): return os.getenv(k, d).strip()

XTB_USER         = _req("XTB_USER",         "Your XTB account number")
XTB_PASS         = _req("XTB_PASS",         "Your XTB password")
WEBHOOK_SECRET   = _req("WEBHOOK_SECRET",   "openssl rand -hex 24")
TELEGRAM_TOKEN   = _req("TELEGRAM_TOKEN",   "@BotFather")
TELEGRAM_CHAT_ID = _req("TELEGRAM_CHAT_ID", "@userinfobot")
USE_DEMO         = _opt("USE_DEMO", "true").lower() == "true"
TRUSTED_IPS_RAW  = _opt("TRUSTED_IPS", "")
TV_HMAC_SECRET   = _opt("TV_HMAC_SECRET", "")
XTB_HOST         = "xapi.xtb.com"
XTB_PORT         = 5124 if USE_DEMO else 5112
SIGNAL_DEDUP_MIN = 10
SPEC_REFRESH_HRS = 6
MIN_RR           = 1.0   # [F2 2026-07-02] was 0.5 — bot was live-trading 0.63R setups (needs 61% WR to break even)
CALIBRATION_HRS  = 24

# ━━ Symbol config ─────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SYMBOL_MAP = {
    "XAUUSD":"GOLD","GOLD":"GOLD","XAGUSD":"SILVER","SILVER":"SILVER",
    "BTCUSD":"BITCOIN","BITCOIN":"BITCOIN","ETHUSD":"ETHEREUM","ETHEREUM":"ETHEREUM",
    "LTCUSD":"LITECOIN","LITECOIN":"LITECOIN","XRPUSD":"RIPPLE","RIPPLE":"RIPPLE",
    "USDJPY":"USDJPY","EURUSD":"EURUSD","GBPUSD":"GBPUSD","AUDUSD":"AUDUSD",
    "NZDUSD":"NZDUSD","USDCAD":"USDCAD","USDCHF":"USDCHF",
    "US30":"US30","DJ30":"US30","WS30":"US30",
    "USTEC":"USTEC","NAS100":"USTEC","US100":"USTEC","NDX":"USTEC",
}
ALLOWED_SYMBOLS = set(SYMBOL_MAP.values())

# [F3 2026-07-02] per-symbol price digits — round(x, 2) was corrupting 5-digit
# forex stops (EURUSD 1.17345 -> 1.17 = SL moved ~35 pips) in trust+floor,
# regime-pad and breakeven paths.
_PX_DIGITS = {"GOLD":2,"SILVER":3,"BITCOIN":2,"ETHEREUM":2,"LITECOIN":2,"RIPPLE":4,
              "USDJPY":3,"EURUSD":5,"GBPUSD":5,"AUDUSD":5,"NZDUSD":5,"USDCAD":5,"USDCHF":5,
              "US30":1,"USTEC":1}
def round_px(sym, px):
    return round(float(px), _PX_DIGITS.get(sym, 2))
SAFE_SPECS = {
    "GOLD":    {"tickSize":0.01,  "tickValue":1.00,"lotMin":0.01,"lotMax":50.0, "lotStep":0.01,"_source":"fallback"},
    "SILVER":  {"tickSize":0.001, "tickValue":5.00,"lotMin":0.01,"lotMax":50.0, "lotStep":0.01,"_source":"fallback"},
    "BITCOIN": {"tickSize":1.00,  "tickValue":1.00,"lotMin":0.01,"lotMax":2.0,  "lotStep":0.01,"_source":"fallback"},
    "ETHEREUM":{"tickSize":0.10,  "tickValue":0.10,"lotMin":0.01,"lotMax":10.0, "lotStep":0.01,"_source":"fallback"},
    "LITECOIN":{"tickSize":0.01,  "tickValue":0.01,"lotMin":0.01,"lotMax":50.0, "lotStep":0.01,"_source":"fallback"},
    "RIPPLE":  {"tickSize":0.0001,"tickValue":0.0001,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"fallback"},
    "USDJPY":  {"tickSize":0.001,  "tickValue":0.65,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"fallback"},
    "EURUSD":  {"tickSize":0.00001,"tickValue":1.00,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"fallback"},
    "GBPUSD":  {"tickSize":0.00001,"tickValue":1.00,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"fallback"},
    "AUDUSD":  {"tickSize":0.00001,"tickValue":1.00,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"fallback"},
    "NZDUSD":  {"tickSize":0.00001,"tickValue":1.00,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"fallback"},
    "USDCAD":  {"tickSize":0.00001,"tickValue":0.75,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"fallback"},
    "USDCHF":  {"tickSize":0.00001,"tickValue":1.27,"lotMin":0.01,"lotMax":100.0,"lotStep":0.01,"_source":"fallback"},
    # [F4 2026-07-02] indices were MISSING — get_spec fell back to GOLD's tick math
    # and lot sizing for USTEC/US30 was arbitrary. $1/point/lot assumed — VERIFY
    # against MT5 symbol specification window and correct if IC Markets differs.
    "US30":    {"tickSize":1.0,   "tickValue":1.00,"lotMin":0.10,"lotMax":50.0, "lotStep":0.10,"_source":"fallback"},
    "USTEC":   {"tickSize":0.1,   "tickValue":0.10,"lotMin":0.10,"lotMax":50.0, "lotStep":0.10,"_source":"fallback"},
}

# ━━ IP + Rate ──────────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_TV_CIDRS = ["52.89.214.238/32","34.212.75.30/32","54.218.53.128/32","52.32.178.7/32",
             "54.237.33.0/24","52.0.239.0/24","52.1.168.0/24","34.200.0.0/16","18.214.0.0/16"]

def _parse_nets(raw):
    nets = []
    for e in (_TV_CIDRS + [s.strip() for s in raw.split(",") if s.strip()]):
        try: nets.append(ipaddress.IPv4Network(e, strict=False))
        except ValueError: pass
    return nets

_ALL_NETS  = _parse_nets(TRUSTED_IPS_RAW)
_rate_data = defaultdict(list)
_rate_lock = threading.Lock()

def _ip_ok(ip):
    if not _ALL_NETS: return True
    try: a = ipaddress.IPv4Address(ip); return any(a in n for n in _ALL_NETS)
    except Exception: return False

def _rate_ok(ip):
    now = time.time()
    with _rate_lock:
        _rate_data[ip] = [t for t in _rate_data[ip] if now - t < 60]
        if len(_rate_data[ip]) >= 10: return False
        _rate_data[ip].append(now); return True

# ━━ State ──────────────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATE_FILE  = "state.json"
_state_lock = threading.Lock()

def _atomic_write(path, data):
    d  = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f: json.dump(data, f, indent=2); f.flush(); os.fsync(f.fileno())
        shutil.move(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except Exception: pass
        raise


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

def load_state():
    s = None
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
    return s

def save_state():
    with _state_lock: _atomic_write(STATE_FILE, state)

state        = load_state()
equity_guard = EquityGuard(state.get("equity"))
discipline   = DisciplineGovernor()

# ━━ Dedup ──────────────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _make_sid(p):
    if p.get("signal_id"): return str(p["signal_id"])
    return hashlib.sha256(f"{p.get('symbol','')}-{p.get('direction','')}-{round(float(p.get('entry',0)),2)}".encode()).hexdigest()[:16]

def _is_dup(sid):
    seen = state.get("seen_signal_ids", {})
    if sid not in seen: return False
    try: return (datetime.now(timezone.utc) - datetime.fromisoformat(seen[sid])).total_seconds() < SIGNAL_DEDUP_MIN * 60
    except Exception: return False

def _mark_seen(sid):
    seen = state.setdefault("seen_signal_ids", {})
    seen[sid] = datetime.now(timezone.utc).isoformat()
    cut = datetime.now(timezone.utc) - timedelta(minutes=SIGNAL_DEDUP_MIN)
    state["seen_signal_ids"] = {k: v for k, v in seen.items() if datetime.fromisoformat(v) > cut}

# ━━ Executor client ───────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [HYGIENE 08-01] dead XTBClient class removed (never instantiated since the
# ICMarketsClient migration). XTB_USER/XTB_PASS stay required so the live
# .env contract is unchanged.
xtb = ICMarketsClient()  # IC Markets cTrader

# ━━ Spec cache ──────────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_spec_cache={}; _spec_time={}; _spec_lock=threading.Lock()
def _spec_valid(s):
    try: return float(s.get("tickSize",0))>0 and float(s.get("tickValue",0))>0
    except Exception: return False
def get_spec(sym, force=False):
    now=time.time()
    with _spec_lock:
        if not force and sym in _spec_cache and now-_spec_time.get(sym,0)<SPEC_REFRESH_HRS*3600 and _spec_valid(_spec_cache[sym]): return _spec_cache[sym]
    try:
        spec=xtb.fetch_symbol_spec(sym)
        if _spec_valid(spec):
            spec["_source"]="live"
            with _spec_lock: _spec_cache[sym]=spec; _spec_time[sym]=time.time()
            return spec
    except Exception as e: log.error(f"[SPEC] {sym}: {e}")
    with _spec_lock:
        if sym in _spec_cache and _spec_valid(_spec_cache[sym]): return _spec_cache[sym]
    return SAFE_SPECS.get(sym, {})

def calc_lot(sym, entry, sl, balance, risk_pct):
    sl_dist=abs(entry-sl)
    if sl_dist<=0: return 0.01,""
    spec=get_spec(sym); ts=float(spec.get("tickSize",0)); tv=float(spec.get("tickValue",0))
    lot_min=float(spec.get("lotMin",0.01)); lot_max=float(spec.get("lotMax",50.0)); lot_step=float(spec.get("lotStep",0.01))
    if ts<=0 or tv<=0: return 0.01,""
    risk_amt=balance*risk_pct; vpu=tv/ts; raw=risk_amt/(sl_dist*vpu)
    si=round(lot_step*1_000_000); ri=round(raw*1_000_000)
    lot=round(round(ri/si)*si/1_000_000,6); lot=round(max(lot_min,min(lot,lot_max)),2)
    return lot,""

# ━━ Telegram ────────────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def send_telegram(text):
    text = "\U0001F539 <b>[V7-DEMO]</b>\n" + text   # tag every v7 msg (demo acct 52834417)
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",json={"chat_id":TELEGRAM_CHAT_ID,"text":text,"parse_mode":"HTML"},timeout=8)
    except Exception as e: log.error(f"[TG] {e}")

# ━━ News ────────────────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_news_cache=[]; _news_t=0.0
def fetch_news():
    global _news_cache,_news_t
    if time.time()-_news_t<600: return _news_cache
    try:
        r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=5)
        if r.status_code==200: _news_cache=[e for e in r.json() if e.get("impact","").lower()=="high"]; _news_t=time.time()
    except Exception as e: log.warning(f"[NEWS] {e}")
    return _news_cache

def is_news_blocking():
    events=fetch_news(); now=datetime.now(timezone.utc); closest=9999
    for ev in events:
        try:
            t=datetime.fromisoformat(ev["date"].replace("Z","+00:00")); diff=abs((t-now).total_seconds()); mins=int(diff/60)
            if mins<closest: closest=mins
            _cur=ev.get("currency","").upper()
            # metals/indices/crypto get whipsawed by ANY high-impact news, not just their own currency.
            # Block within 30min on ANY high-impact event; within 45min for the major currencies.
            if diff<=1800:
                return True,f"News in {mins}min: {ev.get('title')} [{_cur}]",mins
            if diff<=2700 and _cur in ("USD","EUR","JPY","GBP","CAD","AUD","XAU","XAG","BTC"):
                return True,f"News in {mins}min: {ev.get('title')} [{_cur}]",mins
        except Exception: continue
    return False,"clear",closest if closest<9999 else None

# ━━ Background threads ──────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_shutdown = threading.Event()

def _keepalive():
    while not _shutdown.is_set():
        _shutdown.wait(90)
        if _shutdown.is_set(): break
        try: xtb.ping()
        except Exception as e:
            log.warning(f"[KA] {e}")
            try: xtb.ensure_connected()
            except Exception: pass

_mon_cycle=0
_MON_HEARTBEAT_EVERY=5  # ~5min at 60s/cycle
def _monitor():
    mon_lock = threading.Lock()
    while not _shutdown.is_set():
        _shutdown.wait(60)
        if _shutdown.is_set(): continue
        global _mon_cycle
        _mon_cycle += 1
        if _mon_cycle % _MON_HEARTBEAT_EVERY == 0:
            log.info(f"[MON] alive — {sum(1 for _ in all_open_trades())} open trades")
        # ── [SLOT-RECON]: catch timeout-orphans — broker positions v7 isn't tracking ──
        try:
            import requests as _rq2
            _b2=os.getenv("EXECUTOR_URL","").replace("/execute","")
            _pl=_rq2.get(_b2+"/positions",timeout=5).json().get("positions",[])
            _tracked_tix={t.get("order_id") for _,t in all_open_trades()}
            for _bp in _pl:
                _tk=_bp.get("ticket"); _cm=_bp.get("comment","") or ""
                if _tk in _tracked_tix: continue          # already managed
                if not _cm.startswith("BS_"): continue    # not one of ours
                _osym=_bp.get("symbol",""); _oac=asset_class(_osym)
                _slot_free=not any(_a==_oac for _a,_ in all_open_trades())
                if _slot_free:
                    _odir=_bp.get("type","")
                    _oentry=float(_bp.get("price_open",0) or 0)
                    set_open_trade(_oac,{"order_id":_tk,"symbol":_osym,"direction":_odir,
                        "volume":float(_bp.get("volume",0) or 0),"entry":_oentry,
                        "sl":float(_bp.get("sl",0) or 0),"raw_sl":float(_bp.get("sl",0) or 0),
                        "tp":float(_bp.get("tp",0) or 0),"signal_id":f"ADOPTED_{_tk}",
                        "comment":_cm,"cluster_key":"adopted","opened_at":datetime.now(timezone.utc).isoformat(),
                        "asset_class":_oac,"adopted":True})
                    save_state()
                    log.warning(f"[SLOT-RECON] ADOPTED orphan {_tk} {_osym} {_odir} into {_oac} slot")
                    send_telegram(f"♻️ <b>Orphan adopted</b>\n{_osym} {_odir} ticket <code>{_tk}</code>\nWas untracked (timeout-lie). Now managed — partial/BE active.")
                else:
                    log.error(f"[SLOT-RECON] CONFLICT orphan {_tk} {_osym}, {_oac} slot busy")
                    send_telegram(f"⚠️ <b>Untracked position</b>\n{_osym} ticket <code>{_tk}</code>\n{_oac} slot busy — manual review (close or wait).")
        except Exception as _re2:
            log.warning(f"[SLOT-RECON] sweep failed: {_re2}")
        if not any_open_trade(): continue
        try:
            with mon_lock:
                # Fetch MT5 positions ONCE for all slots
                import requests as _rq
                from datetime import datetime as _dt, timezone as _tz
                _base=os.getenv("EXECUTOR_URL","").replace("/execute","")
                try:
                    _r=_rq.get(_base+"/positions",timeout=5)
                    _poslist=_r.json().get("positions",[])
                    _tickets={p.get("ticket") for p in _poslist}
                    _posmap={p.get("ticket"):p for p in _poslist}
                except Exception as _e:
                    log.warning(f"[MON] MT5 positions check failed: {_e}"); continue
                # Snapshot to avoid mutation during iteration
                open_snapshot = list(all_open_trades())
                _hr_cached = None  # /history fetched lazily, only if at least one slot closed
                for ac, tracked in open_snapshot:
                    oid=tracked.get("order_id"); comment=tracked.get("comment","")
                    if oid in _tickets:
                        # ── Phase 5: at +1R → partial-close 50%, then move runner SL to BE (once each, fail-safe) ──
                        try:
                            _p=_posmap.get(oid) or {}
                            _entry=float(tracked.get("entry") or 0)
                            _dir=tracked.get("direction","")
                            _isl=float(tracked.get("sl") or 0)
                            _cur_sl=float(_p.get("sl") or 0)
                            _cur_px=float(_p.get("price_current") or 0)
                            # ── [MAE-LIVE]: accumulate worst/best excursion each cycle ──
                            try:
                                if _cur_px>0 and _entry>0:
                                    _pdir=tracked.get("direction","")
                                    if _pdir=="BUY":
                                        _adv=_entry-_cur_px; _fav=_cur_px-_entry
                                    else:
                                        _adv=_cur_px-_entry; _fav=_entry-_cur_px
                                    _cmae=max(0.0,_adv); _cmfe=max(0.0,_fav)
                                    if _cmae>float(tracked.get("mae") or 0):
                                        tracked["mae"]=round(_cmae,5)
                                    if _cmfe>float(tracked.get("mfe") or 0):
                                        tracked["mfe"]=round(_cmfe,5)
                                    set_open_trade(ac, tracked)
                                    save_state()  # [MAE-LIVE-PERSIST] flush so it survives restart
                            except Exception: pass
                            _pos_vol=float(_p.get("volume") or 0)
                            _risk=abs(_entry-_isl)
                            _moved_right=(_dir=="BUY" and _cur_px>_entry) or (_dir=="SELL" and _cur_px<_entry)
                            _prog=abs(_cur_px-_entry) if _cur_px else 0
                            _at_1r=(_entry>0 and _risk>0 and _cur_px>0 and _moved_right and _prog>=_risk)
                            if False and _at_1r and not tracked.get("partial_done") and _pos_vol>0:  # [BE-ONLY] partial disabled at 0.01 lots
                                _half=round(_pos_vol*0.5, 2)
                                if _half>=0.01 and _half<_pos_vol:
                                    _pres=xtb.close_trade(oid, tracked.get("symbol"), _half, _dir)
                                    if _pres.get("status"):
                                        tracked["partial_done"]=True; set_open_trade(ac, tracked)
                                        log.info(f"[PARTIAL] {tracked.get('symbol')} {oid} +1R -> closed {_half}/{_pos_vol}")
                                        send_telegram(f"\U0001F4B0 <b>Partial close</b>\n{tracked.get('symbol')} {oid}\nClosed {_half} (50%) at +1R")
                                    else:
                                        log.warning(f"[PARTIAL] close failed {oid}: {_pres.get('errorDescr') or _pres.get('raw')}")
                                else:
                                    log.info(f"[PARTIAL] skip {oid}: half={_half} vs vol={_pos_vol}")
                            if _at_1r and not tracked.get("be_done"):
                                _buf=_risk*0.05
                                _be=round_px(tracked.get("symbol",""), _entry+_buf if _dir=="BUY" else _entry-_buf)  # [F3] was round(,2): EURUSD BE landed at 1.17 instead of 1.17345
                                _tighter=(_dir=="BUY" and _be>_cur_sl) or (_dir=="SELL" and _be<_cur_sl)
                                if _tighter:
                                    _mres=xtb.modify_sl(oid, _be, float(_p.get("tp") or tracked.get("tp") or 0))
                                    if _mres.get("status"):
                                        tracked["be_done"]=True; set_open_trade(ac, tracked)
                                        log.info(f"[BE] {tracked.get('symbol')} {oid} +1R -> SL to BE {_be}")
                                        send_telegram(f"\U0001F6E1\uFE0F <b>Breakeven</b>\n{tracked.get('symbol')} {oid}\nSL \u2192 {_be}")
                                    else:
                                        log.warning(f"[BE] modify failed {oid}: {_mres.get('errorDescr') or _mres.get('raw')}")
                        except Exception as _bee:
                            log.error(f"[MGMT] error {oid}: {_bee}")
                        continue  # still open in MT5
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
                    # ── [MAE-LIVE]: use excursion accumulated by the monitor loop ──
                    _mae=tracked.get("mae"); _mfe=tracked.get("mfe")
                    log.info(f"[MAE-LIVE] {tracked.get('symbol')} {tracked.get('order_id')} mae={_mae} mfe={_mfe}")
                    mem_close(tracked.get("signal_id","?"), float(cp), profit, swap, comm, hold_time_seconds=_hold, mae=_mae, mfe=_mfe,
                              be_done=bool(tracked.get("be_done")), partial_done=bool(tracked.get("partial_done")))
                    equity_guard.record_trade(net, tracked["symbol"])
                    state["equity"]=equity_guard.to_dict(); save_state()
                    bal=xtb.get_balance(); equity_guard.update_balance(bal)

                    send_telegram(
                        f"{emoji} <b>Trade closed — {tag}</b>\n"
                        f"Symbol: {tracked['symbol']} {tracked['direction']}\n"
                        f"Close: <code>{cp}</code>  Entry: <code>{tracked.get('entry','?')}</code>\n"
                        f"Net: <code>{net:+.2f}</code>  Streak: {state['consecutive_losses']}\n"
                        f"Record: W{state['total_wins']} / L{state['total_losses']}\n"
                        f"Cluster: <code>{tracked.get('cluster_key','?')}</code>\n"
                        f"Balance: <code>${bal:.2f}</code>"
                    )
                    guard=equity_guard.check(bal,state.get("consecutive_losses",0))
                    if state["consecutive_losses"]>=3 or not guard.allowed:
                        state["paused"]=True; save_state()
                        send_telegram(f"⛔ <b>BOT PAUSED</b>\n{equity_guard.status_summary(bal)}")
        except Exception as e: log.error(f"[MON] {e}",exc_info=True)

def _spec_worker():
    syms=list(dict.fromkeys(SYMBOL_MAP.values()))
    while not _shutdown.is_set():
        for sym in syms:
            if _shutdown.is_set(): break
            try: get_spec(sym,force=True)
            except Exception as e: log.error(f"[SPEC] {sym}: {e}")
            _shutdown.wait(2)
        _shutdown.wait(SPEC_REFRESH_HRS*3600)

def _calibration_worker():
    _shutdown.wait(3600)
    while not _shutdown.is_set():
        try:
            bal=xtb.get_balance()
        except Exception: bal=1000.0
        guard=equity_guard.check(bal,state.get("consecutive_losses",0))
        daily_dd=max(0, -equity_guard.eq.day_pnl) / max(equity_guard.eq.day_open_balance,1)
        result=recalibrate(daily_dd_pct=daily_dd)
        send_telegram(format_calibration_telegram(result))
        _shutdown.wait(CALIBRATION_HRS*3600)

# ━━ Middleware ──────────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.before_request
def _guard():
    if request.path=="/health": return
    ip=(request.headers.get("X-Forwarded-For",request.remote_addr) or "").split(",")[0].strip()
    if not _ip_ok(ip): abort(403)
    if not _rate_ok(ip): abort(429)

# ━━ SIGNAL HANDLER ──────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def handle_signal(payload: dict, raw_body: bytes = b"") -> dict:

    # Auto-inject secret for trusted Pine systems (BEFORE secret check)
    if not payload.get("secret"):
        if payload.get("system") in ("BSv16","BSv17","BSv18","BSv11") or payload.get("version","").startswith("v9") or payload.get("bot","").startswith("BS_"):
            payload["secret"] = WEBHOOK_SECRET

    if payload.get("secret") != WEBHOOK_SECRET: return {"status":"error","msg":"unauthorized"}

    # ═══ Step 1: Record ALL signals (BEFORE field validation) ═══
    try: mem.record_signal(payload)
    except Exception as e: log.warning(f"[MEM] record failed: {e}")

    if TV_HMAC_SECRET:
        tok=request.headers.get("X-Webhook-Token","")
        exp=hmac.new(TV_HMAC_SECRET.encode(),raw_body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(exp,tok): return {"status":"error","msg":"invalid HMAC"}

    # [HYGIENE 08-01] redact the secret before logging — the raw payload was
    # logged AFTER secret injection, so the webhook secret landed in bot.log
    # and journalctl (Iron Rule 8). One committed journalctl dump leaked it;
    # ROTATE WEBHOOK_SECRET after deploying this.
    log.info(f"[WEBHOOK RAW] { {k: ('***' if k == 'secret' else v) for k, v in payload.items()} }")

    # ── Patch C: filter v17 ULTIMATE chart-annotation alerts ─────────────
    # v17 sends INFO/WARN (BOS, sweeps, inducements) and SCALP/MICRO templates
    # which have inverted SL/TP. Only v9.x LITE trade signals are actionable.
    _sig = str(payload.get("signal","")).upper().strip()
    _typ = str(payload.get("type","")).upper().strip()
    _sys = str(payload.get("system","")).upper().strip()
    _grade = str(payload.get("grade","")).upper().strip()  # [F5 2026-07-02] defined for ALL systems — was only set in the BSv17/18 branch, so the signal_bus emit NameError'd (silently) for every v9 signal and the shadow-vote pipeline never saw them
    if _sig in ("INFO","WARN") or _typ in ("SCALP","MICRO","BOS_DOWN","BOS_UP",
            "ALL_TF_BULL","ALL_TF_BEAR","LIQ_SWEEP_BULL","LIQ_SWEEP_BEAR",
            "BULL_INDUCEMENT","BEAR_INDUCEMENT"):
        log.info(f"[v17-NOISE] dropped: system={_sys} signal={_sig} type={_typ}")
        return {"status":"ignored","msg":"v17 chart annotation, not a trade signal"}
    if _sys in ("BSV17", "BSV18"):
        # ── Patch H: v17/v18 quality gate (belt + suspenders to Pine filtering)
        _grade = str(payload.get("grade","")).upper().strip()
        _v4rr  = bool(payload.get("v4_rr", False))
        if _typ != "SMART_SCALP":
            log.info(f"[v17v18-NOISE] dropped — type={_typ} not actionable")
            return {"status":"ignored","msg":f"{_sys} non-trade type"}
        if _grade not in ("A","A+","B"):
            log.info(f"[v17v18-FILTER] dropped grade-{_grade} signal from {_sys}")
            return {"status":"ignored","msg":f"{_sys} grade {_grade} below threshold"}
        if not _v4rr:
            log.info(f"[v17v18-FILTER] dropped — v4_rr=False from {_sys}")
            return {"status":"ignored","msg":f"{_sys} v4_rr veto failed"}
        # [HYGIENE 08-01] was an obfuscated chr(39)... key ('symbol' WITH quote
        # chars) from a patch-script quoting accident — always logged symbol=''
        log.info(f"[v17v18-ACCEPT] {_sys} grade={_grade} symbol={payload.get('symbol','')}")
        try:
            _tg_sym = payload.get("symbol","").split(":")[-1]
            _tg_dir = (payload.get("direction") or payload.get("signal","")).upper()
            _tg_msg = (f"\U0001F3AF <b>v18 {_tg_dir} signal</b>\n"
                       f"<b>{_tg_sym}</b>  grade <b>{_grade}</b>\n"
                       f"Entry: <code>{payload.get('entry')}</code>\n"
                       f"SL:    <code>{payload.get('sl')}</code>\n"
                       f"TP:    <code>{payload.get('tp')}</code>")
            send_telegram(_tg_msg)
        except Exception as _e:
            log.warning(f"[v17v18-TG] Telegram notify failed: {_e}")
        # falls through to normal processing

    sym_raw=payload.get("symbol","").upper().strip().split(":")[-1]  # Strip exchange prefix
    symbol=SYMBOL_MAP.get(sym_raw,sym_raw)

    # Support both LITE v7 ("direction") and ULTIMATE v16 ("signal") formats
    direction=payload.get("direction","").upper().strip()
    if not direction:
        direction=payload.get("signal","").upper().strip()
    if not direction:
        direction=payload.get("action","").upper().strip()  # v9.5 fallback

    # (secret already injected at top)

    try:
        entry=float(payload["entry"])
        raw_sl=float(payload.get("sl") or 0)
        # Support tp, tp1, tp2 — use tp2 for best R:R
        # [TP-FLOOR] prefer tp1 if >=1.0R, else step up to tp2, else fallback (line ~774 covers tp<=0)
        _tp1=float(payload.get("tp1") or 0); _tp2=float(payload.get("tp2") or 0)
        _slv=float(payload.get("sl") or 0)
        _riskd=abs(entry-_slv) if _slv>0 else 0
        if _tp1>0 and _riskd>0 and abs(_tp1-entry)>=_riskd*1.0:
            tp=_tp1
        elif _tp2>0:
            tp=_tp2
        else:
            tp=float(_tp1 or payload.get("tp") or 0)
        # ── Patch G: entry-price sanity check ────────────────────────────
        # Reject signals where entry price is impossible for the symbol.
        # Catches "Pine template applied to wrong chart" bugs (e.g. Gold
        # alert template firing on GBPUSD chart with forex-priced entry).
        _PRICE_RANGES = {
            "GOLD":     (1000, 10000),
            "SILVER":   (5, 500),
            "BITCOIN":  (1000, 1000000),
            "ETHEREUM": (50, 50000),
            "LITECOIN": (10, 10000),
            "RIPPLE":   (0.05, 100),
            "USDJPY":   (50, 500),
            "EURUSD":   (0.5, 3.0),
            "GBPUSD":   (0.5, 3.0),
            "AUDUSD":   (0.3, 2.0),
            "NZDUSD":   (0.3, 2.0),
            "USDCAD":   (0.7, 2.5),
            "USDCHF":   (0.5, 2.0),
            "US30":  (20000, 60000),
            "USTEC": (10000, 50000),
        }
        _lo, _hi = _PRICE_RANGES.get(symbol, (None, None))
        if _lo is not None and not (_lo <= entry <= _hi):
            log.warning(f"[GATE-PRICE] {symbol} entry={entry} outside expected range ({_lo}-{_hi}) - likely Pine template applied to wrong chart. REJECTING.")
            return {"status":"rejected","msg":f"{symbol} entry price {entry} outside expected range - Pine alert likely on wrong chart"}
        # ── DIRECTION SANITY: auto-flip if Pine sent SL/TP on wrong side ──
        if direction == "BUY" and raw_sl > 0 and tp > 0:
            if raw_sl > entry or tp < entry:
                log.warning(f"[DIR-FLIP] {symbol} BUY had inverted SL/TP — Pine bug. raw_sl={raw_sl} tp={tp} entry={entry}. REJECTING.")
                return {"status":"rejected","msg":"BUY signal had SL above entry or TP below entry — Pine script bug"}
        if direction == "SELL" and raw_sl > 0 and tp > 0:
            if raw_sl < entry or tp > entry:
                log.warning(f"[DIR-FLIP] {symbol} SELL had inverted SL/TP — Pine bug. raw_sl={raw_sl} tp={tp} entry={entry}. REJECTING.")
                return {"status":"rejected","msg":"SELL signal had SL below entry or TP above entry — Pine script bug"}

        # If SL=0 from TradingView: REJECT. [F7 2026-07-02]
        # Old behaviour invented a 1.5% (metals) / 3% (other) stop and then
        # risk-sized on the invention — a fabricated plan, not a trade plan.
        # v18 Pine always sends a structural SL; a signal without one is noise.
        if raw_sl <= 0 or raw_sl is None:
            log.warning(f"[GATE-SL] {symbol} {direction}: no SL in payload — REJECTED (auto-SL fabrication removed 07-02)")
            return {"status":"rejected","msg":"signal carries no SL — auto-SL fabrication removed (F7)"}

        if tp <= 0 or tp is None:
            # TP = 3x risk
            risk = abs(entry - raw_sl)
            tp = entry + risk * 3.0 if direction=="BUY" else entry - risk * 3.0
            log.info(f"[AUTO-TP] {symbol} {direction}: no TP from TV, using {tp:.4f}")
        atr       =float(payload["atr"])        if payload.get("atr")        else None
        if atr is None:
            atr = fetch_atr(symbol)  # Phase 1: live ATR when Pine sends none
        swing_low =float(payload["swing_low"])  if payload.get("swing_low")  else None
        swing_hi  =float(payload["swing_high"]) if payload.get("swing_high") else None
        htf_trend = payload.get("htf_trend") or payload.get("trend")  # Patch L: v18 sends 'trend' not 'htf_trend'
        # ── Phase 2 (log-only): compute + journal Market Flow Vector (cannot affect trade) ──
        try:
            _fv = compute_flow_vector(payload)
            log.info(f"[FLOW] {sym_raw} {direction}: vector={_fv['vector']} (dxy={_fv['dxy_dir']} yld={_fv['yield_dir']} vol={_fv['vol_regime']} adx={_fv['adx']:.0f})")
            _fp = os.path.join(os.path.dirname(os.path.abspath(__file__)),"learning","flow_vector.jsonl")
            with open(_fp,"a") as _ff:
                _ff.write(json.dumps({**_fv,"signal_id":payload.get("signal_id"),"symbol":sym_raw,"direction":direction,"ts":datetime.now(timezone.utc).isoformat()})+"\n")
        except Exception as _e:
            log.warning(f"[FLOW] compute failed: {_e}")
        # Patch L: v18 score is 0-7 (vetoes passed), v9.7 score is 0-9. Normalize to 0-100 for filter blend.
        _sys_for_score = str(payload.get("system","")).upper().strip()
        if _sys_for_score in ("BSV17","BSV18"):
            # v18: skip pine_score blend - grade gate (Patch H) already validated quality
            pine_score = None
        else:
            pine_score= int(payload["pine_score"])  if payload.get("pine_score") else (int(payload["score"]) if payload.get("score") else None)
        # ── v9.7 / TASK 8B: breakout probability fields ─────────────────────
        breakout_prob_v=None
        try:
            if payload.get("breakout_prob") is not None:
                breakout_prob_v=int(float(payload["breakout_prob"]))
        except (TypeError, ValueError): pass
        breakout_strength_v=str(payload["breakout_strength"]) if payload.get("breakout_strength") else None
        breakout_dir_v=str(payload["breakout_dir"]) if payload.get("breakout_dir") else None
        # Signal age in seconds (Pine 'time' field is ms since epoch)
        signal_age_seconds_v=None
        try:
            if payload.get("time"):
                from datetime import datetime as _sdt, timezone as _stz
                _sig_t = float(payload["time"])
                if _sig_t > 1e11:  # ms → s
                    _sig_t = _sig_t / 1000.0
                signal_age_seconds_v = max(0.0, (_sdt.now(_stz.utc).timestamp() - _sig_t))
        except (TypeError, ValueError): pass
        atr_pct   =float(payload["atr_pct"])    if payload.get("atr_pct")    else None
        atr_vs_avg=float(payload["atr_vs_avg"]) if payload.get("atr_vs_avg") else {"HIGH":1.5,"MEDIUM":1.0,"LOW":0.5}.get(str(payload.get("vol_regime","")).upper().strip(), None)
        adx       =float(payload["adx"])        if payload.get("adx")        else None
        bb_width  =float(payload["bb_width"])   if payload.get("bb_width")   else None
    except (KeyError,TypeError,ValueError) as e: return {"status":"error","msg":f"field: {e}"}

    if symbol not in ALLOWED_SYMBOLS: return {"status":"error","msg":f"unsupported: {sym_raw}"}
    # ── [ASSET-GATE 08-01] flagged, OFF by default — see utils/asset_gate.py ──
    from utils.asset_gate import asset_gate_check
    _ag_block, _ag_mult = asset_gate_check(symbol)
    if _ag_block:
        log.info(f"[ASSET-GATE] {symbol} {direction} dropped — symbol benched in .env")
        return {"status":"skipped","msg":f"{symbol} disabled by asset gate"}
    if direction not in ("BUY","SELL"): return {"status":"error","msg":"BUY or SELL only"}
    if entry<=0 or raw_sl<=0 or tp<=0: return {"status":"error","msg":"invalid prices"}

    sid=_make_sid(payload)
    if _is_dup(sid): return {"status":"skipped","msg":"duplicate"}
    _mark_seen(sid); save_state()

    if state.get("paused") or state.get("consecutive_losses",0)>=3:
        log.info(f"[GATE-PAUSED] {symbol} {direction} dropped — paused={state.get('paused')} losses={state.get('consecutive_losses',0)}")
        return {"status":"paused","msg":"paused — POST /reset"}
    # TASK 8: per-asset-class slot check (allow concurrent trades across classes)
    _ac = asset_class(symbol)
    _slot_trade = get_open_trade(_ac)
    if _slot_trade:
        log.info(f"[GATE-SLOT] {symbol} {direction} dropped — {_ac} slot held by {_slot_trade.get('symbol')} ticket {_slot_trade.get('order_id')}")
        return {"status":"skipped","msg":f"{_ac} slot already open"}

    # GATE-MARGIN (fail-closed): no balance or below floor -> skip BEFORE score_signal ($0 AI)
    try:
        _bal_gate = xtb.get_balance()
    except Exception:
        _bal_gate = None
    MARGIN_FLOOR = 500.0   # hard floor in account currency; tune as needed
    if _bal_gate is None or _bal_gate < MARGIN_FLOOR:
        log.info(f"[GATE-MARGIN] {symbol} {direction} dropped — balance={_bal_gate} floor={MARGIN_FLOOR}")
        return {"status":"skipped","msg":"margin floor / balance unreadable"}

    # ── PRIORITY 1: Equity Guard ──────────────────────────────────────────────
    try: balance=xtb.get_balance()
    except Exception: balance=1000.0
    guard=equity_guard.check(balance,state.get("consecutive_losses",0))
    if not guard.allowed:
        send_telegram(f"⛔ <b>Equity Guard</b>\n{guard.block_reason}\nTier: {guard.tier_hit}")
        return {"status":"blocked","msg":guard.block_reason}

    # ── PRIORITY 2: News filter ───────────────────────────────────────────────
    news_block,news_reason,news_mins=is_news_blocking()
    if news_block:
        send_telegram(f"⛔ <b>News block</b>\n{symbol} {direction}\n{news_reason}")
        return {"status":"blocked","msg":news_reason}

    # ── PRIORITY 3: Regime detection ──────────────────────────────────────────
    regime:RegimeResult=detect_regime(
        atr_pct=atr_pct,atr_vs_avg=atr_vs_avg,adx=adx,bb_width=bb_width,htf_trend=htf_trend)

    # ── PRIORITY 4: Discipline — EV gate + regime position scale ─────────────
    # (Cluster lookup needs session which comes from ai_filter — do a quick session check)
    now_utc=datetime.now(timezone.utc); utc_hour=now_utc.hour
    # [F9 2026-07-02] DST-aware session (was a static-UTC table, wrong all summer)
    from filters.ai_filter import _get_session as _sess_dst
    session_now=_sess_dst(utc_hour)

    cluster:ClusterLookup=lookup_cluster(symbol,session_now,regime.regime,atr_vs_avg)
    ev=cluster.ev

    daily_dd=max(0,-equity_guard.eq.day_pnl)/max(equity_guard.eq.day_open_balance,1)
    disc_result:DisciplineResult=discipline.pre_trade_check(ev,regime.confidence,daily_dd)

    if not disc_result.ev_gate_passed:
        send_telegram(
            f"📉 <b>EV gate blocked</b>\n{symbol} {direction}\n"
            f"Cluster: <code>{cluster.cluster_key}</code>\n"
            f"{disc_result.ev_gate_reason}\n"
            f"Cluster n={cluster.stats.n_trades if cluster.stats else 0} trusted={cluster.trusted}"
        )
        return {"status":"blocked","msg":disc_result.ev_gate_reason,"ev":ev,"cluster":cluster.cluster_key}

    # ── PRIORITY 5: AI filter (learned weights, regime-aware threshold) ───────
    filt:FilterResult=score_signal(
        symbol=symbol,direction=direction,entry=entry,sl_price=raw_sl,tp=tp,
        regime_result=regime,atr=atr,htf_trend=htf_trend,
        news_minutes=news_mins,custom_score=pine_score,signal_id=sid,
    )
    if not filt.passed:
        send_telegram(
            f"🟡 <b>AI filter blocked</b>\n{symbol} {direction}\n"
            f"Score: {filt.score}/{filt.threshold} | {filt.regime}\n{filt.reason}"
        )
        return {"status":"filtered","msg":filt.reason,"score":filt.score}

    # ── [AI-SHADOW]: emit to vote bus (non-blocking; scored, NEVER enforced) ──
    try:
        from learning.signal_bus import emit_signal
        _cs = cluster.stats
        emit_signal(sid, {
            "symbol": symbol, "direction": direction, "grade": _grade, "atr_vs_avg": atr_vs_avg,
            "entry": entry, "sl": raw_sl, "tp": tp,
            "htf_trend": htf_trend, "atr": atr,
            "regime": regime.regime if regime else None,
            "session": getattr(filt, "session", None),
            "cluster": cluster.cluster_key,
            "cluster_n": _cs.n_trades if _cs else 0,
            "cluster_wr": _cs.win_rate if _cs else None,
            "cluster_pf": _cs.expectancy if _cs else None,
            "ai_score": filt.score,
        })
    except Exception:
        pass

    # ── PRIORITY 6: Institutional SL engine ───────────────────────────────────
    sl_result:SLResult=calculate_institutional_sl(
        symbol=symbol,direction=direction,entry=entry,raw_sl=raw_sl,
        atr=atr,swing_low=swing_low,swing_high=swing_hi)

    # ── v9.x TRUST MODE: bypass institutional widening for high-score Pine signals ──
    # ── Patch M1: trust mode extended to BSv17/BSv18 + v9.x (score-based) ──
    _sys_trust = str(payload.get("system","")).upper().strip()
    trust_pine_sl = raw_sl > 0 and (
        _sys_trust in ("BSV17","BSV18","BSV11") or
        (payload.get("version","").startswith("v9") and pine_score is not None and pine_score >= 7)
    )
    if trust_pine_sl:
        sl_dist_pct = abs(entry - raw_sl) / entry
        # v18 Pine SL can be very tight scalp. Allow 0.02% min for v18, 0.05% for v9.x. Max 8% both.
        _sl_min = 0.0002 if _sys_trust in ("BSV17","BSV18") else 0.0005
        if sl_dist_pct < _sl_min or sl_dist_pct > 0.08:
            send_telegram(f"⛔ <b>SL sanity</b>\n{symbol} trust mode\nSL dist {sl_dist_pct*100:.2f}% out of [{_sl_min*100:.2f}%, 8%]")
            return {"status":"rejected","msg":f"trust mode SL distance {sl_dist_pct*100:.2f}% out of range"}
        # ── Patch P0: ATR-floor the trusted Pine stop (2026-06-18) ──
        # Trust mode accepted Pine's raw SL verbatim -> noise-tight stops
        # (gold 2.5pt deaths). Floor it at the engine's computed min distance.
        # If we widen the stop, widen TP by the same ratio so Pine's R:R holds
        # (Patch D's TP-rebuild is skipped in trust mode).
        # [F9 2026-07-10] scalp-aware floor: the legacy percent floor (~1.5%)
        # was 4-5x live ATR and starved the v7 A/B arm (rejected ~every v18
        # scalp stop). Pine v18.6 already floors SL at 0.7 ATR at source --
        # mirror that here: 1.2x live M15 ATR when ATR is known, else legacy.
        engine_floor = (1.2 * atr) if (atr is not None and atr > 0) else sl_result.sl_distance
        pine_dist    = abs(entry - raw_sl)
        if pine_dist < engine_floor:
            # [F2 2026-07-02] WIDEN-RATIO GUARD: if the noise floor is >1.6x Pine's
            # stop, the setup Pine graded no longer exists at this stop — widening
            # collapsed R:R (live 0.63R trades). Reject instead of trading it.
            if engine_floor > pine_dist * 1.6:
                log.info(f"[SL] widen-reject: {symbol} Pine dist={pine_dist:.5g} floor={engine_floor:.5g} ratio={engine_floor/pine_dist:.2f}x > 1.6x")
                send_telegram(f"⛔ <b>SL floor reject</b>\n{symbol} {direction}\nPine SL dist {pine_dist:.5g} vs floor {engine_floor:.5g} (&gt;1.6×)\nSetup invalidated at survivable stop — skipped.")
                return {"status":"rejected","msg":f"SL floor {engine_floor:.5g} exceeds 1.6x Pine stop {pine_dist:.5g} — R:R collapsed"}
            inst_sl = round_px(symbol, entry - engine_floor if direction=="BUY" else entry + engine_floor)  # [F3] symbol digits
            # TP-INFLATION REMOVED 2026-06-25: SL adaptive, TP stays as Pine sent it.
            log.info(f"[SL] trust+floor: {symbol} Pine dist={pine_dist:.2f} < floor={engine_floor:.2f} -> widened SL={inst_sl} (TP unchanged={tp})")
        else:
            inst_sl = raw_sl
            log.info(f"[SL] trust mode: sys={_sys_trust or 'v9'} SL={raw_sl} dist={sl_dist_pct*100:.2f}%")
    elif regime.atr_multiplier != 1.2:
        pad_adj=(regime.atr_multiplier-1.2)*sl_result.atr_used
        inst_sl=round_px(symbol, sl_result.sl_price-pad_adj if direction=="BUY" else sl_result.sl_price+pad_adj)  # [F3] symbol digits
    else:
        inst_sl=sl_result.sl_price

    if not sl_result.within_limits and not trust_pine_sl:
        send_telegram(f"⛔ <b>SL rejected</b>\n{symbol}\n{sl_result.rejection_reason}")
        return {"status":"rejected","msg":sl_result.rejection_reason}

    # ── Patch D: TP scaling — preserve Pine's R:R when bot widens SL ─────────
    # Pine sends entry/SL/TP at fixed ratio (slMult vs tp1Mult, e.g. 1.5 vs 3.0 = 1:2 R:R).
    # When the institutional engine widens SL (anti stop-hunt), TP must widen
    # proportionally or R:R collapses. We rebuild TP from the original Pine ratio.
    pine_sl_dist = abs(entry - raw_sl)
    new_sl_dist  = abs(entry - inst_sl)
    if (not trust_pine_sl) and pine_sl_dist > 0 and new_sl_dist > pine_sl_dist * 1.05:
        pine_tp_dist = abs(tp - entry)
        pine_rr      = pine_tp_dist / pine_sl_dist if pine_sl_dist > 0 else 0
        if pine_rr >= 1.5:
            # TP-INFLATION REMOVED 2026-06-25: do NOT rebuild TP from ratio.
            # SL widened for noise-survival; TP stays structural (as Pine sent).
            # Real R:R now measured at validate_rr below — sub-MIN_RR trades correctly dropped.
            log.info(f"[TP-SCALE-DISABLED] {symbol} {direction}: SL widened "
                     f"{pine_sl_dist:.4f}→{new_sl_dist:.4f} ({new_sl_dist/pine_sl_dist:.1f}x), "
                     f"TP held at {tp:.4f} (was scaling to preserve {pine_rr:.2f}:1)")

    # ── PRIORITY 7: R:R validation ────────────────────────────────────────────
    rr,rr_err=validate_rr(entry,inst_sl,tp,direction,MIN_RR)
    if rr_err:
        send_telegram(f"⛔ <b>R:R rejected</b>\n{rr_err}")
        return {"status":"rejected","msg":rr_err}

    # ── PRIORITY 8: Final lot size (equity risk × regime scale × discipline pos scale) ─
    _cn = cluster.stats.n_trades if cluster.stats else 0
    _cluster_scale = 0.25 if _cn < 10 else 0.50 if _cn < 30 else 1.00
    effective_risk=guard.risk_pct * regime.risk_scale * disc_result.position_scale * _cluster_scale
    effective_risk=max(0.003, min(effective_risk, 0.01))
    # [ASSET-GATE 08-01] size multiplier applied AFTER the 0.3% floor so a
    # 0.5x gold dial actually halves risk (the floor otherwise re-inflates it).
    # _ag_mult is 1.0 whenever ASSET_GATE_ENABLED=false (default) — inert.
    effective_risk *= _ag_mult
    log.info(f"[CLUSTER-RISK] {symbol} cluster_n={_cn} scale={_cluster_scale} -> risk={effective_risk*100:.3f}%")
    lot,_=calc_lot(symbol,entry,inst_sl,balance,effective_risk)

    # ── Execute ───────────────────────────────────────────────────────────────
    try:
        xtb.ensure_connected()
        comment=f"BS_{sid}"
        resp=xtb.open_trade(symbol,direction,lot,inst_sl,tp,comment=comment)

        if resp.get("status"):
            order_id=resp.get("returnData",{}).get("order")
            # ── Bug #1 fix: journal broker's ACTUAL filled volume + realized risk ──
            # resp carries executor result.volume (falls back to sent lot if absent).
            # realized risk inverts calc_lot: risk = vol*sl_dist*(tv/ts)/balance.
            filled_vol = lot
            realized_risk = effective_risk
            try:
                filled_vol = float(resp.get("returnData",{}).get("volume", lot) or lot)
                _spec = get_spec(symbol)
                _ts = float(_spec.get("tickSize",0)); _tv = float(_spec.get("tickValue",0))
                _sl_dist = abs(entry - inst_sl)
                if _ts>0 and _tv>0 and _sl_dist>0 and balance>0:
                    realized_risk = filled_vol * _sl_dist * (_tv/_ts) / balance
                if abs(filled_vol - lot) > 1e-9:
                    log.info(f"[JOURNAL] filled_vol={filled_vol} vs computed lot={lot}; "
                             f"realized_risk={realized_risk*100:.3f}% vs intended={effective_risk*100:.3f}%")
            except Exception as e:
                log.error(f"[JOURNAL] filled-vol calc failed, falling back to computed lot: {e}")
            _ac = asset_class(symbol)
            set_open_trade(_ac, {
                "order_id":order_id,"symbol":symbol,"direction":direction,
                "volume":filled_vol,"entry":entry,"sl":inst_sl,"raw_sl":raw_sl,"tp":tp,
                "signal_id":sid,"comment":comment,"cluster_key":cluster.cluster_key,
                "opened_at":now_utc.isoformat(),
                "asset_class":_ac,
            })
            state["equity"]=equity_guard.to_dict(); save_state()

            # ── Trade memory record ────────────────────────────────────────────
            trend_aligned=None
            if htf_trend and htf_trend!="RANGE":
                ht=htf_trend.upper()
                trend_aligned=(ht=="UP" and direction=="BUY") or (ht=="DOWN" and direction=="SELL")
            atr_ratio=abs(entry-inst_sl)/atr if atr and atr>0 else None

            mem_open(TradeRecord(
                signal_id=sid,order_id=order_id,symbol=symbol,direction=direction,
                timestamp_open=now_utc.isoformat(),entry=entry,raw_sl=raw_sl,
                inst_sl=inst_sl,tp=tp,sl_distance=abs(entry-inst_sl),
                tp_distance=abs(tp-entry),rr=rr,session=filt.session,
                utc_hour=utc_hour,day_of_week=now_utc.weekday(),
                atr=atr,atr_ratio=atr_ratio,fakeout_pad=sl_result.fakeout_pad,
                sl_method=sl_result.method,htf_trend=htf_trend,
                trend_aligned=trend_aligned,news_minutes=news_mins,
                pine_score=pine_score,ai_score=filt.score,
                score_breakdown=filt.breakdown,balance_at_open=balance,
                equity_pct=guard.equity_pct,risk_pct=realized_risk,lot=filled_vol,
                # ── TASK 8B journal fields ─────────────────────────────────
                asset_class=_ac,
                breakout_prob=breakout_prob_v,
                breakout_strength=breakout_strength_v,
                breakout_dir=breakout_dir_v,
                signal_age_bars=int(signal_age_seconds_v//900) if signal_age_seconds_v is not None else None,  # 15m bars
                regime=regime.regime if regime else None,
            ))

            sl_diff=round(abs(inst_sl-raw_sl),2)
            arrow="🟢" if direction=="BUY" else "🔴"
            ev_tag=f"${ev:+.2f}" if cluster.trusted else f"~${ev:.2f} (learning)"
            w_data=load_weights()

            send_telegram(
                f"{arrow} <b>{direction} {symbol} — OPENED</b>\n"
                f"Entry:    <code>{entry}</code>\n"
                f"SL:       <code>{inst_sl}</code>  <i>(+{sl_diff} vs retail · {sl_result.method})</i>\n"
                f"TP:       <code>{tp}</code>  R:R 1:{rr:.2f}\n"
                f"Lot:      <code>{lot}</code>  "
                f"Risk: <code>{effective_risk*100:.2f}%  ${balance*effective_risk:.2f}</code>\n"
                f"─────────────────────────\n"
                f"EV:       <code>{ev_tag}</code>  "
                f"Cluster: <code>{cluster.cluster_key}</code>\n"
                f"Cluster n: {cluster.stats.n_trades if cluster.stats else 0}  "
                f"WR: {f'{cluster.stats.win_rate:.0%}' if cluster.stats else 'learning'}\n"
                f"AI score: <code>{filt.score}/{filt.threshold}</code>  "
                f"Regime: <code>{regime.regime}</code> ({regime.confidence:.0%})\n"
                f"Pos scale:{disc_result.position_scale:.2f}× — {disc_result.position_reason[:30]}\n"
                f"Weights:  calibrated {w_data.get('updated_at','never')[:10]}\n"
                f"Equity:   <code>${balance:.2f}</code>  "
                f"D:{guard.daily_used_pct:.0f}%  W:{guard.weekly_used_pct:.0f}%\n"
                f"<i>{now_utc.strftime('%Y-%m-%d %H:%M UTC')}</i>"
            )
            log.info(f"[TRADE] {symbol} {direction} lot={lot} sl={inst_sl} rr=1:{rr} "
                     f"score={filt.score} ev={ev:.2f} cluster={cluster.cluster_key} order={order_id}")
            return {"status":"ok","order_id":order_id,"lot":lot,"signal_id":sid,
                    "sl":inst_sl,"rr":rr,"score":filt.score,"ev":ev,
                    "cluster":cluster.cluster_key,"regime":regime.regime}

        err=resp.get("errorDescr","XTB error")
        send_telegram(f"❌ <b>Order rejected</b>\n{symbol}\n{err}")
        return {"status":"error","msg":err}
    except Exception as e:
        log.error(f"[TRADE] {e}",exc_info=True)
        # ── RECONCILE (timeout-lies): exception here does NOT mean the order failed.
        _adopted=False; _adopt_ticket=None
        try:
            import time as _t, requests as _rrq
            _t.sleep(2.0)
            _rbase=os.getenv("EXECUTOR_URL","").replace("/execute","")
            _rcomment=f"BS_{sid}"
            _rpos=_rrq.get(_rbase+"/positions",timeout=6).json().get("positions",[])
            _matches=[q for q in _rpos if q.get("comment")==_rcomment]
            if _matches:
                _ac2=asset_class(symbol)
                _tracked=list(all_open_trades())
                _this_tracked=any(t.get("signal_id")==sid for _,t in _tracked)
                _slot_taken=any(_a==_ac2 for _a,_ in _tracked)
                _m0=_matches[0]; _adopt_ticket=_m0.get("ticket")
                if _this_tracked:
                    log.warning(f"[RECONCILE] {sid} already tracked; no action")
                    _adopted=True
                elif not _slot_taken:
                    set_open_trade(_ac2,{"order_id":_m0.get("ticket"),"symbol":symbol,
                        "direction":direction,"volume":float(_m0.get("volume",lot) or lot),
                        "entry":float(_m0.get("price_open",entry) or entry),
                        "sl":float(_m0.get("sl",inst_sl) or inst_sl),"raw_sl":raw_sl,
                        "tp":float(_m0.get("tp",tp) or tp),"signal_id":sid,
                        "comment":_rcomment,"cluster_key":cluster.cluster_key,
                        "opened_at":now_utc.isoformat(),"asset_class":_ac2,"adopted":True})
                    save_state(); _adopted=True
                    log.warning(f"[RECONCILE] ADOPTED {_m0.get('ticket')} {symbol} {direction} BS_{sid}")
                    send_telegram(f"\u267b\ufe0f <b>RECOVERED \u2014 order had landed</b>\n"
                        f"{direction} {symbol} ticket <code>{_m0.get('ticket')}</code>\n"
                        f"Placement timed out but the position is LIVE. Adopted \u2014 monitor now managing it.")
                    for _ex in _matches[1:]:
                        log.error(f"[RECONCILE] dup {_ex.get('ticket')} {symbol} BS_{sid}")
                        send_telegram(f"\u26a0\ufe0f <b>RECOVERY_CONFLICT</b>\nExtra LIVE {symbol} "
                            f"ticket <code>{_ex.get('ticket')}</code> (BS_{sid}) UNMANAGED \u2014 close manually.")
                else:
                    for _ex in _matches:
                        log.error(f"[RECONCILE] RECOVERY_CONFLICT slot busy, dup {_ex.get('ticket')} {symbol} BS_{sid}")
                        send_telegram(f"\u26a0\ufe0f <b>RECOVERY_CONFLICT</b>\nLIVE {symbol} ticket "
                            f"<code>{_ex.get('ticket')}</code> (BS_{sid}) landed but slot busy \u2014 "
                            f"UNMANAGED. Close manually or restart to orphan-recover.")
        except Exception as _re:
            log.error(f"[RECONCILE] verify failed: {_re}",exc_info=True)
            send_telegram(f"\U0001f6a8 <b>ORDER STATUS UNKNOWN</b>\n{symbol} {direction} (BS_{sid})\n"
                f"Placement raised AND position check failed. Order MAY be live \u2014 check MT5 now.")
        if _adopted:
            return {"status":"ok","adopted":True,"order_id":_adopt_ticket,"signal_id":sid,
                    "msg":"recovered timed-out order"}
        send_telegram(f"❌ <b>Exception</b>\n{e}")
        return {"status":"error","msg":str(e)}

# ━━ Routes ──────────────────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_start=datetime.now(timezone.utc).isoformat()



@app.route("/webhook",methods=["POST"])
def webhook():
    raw=request.get_data()
    try: payload=json.loads(raw) if raw else {}
    except Exception: return jsonify({"status":"error","msg":"invalid JSON"}),400
    return jsonify(handle_signal(payload,raw))

@app.route("/health",methods=["GET"])
def health():
    ok=xtb._connected and xtb._login_ok
    try: bal=xtb.get_balance()
    except Exception: bal=0
    guard=equity_guard.check(bal,state.get("consecutive_losses",0))
    w=load_weights()
    return jsonify({
        "status":"ok" if ok else "degraded","xtb":ok,"demo":USE_DEMO,
        "paused":state.get("paused"),
        "open_trade":any_open_trade(),
        "open_trades":{k:bool(v) for k,v in (state.get("open_trades") or {}).items()},
        "equity_pct":guard.equity_pct,"risk_pct":guard.risk_pct*100,
        "consecutive_losses":state.get("consecutive_losses",0),
        "wins":state.get("total_wins",0),"losses":state.get("total_losses",0),
        "memory":stats_summary(50),"weights_updated":w.get("updated_at","never"),
        "discipline":discipline.status_dict(),"uptime_since":_start,
    }),200 if ok else 503

@app.route("/clusters",methods=["GET"])
def clusters_route():
    if request.args.get("secret")!=WEBHOOK_SECRET: abort(403)
    from learning.cluster_engine import top_clusters,worst_clusters
    return jsonify({"top":top_clusters(10),"worst":worst_clusters(5)})

@app.route("/stats",methods=["GET"])
def stats_route():
    if request.args.get("secret")!=WEBHOOK_SECRET: abort(403)
    return jsonify({"memory":stats_summary(100),"weights":load_weights(),"discipline":discipline.status_dict()})

@app.route("/recalibrate",methods=["POST"])
def recal_route():
    if (request.get_json(force=True) or {}).get("secret")!=WEBHOOK_SECRET: abort(403)
    try: bal=xtb.get_balance()
    except Exception: bal=1000.0
    daily_dd=max(0,-equity_guard.eq.day_pnl)/max(equity_guard.eq.day_open_balance,1)
    result=recalibrate(daily_dd_pct=daily_dd)
    send_telegram(format_calibration_telegram(result))
    return jsonify(result)

@app.route("/status",methods=["GET"])
def status_route():
    if request.args.get("secret")!=WEBHOOK_SECRET: abort(403)
    try: bal=xtb.get_balance()
    except Exception: bal=0
    return jsonify({"state":state,"equity":equity_guard.status_summary(bal),"timestamp":datetime.now().isoformat()})

@app.route("/reset",methods=["POST"])
def reset_route():
    body = request.get_json(force=True) or {}
    if body.get("secret")!=WEBHOOK_SECRET: abort(403)
    state["consecutive_losses"]=0; state["paused"]=False
    equity_guard.reset_hard_stop()
    # Patch P: also reset peak to real MT5 balance if requested or if peak is stale
    try:
        real_bal = xtb.get_balance()
        if real_bal and real_bal > 0:
            peak = equity_guard.eq.peak_balance
            # If peak is more than 30% above real balance, it's stale. Reset.
            if peak > real_bal * 1.30 or body.get("reset_peak"):
                equity_guard.reset_peak(real_bal)
                send_telegram(f"♻️ <b>Peak reset</b> {peak:.2f} → {real_bal:.2f}")
    except Exception as e:
        log.warning(f"[RESET] could not fetch balance: {e}")
    state["equity"]=equity_guard.to_dict(); save_state()
    send_telegram("✅ <b>Bot reset</b> — all guards cleared.")
    return jsonify({"status":"ok"})

@app.route("/close",methods=["POST"])
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
            send_telegram(f"🔒 <b>Closed manually ({ac})</b>\n{t['symbol']}")
            closed.append({"asset_class":ac,"symbol":t["symbol"],"xtb":resp})
        except Exception as e:
            errors.append({"asset_class":ac,"err":str(e)})
    return jsonify({"status":("ok" if closed and not errors else ("partial" if closed else "error")),
                    "closed":closed,"errors":errors})

# ━━ Shutdown + startup ──────────────━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _on_shutdown(sig,frame):
    _shutdown.set(); send_telegram("⚠️ <b>Bot stopping.</b>"); xtb.disconnect(); raise SystemExit(0)
signal.signal(signal.SIGTERM,_on_shutdown)
signal.signal(signal.SIGINT, _on_shutdown)

def startup():
    log.info("━"*60)
    log.info(" BROTHER SNIPER v7 — SELF-ADJUSTING DECISION SYSTEM")
    log.info(f" Mode: {'DEMO' if USE_DEMO else 'REAL'} | Cluster EV: ON | Discipline: ON")
    log.info("━"*60)
    try: xtb.connect()
    except Exception as e: send_telegram(f"❌ <b>Connect failed</b>\n{e}"); return
    if not xtb.login(): send_telegram("❌ <b>MT5 connection failed</b>"); return

    for name,fn in [("keepalive",_keepalive),("monitor",_monitor),
                    ("spec",_spec_worker),("calibration",_calibration_worker)]:
        threading.Thread(target=fn,daemon=True,name=name).start()

    try: bal=xtb.get_balance()
    except Exception: bal=1000.0
    equity_guard.update_balance(bal)
    w=load_weights(); mem=stats_summary(50)

    send_telegram(
        f"🚀 <b>Brother Sniper v7 — ONLINE</b>\n"
        f"Mode:       {'DEMO 🧪' if USE_DEMO else 'REAL 💰'}\n"
        f"SL:         Institutional + regime-adaptive\n"
        f"AI:         6-factor (learned + discipline-guarded)\n"
        f"EV:         Cluster expectancy gate active\n"
        f"Discipline: weight freeze · delta cap · decay · pos scale\n"
        f"Weights:    calibrated {w.get('updated_at','never')[:10]}\n"
        f"Memory:     {mem.get('trades',0)} trades  WR={mem.get('win_rate',0):.0f}%  "
        f"EV=${mem.get('expectancy',0):.2f}\n"
        f"Balance:    <code>${bal:.2f}</code>  Ready."
    )
    # ── ORPHAN CHECK: if state has open_trade but MT5 doesn't, recover via /history ──
    try:
        _orphans = list(all_open_trades())
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
                                float(_deal.get("commission",0)), hold_time_seconds=_hold,
                                mae=_orphan.get("mae"), mfe=_orphan.get("mfe"),
                                be_done=bool(_orphan.get("be_done")), partial_done=bool(_orphan.get("partial_done")))
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
                save_state()
    except Exception as _e:
        log.error(f"[STARTUP] orphan check failed: {_e}", exc_info=True)
    log.info("[STARTUP] All systems go.")

if __name__=="__main__":
    startup()
    app.run(host="0.0.0.0",port=5000,debug=False,use_reloader=False)
