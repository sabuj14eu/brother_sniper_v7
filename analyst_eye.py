#!/usr/bin/env python3
"""
Brother Sniper v7 — AI ANALYST EYE (v1, LOG-ONLY)
==================================================
INDEPENDENT market analyst. Does NOT depend on Pine. On each 15m bar close, for
each symbol whose asset-class slot is FREE and margin is OK, it asks each enabled
LLM to read the live candles and produce its OWN entry view (BUY/SELL/NOTHING +
entry/sl/tp + reason). Every read is logged to analyst_reads.jsonl.

THIS MODULE TOUCHES NO TRADES. It only:
  - reads /candles and /positions from the executor (read-only)
  - reads slot state from the bot's state.json (read-only)
  - writes analyst_reads.jsonl

COST CONTROL (the whole point):
  - For each symbol, if its asset-class slot is OCCUPIED -> skip (can't act anyway)
  - If free margin < MARGIN_FLOOR -> skip everything this cycle
  - Only when a slot is genuinely open does it spend an LLM call.

Run standalone:  python3 analyst_eye.py            (loops on 15m boundaries)
Run one cycle:   python3 analyst_eye.py --once      (single pass, for testing)
Dry run (no LLM):python3 analyst_eye.py --once --dry (logs would-call, spends nothing)
"""
import os, sys, json, time, urllib.request, urllib.error
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
HERE       = os.path.dirname(os.path.abspath(__file__))
READS_LOG  = os.path.join(HERE, "learning", "analyst_reads.jsonl")
STATE_FILE = os.path.join(HERE, "state.json")

SYMBOLS = ["SILVER", "GOLD", "BITCOIN", "ETHEREUM", "USDJPY", "USTEC"]

# asset-class map (mirrors bot.py asset_class()) — used for the per-class slot gate
ASSET_OF = {
    "GOLD": "metals", "SILVER": "metals",
    "BITCOIN": "crypto", "ETHEREUM": "crypto", "LITECOIN": "crypto", "RIPPLE": "crypto",
    "USDJPY": "forex", "EURUSD": "forex", "GBPUSD": "forex",
    "USTEC": "other", "US30": "other",
}

MARGIN_FLOOR = 100.0     # skip all analysis if free margin below this
CANDLES_N    = 50        # bars of context handed to the model
BAR_SECONDS  = 15 * 60   # 15m cadence
TIMEOUT_S    = 20
MAX_TOKENS   = 1024      # headroom for the richer JSON schema (512 truncated it)
TEMPERATURE  = 0.2

# Pluggable providers. Claude activates automatically when CLAUDE_API_KEY is set.
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "key_env":  "DEEPSEEK_API_KEY",
        "model":    "deepseek-v4-flash",
        "extra":    {},
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env":  "GEMINI_API_KEY",
        "model":    "gemini-3.1-pro-preview",
        "extra":    {"reasoning_effort": "low"},
    },
    "claude": {
        "base_url": "https://api.anthropic.com/v1",   # OpenAI-compat endpoint
        "key_env":  "CLAUDE_API_KEY",
        "model":    "claude-sonnet-4-6",
        "extra":    {},
    },
}

EXECUTOR_BASE = os.getenv("EXECUTOR_URL", "").replace("/execute", "")

SYSTEM_PROMPT = (
    "You are an independent intraday futures/FX analyst on the 15-minute timeframe. "
    "You are given recent OHLC candles, basic context, multi-timeframe trend "
    "(M15/H1/H4), where price sits in its recent range (pos_in_range_pct: 0=at "
    "support, 100=at resistance), and upcoming economic-calendar events for ONE "
    "symbol. Form your OWN view from the price action AND the news "
    "calendar — do not assume any prior signal exists. "
    "Favour BUYs near support (low pos_in_range) with aligned higher-timeframe "
    "trend, and SELLs near resistance (high pos_in_range) with aligned trend. "
    "Decide: is there a high-quality trade RIGHT NOW? Most of the time the answer is "
    "NOTHING; only call BUY or SELL on a genuinely clean setup. "
    "ALWAYS report your full analysis even when the call is NOTHING: give the levels you "
    "WOULD use if a trade set up, what you are waiting for, and how the news calendar "
    "affects your view. Use real price levels from the candles (support/resistance/"
    "structure), never round guesses. "
    "Reply with ONLY a compact JSON object, no markdown, no prose: "
    '{"call":"BUY"|"SELL"|"NOTHING",'
    '"entry":<float|null>,"sl":<float|null>,"tp":<float|null>,'
    '"confidence":0-100,'
    '"bias":"BULLISH"|"BEARISH"|"NEUTRAL",'
    '"key_level":<float|null>,'
    '"waiting_for":"<=20 words: what would make this a trade>",'
    '"news_impact":"<=15 words: how upcoming events affect this>",'
    '"reason":"<=30 words: your analysis>"}'
)

