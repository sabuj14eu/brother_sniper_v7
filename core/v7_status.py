"""V7 status emitter — a read-only mirror of v7's own state (DISPLAY ONLY).

Feeds the platform's /v7 page and the dashboard's V7 Desk with two records:

  v7_decision   one per Pine signal v7 finishes processing (accepted OR not),
                carrying the stance (TRADE/WAIT/REJECT/ERROR) and the exact
                gate that stopped it — the same tags bot.py already logs.
  v7_heartbeat  every monitor cycle (~60s), carrying pause/kill state, the
                equity picture and the open slots, so "v7 said nothing for an
                hour" is distinguishable from "no setups".

HARD RULES (same law as learning/telemetry.py):
  * This module NEVER affects trading. Every entry point swallows every
    exception. A mirror that can break the order path is worse than no mirror.
  * v7 ships data, the platform displays it. Fields we don't have are absent —
    the consumer renders UNKNOWN, never a manufactured value.
  * Pull surface: learning/v7_status.json (atomic replace, heartbeat + last
    N decisions). Push surface: the EXISTING platform contract from the
    platform repo's docs/INTEGRATION_V7.md — decisions to
    {PLATFORM_URL}/webhooks/brain/decision, heartbeats to
    {PLATFORM_URL}/webhooks/brain/artifact, header X-Brain-Secret, one
    attempt on a daemon thread, failures logged and dropped. OFF until both
    PLATFORM_URL and PLATFORM_SECRET are set in the environment.
  * The platform files anything whose "system" contains "18" into the v18
    lane (normalize_system), so the push stamps system:"v7" and carries
    Pine's own system name as pine_system.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from collections import deque
from datetime import datetime, timezone

log = logging.getLogger("sniper.v7status")

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_FILE = os.path.join(_BASE, "learning", "v7_status.json")

MAX_DECISIONS = 50
SCHEMA_VER = "v7-status-1"

_lock = threading.Lock()
_decisions: deque = deque(maxlen=MAX_DECISIONS)
_heartbeat: dict = {}
_loaded = False
HB_PUSH_MIN_S = 240  # local file refreshes every cycle; the platform push is
                     # throttled so ~60s cycles become ~5-minute artifact rows
_last_hb_push = -float(HB_PUSH_MIN_S)  # first heartbeat always pushes


# ── gate classification ──────────────────────────────────────────────────────
# (status, msg-regex) -> (gate tag, stance). First match wins. The tags mirror
# the [GATE-*] names bot.py logs so the desk and the log file agree.
# stance: TRADE executed · WAIT retryable condition · REJECT structural · ERROR
_GATE_RULES = (
    ("ok",       r".*",                          "PASSED",           "TRADE"),
    ("ignored",  r"grade .* below threshold",    "GATE-GRADE",       "REJECT"),
    ("ignored",  r"v4_rr veto",                  "GATE-V4RR",        "REJECT"),
    ("rejected", r"outside expected range",      "GATE-PRICE",       "REJECT"),
    ("rejected", r"SL (above|below) entry|TP",   "GATE-DIRECTION",   "REJECT"),
    ("rejected", r"no SL",                       "GATE-SL-MISSING",  "REJECT"),
    ("rejected", r"trust mode SL distance",      "GATE-SL-SANITY",   "REJECT"),
    ("rejected", r"SL floor .* exceeds",         "GATE-SL-FLOOR",    "REJECT"),
    ("rejected", r"R:R|rr ",                     "GATE-RR",          "REJECT"),
    ("rejected", r".*",                          "GATE-SL-LIMITS",   "REJECT"),
    ("skipped",  r"duplicate",                   "GATE-DEDUP",       "WAIT"),
    ("skipped",  r"disabled by asset gate",      "GATE-ASSET-BENCH", "WAIT"),
    ("skipped",  r"slot already open",           "GATE-SLOT",        "WAIT"),
    ("skipped",  r"margin floor",                "GATE-MARGIN",      "WAIT"),
    ("skipped",  r".*",                          "GATE-SKIP",        "WAIT"),
    ("paused",   r".*",                          "GATE-PAUSED",      "WAIT"),
    ("blocked",  r"[Nn]ews",                     "GATE-NEWS",        "WAIT"),
    ("blocked",  r"[Ee][Vv]|expectancy",         "GATE-EV",          "WAIT"),
    ("blocked",  r".*",                          "GATE-EQUITY-GUARD","WAIT"),
    ("filtered", r".*",                          "GATE-AI-FILTER",   "WAIT"),
    ("error",    r".*",                          "ERROR",            "ERROR"),
)


def classify_gate(status: str, msg: str) -> tuple:
    """Map a handle_signal result to (gate, stance). Total: always returns."""
    s, m = str(status or ""), str(msg or "")
    for st, pat, gate, stance in _GATE_RULES:
        if st == s and re.search(pat, m):
            return gate, stance
    return (s.upper() or "UNKNOWN"), "ERROR"


# ── record builders ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_decision(payload: dict, result: dict) -> dict:
    """One v7_decision record from the webhook payload + handle_signal result.
    Only facts we actually have; absent field == UNKNOWN on the consumer side."""
    p, r = payload or {}, result or {}
    status = str(r.get("status", ""))
    msg = str(r.get("msg", ""))
    gate, stance = classify_gate(status, msg)

    def num(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    rec = {
        "kind": "v7_decision",
        "ts": _now(),
        "schema": SCHEMA_VER,
        "signal_id": r.get("signal_id") or p.get("signal_id"),
        "symbol": p.get("symbol"),
        "direction": p.get("direction") or p.get("signal") or p.get("action"),
        "pine_system": p.get("system"),
        "type": p.get("type"),
        "session": p.get("session"),
        "tf": p.get("tf"),
        "grade": p.get("grade"),
        "pine_score": p.get("score") or p.get("pine_score"),
        "pine_ver": p.get("pine_ver"),
        "entry": num(p.get("entry")),
        "sl": num(r.get("sl")) or num(p.get("sl")),
        "tp": num(p.get("tp1")) or num(p.get("tp")),
        "rr": num(r.get("rr")) or num(p.get("rr")),
        "atr": num(p.get("atr")),
        "stance": stance,
        "status": status,
        "gate": gate,
        "gate_detail": msg or None,
        "reason": msg or None,  # the platform's recognized field name
        "executed": status == "ok",
        "order_id": r.get("order_id"),
        "lot": r.get("lot"),
        "ai_score": r.get("score") if status in ("ok", "filtered") else None,
        "ev": r.get("ev"),
        "cluster": r.get("cluster"),
        "regime": r.get("regime") or p.get("regime"),
        "bot_version": "v7",
    }
    return {k: v for k, v in rec.items() if v is not None}


def build_heartbeat(state: dict, guard: dict | None = None, *,
                    bridge_ok=None, balance=None, equity=None,
                    symbols_enabled=None) -> dict:
    """One v7_heartbeat record from the live state dict (+ equity guard dict)."""
    st, gd = state or {}, guard or {}
    slots = {}
    for ac, t in (st.get("open_trades") or {}).items():
        if t:
            slots[ac] = {
                "symbol": t.get("symbol"), "ticket": t.get("order_id"),
                "side": t.get("direction"), "entry": t.get("entry"),
                "sl": t.get("sl"), "tp": t.get("tp"),
                "mae": t.get("mae"), "mfe": t.get("mfe"),
                "opened_at": t.get("opened_at"),
            }
        else:
            slots[ac] = None
    hb = {
        "kind": "v7_heartbeat",
        "ts": _now(),
        "schema": SCHEMA_VER,
        "paused": bool(st.get("paused")),
        "hard_stopped": bool(gd.get("hard_stopped")),
        "consecutive_losses": st.get("consecutive_losses", 0),
        "total_trades": st.get("total_trades", 0),
        "total_wins": st.get("total_wins", 0),
        "total_losses": st.get("total_losses", 0),
        "peak_balance": gd.get("peak_balance"),
        "day_pnl": gd.get("day_pnl"),
        "week_pnl": gd.get("week_pnl"),
        "balance": balance,
        "equity": equity,
        "bridge_ok": bridge_ok,
        "open_slots": slots,
        "symbols_enabled": sorted(symbols_enabled) if symbols_enabled else None,
        "last_decision_ts": (_decisions[-1].get("ts") if _decisions else None),
        "bot_version": "v7",
    }
    return {k: v for k, v in hb.items() if v is not None}


# ── persistence (pull surface) ───────────────────────────────────────────────

def _load_existing() -> None:
    """Re-seed the decision ring from the last written file so a restart
    doesn't blank the desk. Guarded; a corrupt file just starts fresh."""
    global _loaded
    _loaded = True
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for d in (data.get("decisions") or [])[-MAX_DECISIONS:]:
            if isinstance(d, dict):
                _decisions.append(d)
    except Exception:
        pass


