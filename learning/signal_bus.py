#!/usr/bin/env python3
"""
signal_bus.py  --  the ONLY thing that touches bot.py's live trade path.

It does a single non-blocking append (signal + context) to signal_bus.jsonl and
returns immediately. No network, no AI call, no lock contention. The voting and
scoring happen in a SEPARATE process (vote_worker.py) reading this file, so the
executor can never hang or be broken by the AI layer.

In bot.py, AFTER the signal is parsed and you have the REAL signal_id (sid) and
cluster.stats, add ONE line:

    from learning.signal_bus import emit_signal
    emit_signal(sid, {
        "symbol": symbol, "side": side, "grade": grade,
        "entry": entry, "sl": sl, "tp": tp,
        "htf_trend": htf_trend, "atr": atr, "regime": regime,
        "session": session,
        "cluster": cluster.key,            # or build it; scorer can synthesize too
        "cluster_n": cluster.stats.get("n"),
        "cluster_wr": cluster.stats.get("wr"),
        "cluster_pf": cluster.stats.get("pf"),
        "news_window": news_window,
    })

That's it. Trade proceeds on Pine+bot exactly as today. Verdict is shadow.
"""
import json, os, time

BASE = os.environ.get("BS7_BASE", "/home/shyam/brother_sniper_v7")
BUS  = os.path.join(BASE, "learning", "signal_bus.jsonl")


def emit_signal(signal_id, context):
    """Append-only, swallow all errors -- the live path must NEVER break here."""
    try:
        os.makedirs(os.path.dirname(BUS), exist_ok=True)
        rec = {"signal_id": str(signal_id), "ts": int(time.time()),
               "context": context}
        line = json.dumps(rec, default=str)
        # single atomic-ish append; O_APPEND keeps it safe across the worker tail
        with open(BUS, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # by design: a logging failure must not affect execution
