#!/usr/bin/env python3
"""
Brother Sniper v7 — unified audit report (READ-ONLY).

Joins every learning source by signal_id into one record per signal:
  signal_bus     -> the raw signal + context (entry/sl/tp/grade/session/regime)
  flow_vector    -> macro vector (dxy/yield/vol/adx/regime)
  eye_votes      -> AI shadow votes (gemini / deepseek / shadow) : take + confidence
  analyst_reads  -> analyst-eye read (bias / call / key_level)
  trades         -> OUTCOME (net_profit / won / mae / mfe / hold_time)

Writes:
  learning/audit_report.json   full joined records (list, newest last)
  learning/audit_latest.json   compact per-signal summary (dict keyed by signal_id)
And prints a human summary to stdout.

Run anytime:  python3 audit_report.py
It NEVER writes to any live-bot state file and makes no trade decisions.
"""
import json, os, glob, collections, sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
L = os.path.join(BASE, "learning")

def _load(name):
    """Load a jsonl file into a list of dicts; tolerate bad lines."""
    path = os.path.join(L, name)
    rows = []
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows

def _sid(r):
    return r.get("signal_id")

def main():
    signals = _load("signal_bus.jsonl")
    flows   = _load("flow_vector.jsonl")
    votes   = _load("eye_votes.jsonl")
    reads   = _load("analyst_reads.jsonl")
    trades  = _load("trades.jsonl")

    # index by signal_id
    flow_by  = {_sid(r): r for r in flows if _sid(r)}
    trade_by = {_sid(r): r for r in trades if _sid(r)}
    votes_by = collections.defaultdict(list)
    for v in votes:
        if _sid(v):
            votes_by[_sid(v)].append(v)

    # analyst reads have no signal_id — join loosely by symbol+nearest ts (best-effort, optional)
    # (kept out of the hard join to avoid wrong matches; surfaced only in counts)

    records = []
    for s in signals:
        sid = _sid(s)
        if not sid:
            continue
        ctx = s.get("context") or {}
        ms  = ctx  # v7 signal_bus stores fields directly under context
        vlist = votes_by.get(sid, [])
        eye = {}
        for v in vlist:
            eye[v.get("provider", "?")] = {
                "take": v.get("take"),
                "confidence": v.get("confidence"),
                "reason": (v.get("reason") or "")[:120],
            }
        tr = trade_by.get(sid)
        fl = flow_by.get(sid)

        # eye consensus: how many said take=True vs False
        takes = [v.get("take") for v in vlist if v.get("take") is not None]
        eye_yes = sum(1 for t in takes if t)
        eye_no  = sum(1 for t in takes if not t)

        rec = {
            "signal_id": sid,
            "symbol": s.get("symbol") or ms.get("symbol"),
            "direction": ms.get("direction") or s.get("direction") or ms.get("side"),
            "grade": ms.get("grade"),
            "session": ms.get("session"),
            "regime": ms.get("regime") or (fl or {}).get("ny_regime"),
            "entry": ms.get("entry") or s.get("entry"),
            "sl": ms.get("sl") or s.get("sl"),
            "tp1": ms.get("tp1") or ms.get("tp"), "tp2": ms.get("tp2"),
            "htf_trend": ms.get("htf_trend"),
            "cluster": ms.get("cluster"),
            "ai_score": ms.get("ai_score"),
            "vol_regime": (fl or {}).get("vol_regime") or ms.get("vol_regime"),
            "vector": (fl or {}).get("vector"),
            "eye_votes": eye,
            "eye_yes": eye_yes, "eye_no": eye_no,
            "outcome": None if not tr else {
                "won": tr.get("won"),
                "net_profit": tr.get("net_profit"),
                "mae": tr.get("mae"), "mfe": tr.get("mfe"),
                "hold_s": tr.get("hold_time_seconds"),
            },
        }
        records.append(rec)

    # ---- write outputs (into learning/, both new files — not live state) ----
    out_full = os.path.join(L, "audit_report.json")
    out_latest = os.path.join(L, "audit_latest.json")
    with open(out_full, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=1, default=str)
    latest = {r["signal_id"]: r for r in records}
    with open(out_latest, "w", encoding="utf-8") as f:
        json.dump(latest, f, indent=1, default=str)

    # ---- human summary ----
    closed = [r for r in records if r["outcome"] and r["outcome"]["net_profit"] is not None]
    print("\n" + "=" * 68)
    print(f"  BROTHER SNIPER v7 — AUDIT REPORT   {datetime.now(timezone.utc).isoformat()}")
    print("=" * 68)
    print(f"  signals joined : {len(records)}")
    print(f"  with outcome   : {len(closed)}")
    print(f"  with eye votes : {sum(1 for r in records if r['eye_votes'])}")
    print(f"  written        : learning/audit_report.json + audit_latest.json")

    if closed:
        def agg(key, val):
            g = collections.defaultdict(lambda: [0, 0.0, 0])  # n, net, wins
            for r in closed:
                k = r.get(key)
                if val and k != val:
                    continue
                g[k][0] += 1
                g[k][1] += r["outcome"]["net_profit"] or 0
                g[k][2] += 1 if r["outcome"]["won"] else 0
            return g

        print("\n  -- outcome by side --")
        for k, (n, net, w) in sorted(agg("direction", None).items(), key=lambda x: x[1][1]):
            print(f"    {str(k):5} n={n:3} wr={ (w/n*100 if n else 0):4.0f}%  net={net:8.2f}")

        print("\n  -- did the AI eyes predict the loss? (closed trades) --")
        # when BOTH eyes said take=False, how did those trades do vs when eyes said yes
        eyes_no  = [r for r in closed if r["eye_no"] >= 2 and r["eye_yes"] == 0]
        eyes_yes = [r for r in closed if r["eye_yes"] >= 1]
        def netwr(rs):
            if not rs: return "n=0"
            n = len(rs); net = sum(r["outcome"]["net_profit"] or 0 for r in rs)
            w = sum(1 for r in rs if r["outcome"]["won"])
            return f"n={n:3} wr={w/n*100:4.0f}%  net={net:8.2f}"
        print(f"    eyes said SKIP (both no) : {netwr(eyes_no)}")
        print(f"    eyes said TAKE (any yes) : {netwr(eyes_yes)}")
    print("=" * 68 + "\n")

if __name__ == "__main__":
    main()