def _write_status() -> None:
    """Atomic replace of learning/v7_status.json. Caller holds no locks."""
    with _lock:
        if not _loaded:
            _load_existing()
        data = {
            "schema": SCHEMA_VER,
            "written_at": _now(),
            "heartbeat": _heartbeat or None,
            "decisions": list(_decisions),
        }
        d = os.path.dirname(STATUS_FILE)
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, STATUS_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise


# ── push surface (the EXISTING contract: platform docs/INTEGRATION_V7.md) ───

def _push(record: dict, path: str) -> None:
    """Fire-and-forget POST to the platform. Inert until PLATFORM_URL and
    PLATFORM_SECRET are both set (same env names as INTEGRATION_V7.md)."""
    base = os.getenv("PLATFORM_URL", "").rstrip("/")
    secret = os.getenv("PLATFORM_SECRET", "")
    if not base or not secret:
        return
    body = {**record, "system": "v7"}

    def _post():
        try:
            import requests
            requests.post(base + path, json=body, timeout=5,
                          headers={"X-Brain-Secret": secret})
        except Exception as e:
            log.warning(f"[V7-STATUS] push dropped (non-fatal): {type(e).__name__}")

    threading.Thread(target=_post, daemon=True).start()


# ── public entry points (never raise) ────────────────────────────────────────

def record_decision(payload: dict, result: dict) -> None:
    """Call at the /webhook choke point for every finished signal."""
    try:
        rec = build_decision(payload, result)
        with _lock:
            if not _loaded:
                _load_existing()
            _decisions.append(rec)
        _write_status()
        _push(rec, "/webhooks/brain/decision")
    except Exception as e:  # pragma: no cover - defensive
        log.warning(f"[V7-STATUS] record_decision skipped (non-fatal): {e}")


def update_heartbeat(state: dict, guard: dict | None = None, **kw) -> None:
    """Call once per monitor cycle."""
    global _heartbeat
    try:
        hb = build_heartbeat(state, guard, **kw)
        global _last_hb_push
        with _lock:
            _heartbeat = hb
        _write_status()
        # artifacts endpoint expects kind/generated_at; extra keys pass through
        import time as _t
        if _t.monotonic() - _last_hb_push >= HB_PUSH_MIN_S:
            _last_hb_push = _t.monotonic()
            _push({**hb, "generated_at": hb.get("ts"),
                   "title": "v7 heartbeat"}, "/webhooks/brain/artifact")
    except Exception as e:  # pragma: no cover - defensive
        log.warning(f"[V7-STATUS] update_heartbeat skipped (non-fatal): {e}")