# ── Tiny helpers ──────────────────────────────────────────────────────────────
def _now_iso(): return datetime.now(timezone.utc).isoformat()

def _http_post_json(url, key, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))

def _http_get_json(url):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))

def _extract_content(api_json):
    try:
        return api_json["choices"][0]["message"]["content"]
    except Exception:
        return ""

def _parse_read(text):
    if not text: return None
    t = text.strip()
    # strip markdown fences if present
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"): t = t[4:]
        t = t.strip()
    o = None
    # try whole string first
    try:
        o = json.loads(t)
    except Exception:
        # extract the first balanced {...} block anywhere in the text
        start = t.find("{")
        if start != -1:
            depth = 0
            for i in range(start, len(t)):
                if t[i] == "{": depth += 1
                elif t[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            o = json.loads(t[start:i+1])
                        except Exception:
                            o = None
                        break
    if not isinstance(o, dict):
        return None
    call = str(o.get("call", "NOTHING")).upper()
    if call not in ("BUY", "SELL", "NOTHING"): call = "NOTHING"
    # Capture the full rich schema; keep extensible (future fields pass through).
    out = {
        "call": call,
        "entry": o.get("entry"), "sl": o.get("sl"), "tp": o.get("tp"),
        "confidence": o.get("confidence"),
        "bias": o.get("bias"),
        "key_level": o.get("key_level"),
        "waiting_for": str(o.get("waiting_for", ""))[:200] if o.get("waiting_for") is not None else None,
        "news_impact": str(o.get("news_impact", ""))[:200] if o.get("news_impact") is not None else None,
        "reason": str(o.get("reason", ""))[:300],
    }
    # pass through any extra keys the model added, so future prompt fields are auto-logged
    for k, v in o.items():
        if k not in out:
            out[k] = v
    return out

def _log_read(symbol, provider_key, model, read, context_summary, error=None):
    try:
        os.makedirs(os.path.dirname(READS_LOG), exist_ok=True)
        row = {
            "ts": _now_iso(),
            "symbol": symbol,
            "provider": provider_key,
            "model": model,
            "context": context_summary,   # price snapshot so the read is self-contained
        }
        if read is None:
            row.update({"call": None, "entry": None, "sl": None, "tp": None,
                        "confidence": None, "reason": None, "error": error})
        else:
            row.update(read)
        with open(READS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass  # logging must never crash the loop

# ── Read-only state / market access ───────────────────────────────────────────
def _slot_occupied(symbol):
    """True if this symbol's asset-class slot already holds a trade (read state.json)."""
    ac = ASSET_OF.get(symbol, "other")
    try:
        st = json.load(open(STATE_FILE))
        slot = (st.get("open_trades") or {}).get(ac)
        return slot is not None
    except Exception:
        return False  # if we can't read state, don't block analysis

def _equity():
    """Read equity for visibility/logging only. /health has no margin_free field,
    so we do NOT gate on margin — the per-class slot gate is the real cost control."""
    try:
        h = _http_get_json(EXECUTOR_BASE + "/health")
        return float(h.get("equity", 0) or 0)
    except Exception:
        return 0.0

def _fetch_candles(symbol):
    url = EXECUTOR_BASE + f"/candles?symbol={symbol}&tf=15&n={CANDLES_N}"
    d = _http_get_json(url)
    return d.get("rows") or []

# ── Multi-timeframe trend (cached: H1/H4 move slowly, refresh hourly) ──────────
_HTF_CACHE = {}   # symbol -> {"t": epoch, "h1": "UP/DOWN/FLAT", "h4": ...}
_HTF_TTL = 3600   # 1 hour — H1/H4 barely change within a 15m cycle

def _ema(vals, period):
    if not vals: return None
    k = 2.0 / (period + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e

def _trend_from_closes(closes):
    if len(closes) < 50: return "UNKNOWN"
    e20, e50 = _ema(closes[-50:], 20), _ema(closes[-50:], 50)
    if e20 is None or e50 is None: return "UNKNOWN"
    sep = (e20 - e50) / e50 * 100 if e50 else 0
    if sep > 0.05: return "UP"
    if sep < -0.05: return "DOWN"
    return "FLAT"

def _htf_trends(symbol):
    """Return (h1_trend, h4_trend), cached 1h to avoid hammering the executor."""
    import time as _t
    c = _HTF_CACHE.get(symbol)
    if c and (_t.time() - c["t"] < _HTF_TTL):
        return c["h1"], c["h4"]
    h1 = h4 = "UNKNOWN"
    try:
        d = _http_get_json(EXECUTOR_BASE + f"/candles?symbol={symbol}&tf=60&n=60")
        rows = d.get("rows") or []
        if rows: h1 = _trend_from_closes([r["close"] for r in rows])
    except Exception:
        pass
    try:
        d = _http_get_json(EXECUTOR_BASE + f"/candles?symbol={symbol}&tf=240&n=60")
        rows = d.get("rows") or []
        if rows: h4 = _trend_from_closes([r["close"] for r in rows])
    except Exception:
        pass
    _HTF_CACHE[symbol] = {"t": _t.time(), "h1": h1, "h4": h4}
    return h1, h4

def _build_context(symbol, rows):
    if not rows: return None
    closes = [r["close"] for r in rows]
    highs  = [r["high"] for r in rows]
    lows   = [r["low"] for r in rows]
    last = rows[-1]
    # simple ATR(14)
    trs = []
    for i in range(1, len(rows)):
        trs.append(max(rows[i]["high"]-rows[i]["low"],
                       abs(rows[i]["high"]-rows[i-1]["close"]),
                       abs(rows[i]["low"]-rows[i-1]["close"])))
    atr = round(sum(trs[-14:]) / max(1, len(trs[-14:])), 5) if trs else None
    trend = "UP" if closes[-1] > closes[max(0, len(closes)-20)] else "DOWN"
    # position in recent range: 0 = at support (BUY zone), 100 = at resistance (SELL zone)
    rhigh = max(highs[-20:]); rlow = min(lows[-20:])
    rng = rhigh - rlow
    pos_in_range = round((last["close"] - rlow) / rng * 100, 1) if rng else 50.0
    # multi-timeframe trend (cached)
    h1_trend, h4_trend = _htf_trends(symbol)
    return {
        "symbol": symbol,
        "price": last["close"],
        "atr14": atr,
        "trend_20bar": trend,
        "trend_h1": h1_trend,
        "trend_h4": h4_trend,
        "recent_high": rhigh,
        "recent_low": rlow,
        "pos_in_range_pct": pos_in_range,   # 0=at support, 100=at resistance
        "last_10_closes": [round(c, 5) for c in closes[-10:]],
    }

def _enabled_providers():
    out = []
    for pk, cfg in PROVIDERS.items():
        key = os.getenv(cfg["key_env"], "").strip()
        if key and not key.startswith("<") and key not in ("changeme", "PUT_KEY_HERE"):
            out.append(pk)
    return out

# ── Economic calendar (faireconomy — same feed the bot's news filter uses) ─────
_CAL_CACHE = {"t": 0.0, "events": []}

# which calendar currencies matter for each symbol
SYMBOL_CCY = {
    "GOLD": ("USD", "XAU"), "SILVER": ("USD", "XAG"),
    "BITCOIN": ("USD", "BTC"), "ETHEREUM": ("USD", "BTC"),
    "USDJPY": ("USD", "JPY"), "USTEC": ("USD",),
}

def _fetch_calendar():
    """Return list of high-impact upcoming events. Cached 10 min. Fail-safe to []."""
    if time.time() - _CAL_CACHE["t"] < 600:
        return _CAL_CACHE["events"]
    try:
        req = urllib.request.Request(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        evs = [e for e in d if str(e.get("impact", "")).lower() == "high"]
        _CAL_CACHE["events"] = evs
        _CAL_CACHE["t"] = time.time()
    except Exception:
        pass
    return _CAL_CACHE["events"]

def _calendar_for(symbol):
    """Upcoming high-impact events relevant to this symbol, with minutes-to-event."""
    ccys = SYMBOL_CCY.get(symbol, ("USD",))
    now = datetime.now(timezone.utc)
    out = []
    for e in _fetch_calendar():
        if str(e.get("country", e.get("currency", ""))).upper() not in ccys:
            continue
        try:
            t = datetime.fromisoformat(str(e.get("date", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        mins = int((t - now).total_seconds() / 60)
        if -60 <= mins <= 720:  # within last hour or next 12h
            out.append({"title": e.get("title"), "currency": e.get("country", e.get("currency")),
                        "in_minutes": mins})
    out.sort(key=lambda x: abs(x["in_minutes"]))
    return out[:5]

def _ask_model(provider_key, context, dry=False):
    cfg = PROVIDERS[provider_key]
    model = cfg["model"]
    if dry:
        return None, "dry"
    key = os.getenv(cfg["key_env"], "").strip()
    payload = {
        "model": model, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
    }
    payload.update(cfg.get("extra", {}))
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    try:
        api = _http_post_json(url, key, payload)
    except urllib.error.HTTPError as e:
        try: detail = e.read().decode("utf-8")[:200]
        except Exception: detail = ""
        return None, f"http_{e.code}:{detail}"
    except Exception as e:
        return None, f"exc:{type(e).__name__}"
    content = _extract_content(api)
    read = _parse_read(content)
    if read is None:
        return None, "bad_json:" + (content or "")[:300].replace("\n", " ")
    return read, None

# ── One cycle ─────────────────────────────────────────────────────────────────
def run_cycle(dry=False):
    providers = _enabled_providers()
    if not providers and not dry:
        print(f"[{_now_iso()}] no enabled providers (no keys) — nothing to do")
        return
    eq = _equity()  # visibility only; slot gate is the cost control
    analyzed = skipped = 0
    for sym in SYMBOLS:
        if _slot_occupied(sym):
            skipped += 1
            continue  # slot full -> can't act -> don't spend
        try:
            rows = _fetch_candles(sym)
        except Exception as e:
            print(f"[{_now_iso()}] {sym} candles failed: {e}")
            continue
        ctx = _build_context(sym, rows)
        if not ctx:
            continue
        # inject economic-calendar awareness (the edge Pine lacks)
        ctx["upcoming_news"] = _calendar_for(sym)
        for pk in (providers or ["dry"]):
            if pk == "dry" or dry:
                _log_read(sym, pk, PROVIDERS.get(pk, {}).get("model", "dry"),
                          {"call": "NOTHING", "reason": "dry-run", "confidence": 0,
                           "entry": None, "sl": None, "tp": None}, ctx)
                continue
            read, err = _ask_model(pk, ctx, dry=dry)
            _log_read(sym, pk, PROVIDERS[pk]["model"], read, ctx, error=err)
            analyzed += 1
    print(f"[{_now_iso()}] cycle done: analyzed={analyzed} skipped_full_slot={skipped} equity=${eq:.0f}")

def _sleep_to_next_bar():
    now = time.time()
    nxt = (int(now // BAR_SECONDS) + 1) * BAR_SECONDS + 5  # +5s after bar close
    time.sleep(max(1, nxt - now))

def main():
    once = "--once" in sys.argv
    dry  = "--dry" in sys.argv
    if not EXECUTOR_BASE:
        print("EXECUTOR_URL not set — cannot fetch candles. Exiting.")
        sys.exit(1)
    if once:
        run_cycle(dry=dry); return
    print(f"[{_now_iso()}] analyst_eye started — symbols={SYMBOLS} providers={_enabled_providers()}")
    while True:
        _sleep_to_next_bar()
        try:
            run_cycle(dry=dry)
        except Exception as e:
            print(f"[{_now_iso()}] cycle error: {e}")

if __name__ == "__main__":
    main()
