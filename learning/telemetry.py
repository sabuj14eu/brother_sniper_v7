"""Execution telemetry — the IRRECOVERABLE data layer (LOG ONLY).

Writes one row per trade at OPEN time with every fact we can capture the moment
a trade is placed: IDs, code versions, market snapshot, the full timing chain,
and the execution request/fill. The OUTCOME half (win/loss, R, MAE/MFE, exit)
already lives in learning/trades.jsonl keyed by the same signal_id, so
`load_unified()` joins the two into the single per-trade row the feature store
needs — one trade, one row, no duplicate logs.

HARD RULE: this module NEVER affects trading. Every writer is wrapped so a
failure here cannot propagate into the order path. It only appends to
learning/telemetry.jsonl. Fields we cannot capture yet (bridge fill telemetry)
are written as null and fill in later — the schema is stable from day one so
no data is lost to a missing column.

Two timing chains exist; this file logs the v7 path:
    Pine signal_time -> v7 receive -> v7->bridge send -> bridge->MT5 -> fill
(The v18 brain path -- signal -> brain -> executor -> MT5 -- is logged brain-side.)
"""
from __future__ import annotations

import json
import logging
import os
import threading

log = logging.getLogger("sniper.telemetry")

TELEMETRY_FILE = os.path.join(os.path.dirname(__file__), "telemetry.jsonl")
_LOCK = threading.Lock()

# Canonical schema (grouped as specced). Every key always present; missing = None.
_SCHEMA_GROUPS = {
    "ids": ["trade_id", "signal_id", "broker_ticket"],
    "versions": ["pine_version", "brain_version", "executor_version",
                 "weight_version", "cluster_version"],
    "market": ["symbol", "side", "session", "hour", "day_of_week", "week",
               "regime", "bid", "ask", "spread", "atr", "adx", "rsi",
               "dxy", "oil", "us10y", "vix", "volatility",
               # 08-21 APPEND-ONLY: Pine v18.12 emits entry_dist_atr (how far
               # price had already travelled from the zone, in ATR) on every
               # scalp payload. This column is the SECOND population for the
               # >3 ATR distance question — the platform's paper lanes are
               # the first, and nothing gates until both agree. Forward-only:
               # every trade fired before this column landed dropped the
               # value, so the n>=20-30 per bucket clock starts now.
               "entry_dist_atr"],
    "structure": ["bos", "choch", "fvg", "liquidity_sweep", "order_block",
                  "zone", "htf_align", "setup_type", "strategy_id",
                  # 08-31 APPEND-ONLY: Pine v18.13 emits its own structure
                  # read ("HH/HL" | "LH/LL" | "MIXED") — the SAME three words
                  # auto-live-v1 emits. Captured verbatim so the agreement cut
                  # (does Pine do better when the bot agrees?) becomes a join
                  # instead of an inference; this week it was CANNOT SEPARATE
                  # at n=7/14. Forward-only: the clock starts at the ceremony.
                  "pine_structure"],
    "ai": ["grade", "ai_score", "pine_score", "council_votes", "confidence",
           "reject_reason"],
    "timing": ["signal_time", "v7_receive_time", "send_time",
               "mt5_send_time", "fill_time"],
    "execution": ["requested_price", "fill_price", "slippage", "fill_delay",
                  "broker_latency", "retry_count", "requotes"],
}

# flat ordered field list
_FIELDS = [f for group in _SCHEMA_GROUPS.values() for f in group]


def blank_row() -> dict:
    """A row with every schema field present and null. Callers fill what they have."""
    return {f: None for f in _FIELDS}


def build_open_row(**values) -> dict:
    """Build a telemetry row from whatever the caller captured. Unknown keys are
    IGNORED (never crash on an extra field); known keys fill the schema slot.
    A derived spread is computed from bid/ask if spread wasn't passed."""
    row = blank_row()
    for k, v in values.items():
        if k in row:
            row[k] = v
    if row["spread"] is None and row["bid"] is not None and row["ask"] is not None:
        try:
            row["spread"] = round(float(row["ask"]) - float(row["bid"]), 8)
        except (TypeError, ValueError):
            pass
    row["_type"] = "telemetry_open"
    return row


