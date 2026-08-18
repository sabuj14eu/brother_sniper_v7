#!/usr/bin/env python3
"""What would the signals v7 REFUSED have done? (batch, read-only, $0)

v7 records why it killed each signal but never what happened next, so no
gate can be judged. This replays every stored verdict against real candles
and asks the only question that settles the argument: would it have won?

    A gate that killed 100 signals of which 80 would have lost is a GOOD
    gate. One that killed 70 winners is a BAD gate. Frequency says nothing.

HONESTY RULES (copied from pullback_backtest.py:14-19 and the brain's
council_calibration.py — the same rules that settled the PULLBACK argument):
  * No lookahead: only bars strictly AFTER the signal's timestamp count.
  * The entry must actually be touched within FILL_WINDOW_H, else NO_FILL —
    a limit that never fills is not a trade, win or lose.
  * Same bar touches both TP and SL -> SL. Always the conservative reading.
  * Unresolved after RESOLVE_H -> OPEN, counted separately, never as a win.
  * A signal with no entry/sl/tp is UNKNOWN — never reconstructed.

This module NEVER runs in the trading path. It reads journals and candles,
writes one JSONL of outcomes, and touches nothing else.

Usage:
    python3 v7_counterfactual.py                 # replay + summary
    python3 v7_counterfactual.py --json out.json # machine-readable
    python3 v7_counterfactual.py --limit 200     # cap work per run
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
JOURNAL = os.path.join(BASE, "learning", "decisions.jsonl")
SIGNAL_MEMORY = os.path.join(BASE, "signal_memory.json")
OUT_FILE = os.path.join(BASE, "learning", "counterfactual.jsonl")

FILL_WINDOW_H = 12      # a limit unfilled this long is NO_FILL
RESOLVE_H = 48          # unresolved after this is OPEN
TF = "15"               # replay timeframe (minutes)
MAX_BARS = 5000         # bridge cap

# canonical -> bridge symbol candidates, first that returns rows wins
_SYM_CANDIDATES = {
    "GOLD": ["XAUUSD", "GOLD"], "SILVER": ["XAGUSD", "SILVER"],
    "BITCOIN": ["BTCUSD", "BITCOIN"], "ETHEREUM": ["ETHUSD", "ETHEREUM"],
    "LITECOIN": ["LTCUSD"], "RIPPLE": ["XRPUSD"],
    "US30": ["US30", "DJ30"], "USTEC": ["USTEC", "NAS100"],
}


# ── inputs ───────────────────────────────────────────────────────────────────

def _parse_ts(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v / 1000 if v > 4102444800 else v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _num(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def load_verdicts(journal: str | None = None,
                  memory: str | None = None) -> list[dict]:
    """Every stored verdict that carries enough to replay: ts, side, entry,
    sl, tp. Primary source is the decisions journal (it also carries the
    GATE, which is the whole point). signal_memory.json backfills history
    from before the journal existed — it stores every signal pre-validation,
    but has no gate, so those rows replay as gate UNKNOWN."""
    out, seen = [], set()
    for line in _read_lines(journal or JOURNAL):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not isinstance(r, dict):
            continue
        ts, entry = _parse_ts(r.get("ts")), _num(r.get("entry"))
        sl, tp = _num(r.get("sl")), _num(r.get("tp"))
        side = str(r.get("direction") or "").upper()
        if not (ts and entry and sl and tp and side in ("BUY", "SELL")):
            continue
        key = (r.get("signal_id"), round(entry, 6))
        if key in seen:
            continue
        seen.add(key)
        out.append({"signal_id": r.get("signal_id"), "ts": ts,
                    "symbol": r.get("symbol"), "side": side, "entry": entry,
                    "sl": sl, "tp": tp, "gate": r.get("gate") or "UNKNOWN",
                    "stance": r.get("stance"), "session": r.get("session"),
                    "grade": r.get("grade"), "regime": r.get("regime"),
                    "executed": bool(r.get("executed")), "source": "journal"})

    try:
        with open(memory or SIGNAL_MEMORY, encoding="utf-8") as f:
            mem = json.load(f)
    except Exception:
        mem = {}
    for symbol, events in (mem or {}).items():
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            ts, entry = _parse_ts(ev.get("ts")), _num(ev.get("entry"))
            sl, tp = _num(ev.get("sl")), _num(ev.get("tp"))
            side = "BUY" if "BUY" in str(ev.get("category", "")) else (
                "SELL" if "SELL" in str(ev.get("category", "")) else "")
            if not (ts and entry and sl and tp and side):
                continue
            key = (None, round(entry, 6))
            if key in seen:
                continue
            seen.add(key)
            out.append({"signal_id": None, "ts": ts, "symbol": symbol,
                        "side": side, "entry": entry, "sl": sl, "tp": tp,
                        "gate": "UNKNOWN", "stance": None,
                        "session": ev.get("session"), "grade": None,
                        "regime": None, "executed": bool(ev.get("traded")),
                        "source": "signal_memory"})
    out.sort(key=lambda r: r["ts"])
    return out


def _read_lines(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield line
    except FileNotFoundError:
        return


# ── candles ──────────────────────────────────────────────────────────────────

def bridge_candles(symbol: str, tf: str = TF, n: int = MAX_BARS,
                   base_url: str | None = None) -> list[dict]:
    """Closed bars from the v7 bridge. [] on any failure — a missing feed
    must produce UNKNOWN outcomes, never invented ones."""
    base = (base_url or os.getenv("EXECUTOR_URL", "")).replace("/execute", "")
    if not base:
        return []
    q = urllib.parse.urlencode({"symbol": symbol, "tf": tf, "n": n})
    try:
        with urllib.request.urlopen(f"{base}/candles?{q}", timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return []
    rows = data if isinstance(data, list) else (data.get("rows") or [])
    out = []
    for r in rows:
        try:
            out.append({"t": _parse_ts(r.get("time") or r.get("t")),
                        "h": float(r.get("high", r.get("h"))),
                        "l": float(r.get("low", r.get("l"))),
                        "c": float(r.get("close", r.get("c")))})
        except (TypeError, ValueError):
            continue
    return [r for r in out if r["t"]]


def make_candle_cache(fetch=bridge_candles):
    """One fetch per symbol per run, reused across all its verdicts."""
    cache: dict = {}

    def get(symbol: str) -> list[dict]:
        sym = str(symbol or "").upper()
        if sym in cache:
            return cache[sym]
        rows = []
        for cand in _SYM_CANDIDATES.get(sym, [sym]):
            rows = fetch(cand)
            if rows:
                break
        cache[sym] = rows
        return rows
    return get


# ── the replay ───────────────────────────────────────────────────────────────

def replay(verdict: dict, rows: list[dict], *, fill_window_h: float = FILL_WINDOW_H,
           resolve_h: float = RESOLVE_H) -> dict:
    """One verdict against real bars -> HIT | SL | NO_FILL | OPEN | UNKNOWN.

    R is measured against the signal's OWN risk (entry-sl), so a big-stop
    setup cannot look better merely for risking more."""
    entry, sl, tp = verdict["entry"], verdict["sl"], verdict["tp"]
    side, ts = verdict["side"], verdict["ts"]
    risk = abs(entry - sl)
    base = {"signal_id": verdict.get("signal_id"), "ts": verdict["ts"],
            "symbol": verdict.get("symbol"), "side": side, "gate": verdict.get("gate"),
            "stance": verdict.get("stance"), "session": verdict.get("session"),
            "grade": verdict.get("grade"), "regime": verdict.get("regime"),
            "executed": verdict.get("executed"), "source": verdict.get("source"),
            "entry": entry, "sl": sl, "tp": tp,
            "rr": round(abs(tp - entry) / risk, 3) if risk else None}
    if not risk:
        return {**base, "would_have": "UNKNOWN", "r": None,
                "why": "zero risk distance — not replayable"}
    # geometry must be sane in the stated direction, else we are not looking
    # at the trade the bot saw
    if (side == "BUY" and not (sl < entry < tp)) or \
       (side == "SELL" and not (tp < entry < sl)):
        return {**base, "would_have": "UNKNOWN", "r": None,
                "why": "levels inconsistent with direction"}

    fwd = [r for r in rows if r["t"] > ts]          # NO LOOKAHEAD
    if not fwd:
        return {**base, "would_have": "UNKNOWN", "r": None,
                "why": "no candles after the signal — feed missing or too old"}

    fill_i = None
    for i, r in enumerate(fwd):
        if (r["t"] - ts) > fill_window_h * 3600:
            break
        touched = (r["l"] <= entry <= r["h"])
        if touched:
            fill_i = i
            break
    if fill_i is None:
        last_age_h = (fwd[-1]["t"] - ts) / 3600
        if last_age_h < fill_window_h:
            return {**base, "would_have": "OPEN", "r": None,
                    "why": f"only {last_age_h:.1f}h of candles so far — still inside "
                           f"the {fill_window_h}h fill window"}
        return {**base, "would_have": "NO_FILL", "r": 0.0,
                "why": f"entry never touched within {fill_window_h}h — a limit that "
                       f"does not fill is not a trade"}

    for r in fwd[fill_i:]:
        if (r["t"] - ts) > resolve_h * 3600:
            break
        hit_sl = r["l"] <= sl if side == "BUY" else r["h"] >= sl
        hit_tp = r["h"] >= tp if side == "BUY" else r["l"] <= tp
        if hit_sl:                                   # same bar both -> SL
            return {**base, "would_have": "SL", "r": -1.0,
                    "why": "stop hit first (same-bar ties resolve to SL)"}
        if hit_tp:
            return {**base, "would_have": "HIT",
                    "r": round(abs(tp - entry) / risk, 3),
                    "why": "target reached before stop"}
    return {**base, "would_have": "OPEN", "r": None,
            "why": f"filled but unresolved within {resolve_h}h"}


def run(verdicts: list[dict], candles_for) -> list[dict]:
    return [replay(v, candles_for(v.get("symbol"))) for v in verdicts]


# ── summary ──────────────────────────────────────────────────────────────────

def summarize(results: list[dict]) -> dict:
    """Counts only. Expectancy over RESOLVED rows (HIT/SL/NO_FILL); OPEN and
    UNKNOWN are reported, never silently dropped into a denominator."""
    resolved = [r for r in results if r["would_have"] in ("HIT", "SL", "NO_FILL")]
    rs = [r["r"] for r in resolved if r["r"] is not None]
    wins = [r for r in resolved if r["would_have"] == "HIT"]
    return {
        "n_total": len(results),
        "n_resolved": len(resolved),
        "n_open": sum(1 for r in results if r["would_have"] == "OPEN"),
        "n_unknown": sum(1 for r in results if r["would_have"] == "UNKNOWN"),
        "n_hit": len(wins),
        "n_sl": sum(1 for r in resolved if r["would_have"] == "SL"),
        "n_no_fill": sum(1 for r in resolved if r["would_have"] == "NO_FILL"),
        "win_rate": round(len(wins) / len(resolved) * 100, 1) if resolved else None,
        "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
        "provisional": len(resolved) < 20,
    }


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    verdicts = load_verdicts()
    if limit:
        verdicts = verdicts[-limit:]
    if not verdicts:
        print("no replayable verdicts yet — the journal fills as signals arrive")
        return 0
    results = run(verdicts, make_candle_cache())
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, default=str) + "\n")
    s = summarize(results)
    if "--json" in argv:
        path = argv[argv.index("--json") + 1]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"summary": s, "results": results}, f, indent=1, default=str)
    print(f"replayed {s['n_total']} verdicts -> {OUT_FILE}")
    print(f"  resolved {s['n_resolved']} (HIT {s['n_hit']} · SL {s['n_sl']} · "
          f"NO_FILL {s['n_no_fill']}) · OPEN {s['n_open']} · UNKNOWN {s['n_unknown']}")
    if s["n_resolved"]:
        print(f"  would-have WR {s['win_rate']}% · expectancy {s['expectancy_r']}R"
              + ("   [PROVISIONAL n<20 — this is luck, not evidence]"
                 if s["provisional"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
