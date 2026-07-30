"""
filters/deepseek_vote.py  --  provider-agnostic "eye" tiebreaker for Brother Sniper v7.

WHAT CHANGED: this file is now MODEL-SWAPPABLE. The public function name and
signature are UNCHANGED, so the existing hook in filters/ai_filter.py needs NO edit.

Pick the agent in .env:
    EYE_MODEL=gemini      -> Gemini 3.1 Pro Preview   (gemini-3.1-pro-preview)
    EYE_MODEL=deepseek    -> DeepSeek V4 Flash         (deepseek-v4-flash)   [default]
    EYE_MODEL=shadow      -> OPTIONAL: ask BOTH, log both, let PRIMARY decide
                             (set EYE_SHADOW_PRIMARY=gemini|deepseek; default deepseek)

CONTRACT (unchanged):
    deepseek_tiebreak(signal: dict) -> (take: bool, confidence: int, reason: str) | None

FAIL-SAFE BY DESIGN: missing key / network error / timeout / bad JSON -> returns None
-> the caller keeps the trade BLOCKED. The eye is only ever called on BLOCKED signals,
so it only spends API money on trades the rules already rejected. No key in .env = the
bot behaves EXACTLY as before (pure no-op).

PER-MODEL SCORING: the model that voted is recorded two ways so overrides are scoreable
even though the return tuple keeps its original 3-field shape:
   1) prefixed into the reason string ->  "[gemini-3.1-pro-preview] ..."
   2) appended as a self-contained JSON line to learning/eye_votes.jsonl
"""

import os
import re
import json
import time
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Provider table. base_url + key env + model string + per-provider extra body.
# Only universally-safe OpenAI fields go in the shared body; risky provider-
# specific knobs live in "extra" so a param one provider rejects can never
# 400 the other provider's week.
# ---------------------------------------------------------------------------
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "key_env":  "DEEPSEEK_API_KEY",
        "model":    "deepseek-v4-flash",
        "extra":    {},  # default (cheap) mode; no risky params
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env":  "GEMINI_API_KEY",
        "model":    "gemini-3.1-pro-preview",
        # keep Gemini's thinking shallow -> protects the $12/1M output bill
        "extra":    {"reasoning_effort": "low"},
    },
}

TIMEOUT_S = 15          # hard cap so a hung API never stalls the signal loop
MAX_TOKENS = 512        # headroom for the JSON answer (Gemini thinks server-side)
TEMPERATURE = 0.2       # low = consistent votes
CONF_FLOOR_HINT = 60    # informational only; the >=60 gate lives in ai_filter.py

_HERE = os.path.dirname(os.path.abspath(__file__))
_VOTE_LOG = os.path.join(_HERE, "..", "learning", "eye_votes.jsonl")

SYSTEM_PROMPT = (
    "You are a disciplined intraday trading risk filter. The rule engine has "
    "BLOCKED this signal (its score was below the threshold). Decide whether the "
    "setup is still genuinely worth taking. Be conservative: rescue only "
    "high-probability setups; when unsure, do not take. "
    "Reply with ONLY a compact JSON object and nothing else (no markdown, no prose): "
    '{"take": true|false, "confidence": 0-100, "reason": "<=20 words"}'
)


def _active_model():
    """Return (provider_key, EYE_MODEL_raw). Default deepseek."""
    raw = (os.getenv("EYE_MODEL") or "deepseek").strip().lower()
    if raw == "shadow":
        return "shadow", raw
    if raw in PROVIDERS:
        return raw, raw
    # unknown value -> safest default, but make it visible in the log/reason
    return "deepseek", raw


def _http_post_json(url, key, payload, timeout=TIMEOUT_S):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_content(api_json):
    """Pull the assistant text from an OpenAI-compatible response. Tolerant."""
    try:
        choice = api_json["choices"][0]
    except (KeyError, IndexError, TypeError):
        return None
    msg = choice.get("message") or {}
    content = msg.get("content")
    # some providers return content as a list of parts
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                parts.append(p.get("text") or "")
            else:
                parts.append(str(p))
        content = "".join(parts)
    return content if isinstance(content, str) else None