def write_row(row: dict) -> None:
    """Append one telemetry row. NEVER raises into the caller (order path safety)."""
    try:
        os.makedirs(os.path.dirname(TELEMETRY_FILE), exist_ok=True)
        line = json.dumps(row, default=str) + "\n"
        with _LOCK:
            with open(TELEMETRY_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:  # pragma: no cover - defensive
        log.warning(f"[TELEMETRY] write failed (non-fatal): {e}")


def capture_open(**values) -> None:
    """One-call convenience for the order path: build + write, fully guarded.
    Safe to drop anywhere near trade placement — it cannot affect the trade."""
    try:
        write_row(build_open_row(**values))
    except Exception as e:  # pragma: no cover - defensive
        log.warning(f"[TELEMETRY] capture_open skipped (non-fatal): {e}")


def capture_reject(payload: dict, status: str, reason: str) -> None:
    """Stage 3 — log a REJECTED signal with its reason + the conditions it fired
    under, so the nightly report can later ask 'which rejection rules actually
    improve expectancy?' (join a rejected signal's later forward outcome, if any,
    by signal_id). Never raises. Reads only the Pine payload — no live effect."""
    try:
        from learning.strategy_dna import classify
        row = build_open_row(
            signal_id=payload.get("signal_id"),
            symbol=payload.get("symbol"), side=payload.get("direction") or payload.get("signal"),
            regime=payload.get("regime"),
            atr=payload.get("atr"), adx=payload.get("adx"), rsi=payload.get("rsi"),
            dxy=payload.get("dxy_dir"), us10y=payload.get("yield_dir"),
            entry_dist_atr=payload.get("entry_dist_atr"),
            zone=payload.get("zone") or payload.get("loc_zone"),
            setup_type=payload.get("type"),
            grade=payload.get("grade"), pine_score=payload.get("score"),
            pine_version=payload.get("pine_ver") or payload.get("version"),
            pine_structure=payload.get("structure"),
            reject_reason=reason,
        )
        row["strategy_id"] = classify(payload)
        row["_type"] = "reject"
        row["reject_status"] = status
        write_row(row)
    except Exception as e:  # pragma: no cover - defensive
        log.warning(f"[TELEMETRY] capture_reject skipped (non-fatal): {e}")


# ── unified feature store: join telemetry (open) + trades (outcome) ──────────

def load_unified(telemetry_path: str | None = None, trades: list | None = None) -> list:
    """One trade -> one row. Joins telemetry rows (open-time facts) with the
    trade journal (outcome) by signal_id. Trades with no telemetry still appear
    (outcome-only); telemetry with no outcome appears open (outcome fields null).
    No duplicates: last telemetry row per signal_id wins."""
    telemetry_path = telemetry_path or TELEMETRY_FILE
    tele = {}
    try:
        with open(telemetry_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                sid = r.get("signal_id")
                if sid:
                    tele[sid] = r
    except FileNotFoundError:
        pass

    if trades is None:
        try:
            from learning.trade_memory import load_all
            trades = load_all()
        except Exception:
            trades = []
    outcomes = {t.get("signal_id"): t for t in trades if t.get("signal_id")}

    rows = []
    for sid in set(tele) | set(outcomes):
        row = dict(tele.get(sid, {"signal_id": sid}))
        oc = outcomes.get(sid)
        if oc:
            # outcome fields fill in; telemetry open-time facts stay authoritative
            for k in ("won", "net_profit", "mae", "mfe", "hold_time_seconds",
                      "be_done", "partial_done", "close_price", "risk_pct",
                      "balance_at_open", "rr", "sl_distance", "entry"):
                if oc.get(k) is not None and row.get(k) is None:
                    row[k] = oc.get(k)
            row.setdefault("symbol", oc.get("symbol"))
            row.setdefault("side", oc.get("direction"))
        rows.append(row)
    return rows
