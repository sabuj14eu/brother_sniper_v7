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
MAX_TOKENS   = 512
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
    "You are an independent intraday futures/FX analyst working on the 15-minute "
    "timeframe. You are given recent OHLC candles and basic context for ONE symbol. "
    "Form your OWN view from the price action — do not assume any prior signal exists. "
    "Decide: is there a high-quality trade RIGHT NOW? Most of the time the answer is "
    "NOTHING; only call BUY or SELL on a genuinely clean setup. "
    "Reply with ONLY a compact JSON object, no markdown, no prose: "
    '{"call":"BUY"|"SELL"|"NOTHING","entry":<float|null>,"sl":<float|null>,'
    '"tp":<float|null>,"confidence":0-100,"reason":"<=25 words"}'
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
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"): t = t[4:]
    try:
        o = json.loads(t)
        call = str(o.get("call", "NOTHING")).upper()
        if call not in ("BUY", "SELL", "NOTHING"): call = "NOTHING"
        return {
            "call": call,
            "entry": o.get("entry"), "sl": o.get("sl"), "tp": o.get("tp"),
            "confidence": o.get("confidence"), "reason": str(o.get("reason", ""))[:200],
        }
    except Exception:
        return None

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
    return {
        "symbol": symbol,
        "price": last["close"],
        "atr14": atr,
        "trend_20bar": trend,
        "recent_high": max(highs[-20:]),
        "recent_low": min(lows[-20:]),
        "last_10_closes": [round(c, 5) for c in closes[-10:]],
    }

def _enabled_providers():
    out = []
    for pk, cfg in PROVIDERS.items():
        key = os.getenv(cfg["key_env"], "").strip()
        if key and not key.startswith("<") and key not in ("changeme", "PUT_KEY_HERE"):
            out.append(pk)
    return out

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
    read = _parse_read(_extract_content(api))
    if read is None:
        return None, "bad_json"
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