def _parse_vote(text):
    """text -> (take:bool, confidence:int, reason:str) or None. Fails safe."""
    if not text:
        return None
    # strip ```json ... ``` fences if present
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    # grab the first {...} block
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    if "take" not in obj or "confidence" not in obj:
        return None
    try:
        take = bool(obj["take"])
        conf = int(round(float(obj["confidence"])))
    except (ValueError, TypeError):
        return None
    conf = max(0, min(100, conf))
    reason = str(obj.get("reason", ""))[:200]
    return take, conf, reason


def _log_vote(provider_key, model, signal, result, error=None):
    """Append a self-contained line to learning/eye_votes.jsonl. Never raises."""
    try:
        os.makedirs(os.path.dirname(_VOTE_LOG), exist_ok=True)
        row = {
            "ts": round(time.time(), 3),
            "provider": provider_key,
            "model": model,
            "signal_id": signal.get("signal_id"),
            "symbol": signal.get("symbol"),
            "direction": signal.get("direction"),
            "rule_score": signal.get("rule_score"),
            "threshold": signal.get("threshold"),
            "session": signal.get("session"),
            "regime": signal.get("regime"),
        }
        if result is None:
            row.update({"take": None, "confidence": None,
                        "reason": None, "error": error})
        else:
            take, conf, reason = result
            row.update({"take": take, "confidence": conf, "reason": reason})
        with open(_VOTE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass  # logging must never break the trade path


def _ask_one(provider_key, signal):
    """Call a single provider. Returns (take, conf, reason_with_model_tag) or None."""
    cfg = PROVIDERS[provider_key]
    key = os.getenv(cfg["key_env"], "").strip()
    model = cfg["model"]
    if not key or key.startswith("<") or key in ("changeme", "PUT_KEY_HERE"):
        _log_vote(provider_key, model, signal, None, error="no_key")
        return None

    payload = {
        "model": model,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(signal, ensure_ascii=False)},
        ],
    }
    payload.update(cfg.get("extra", {}))

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    try:
        api_json = _http_post_json(url, key, payload)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            detail = ""
        _log_vote(provider_key, model, signal, None,
                  error="http_%s:%s" % (e.code, detail))
        return None
    except Exception as e:
        _log_vote(provider_key, model, signal, None,
                  error="exc:%s" % (type(e).__name__,))
        return None

    parsed = _parse_vote(_extract_content(api_json))
    if parsed is None:
        _log_vote(provider_key, model, signal, None, error="bad_json")
        return None

    take, conf, reason = parsed
    tagged = "[%s] %s" % (model, reason)
    _log_vote(provider_key, model, signal, (take, conf, tagged))
    return take, conf, tagged


def deepseek_tiebreak(signal):
    """
    PUBLIC API (unchanged). Returns (take, confidence, reason) or None.
    The reason string is prefixed with the model tag, e.g. "[deepseek-v4-flash] ...",
    so downstream breakdown rows carry which agent voted.
    """
    if not isinstance(signal, dict):
        return None

    provider_key, raw = _active_model()

    if provider_key == "shadow":
        primary = (os.getenv("EYE_SHADOW_PRIMARY") or "deepseek").strip().lower()
        if primary not in PROVIDERS:
            primary = "deepseek"
        secondary = "gemini" if primary == "deepseek" else "deepseek"
        # ask both (both get logged to eye_votes.jsonl), but only PRIMARY decides
        primary_result = _ask_one(primary, signal)
        try:
            _ask_one(secondary, signal)  # logged only, never controls the trade
        except Exception:
            pass
        return primary_result

    # normal single-model path
    return _ask_one(provider_key, signal)


# convenience alias if you prefer a neutral name in new code
ai_tiebreak = deepseek_tiebreak


if __name__ == "__main__":
    # quick local self-check (no network): parsing + model selection
    demo = {"symbol": "US30", "direction": "BUY", "rule_score": 68,
            "threshold": 72, "session": "london", "regime": "TREND",
            "flags": ["ATR"]}
    pk, raw = _active_model()
    print("EYE_MODEL raw =", raw, "| resolved provider =", pk)
    print("parse test:", _parse_vote('```json\n{"take": true, '
                                      '"confidence": 71, "reason": "clean retest"}\n```'))
    print("bad parse  :", _parse_vote("no json here"))
