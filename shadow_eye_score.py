#!/usr/bin/env python3
"""
Brother Sniper v7 — SHADOW-EYE SCORING (read-only, run anytime)
===============================================================
The shadow-eye votes (gemini, deepseek) have accumulated for weeks and have
never been scored against outcomes. This joins learning/eye_votes.jsonl to
learning/trades.jsonl by signal_id and answers, per model:

    When the eye said TAKE, what was the win rate and avg R?
    When the eye said BLOCK, what happened to the trades that ran anyway?
    How does each compare to the baseline WR of all joined trades?

    python3 shadow_eye_score.py

NOTHING is written, NOTHING is traded. Pure analysis.
HONESTY: n<20 is PROVISIONAL. The eye only fires on BLOCKED signals, so joined
trades are the overridden/adopted subset — selection bias is real and stated.
R-multiple = net_profit / (balance_at_open * risk_pct) when both are recorded,
else the trade counts for WR only (shown as r_n < n).
"""
import collections
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TRADES = os.path.join(HERE, "learning", "trades.jsonl")
VOTES = os.path.join(HERE, "learning", "eye_votes.jsonl")
MIN_N = 20


def _load_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return rows


def merged_trades(path=TRADES):
    trades = collections.OrderedDict()
    for r in _load_jsonl(path):
        sid = r.get("signal_id")
        if not sid:
            continue
        rec = trades.setdefault(sid, {})
        for k, v in r.items():
            if v is not None:
                rec[k] = v
    return {sid: t for sid, t in trades.items()
            if ("won" in t or "net_profit" in t)
            and "test" not in str(sid).lower()}


def _won(t):
    return bool(t.get("won")) if "won" in t else (t.get("net_profit", 0) or 0) > 0


def _r_multiple(t):
    net = t.get("net_profit")
    bal = t.get("balance_at_open")
    risk = t.get("risk_pct")
    try:
        dollar_risk = float(bal) * float(risk)
        if net is None or dollar_risk <= 0:
            return None
        return float(net) / dollar_risk
    except (TypeError, ValueError):
        return None


def score(votes, trades):
    """Per (model, take-verdict): n, joined, WR, avg R. Returns dict."""
    out = collections.defaultdict(lambda: {
        "votes": 0, "joined": 0, "wins": 0, "r_sum": 0.0, "r_n": 0,
        "conf_hi_joined": 0, "conf_hi_wins": 0,
    })
    for v in votes:
        model = v.get("model", "?")
        take = v.get("take")
        verdict = "TAKE" if take is True else "BLOCK" if take is False else "NONE"
        key = (model, verdict)
        out[key]["votes"] += 1
        sid = v.get("signal_id")
        t = trades.get(sid)
        if not t:
            continue
        out[key]["joined"] += 1
        w = _won(t)
        if w:
            out[key]["wins"] += 1
        r = _r_multiple(t)
        if r is not None:
            out[key]["r_sum"] += r
            out[key]["r_n"] += 1
        try:
            if float(v.get("confidence") or 0) >= 60:
                out[key]["conf_hi_joined"] += 1
                if w:
                    out[key]["conf_hi_wins"] += 1
        except (TypeError, ValueError):
            pass
    return dict(out)


def main():
    votes = _load_jsonl(VOTES)
    trades = merged_trades()
    print(f"\nSHADOW-EYE SCORING   {datetime.now(timezone.utc).isoformat()}")
    print(f"votes: {len(votes)}   closed trades: {len(trades)}")
    if not votes:
        print("INSUFFICIENT DATA — no eye votes logged yet.")
        return

    baseline = [t for t in trades.values()]
    bw = sum(1 for t in baseline if _won(t))
    bl_wr = round(100 * bw / len(baseline), 1) if baseline else None
    print(f"BASELINE (all closed trades): n={len(baseline)} WR={bl_wr}%")
    print("CAVEAT: the eye fires on BLOCKED signals only — joined trades are the")
    print("override/adopt subset, so comparisons vs baseline carry selection bias.\n")

    res = score(votes, trades)
    print(f"  {'model':<22}{'verdict':<8}{'votes':>6}{'joined':>7}{'WR%':>7}"
          f"{'avgR':>7}{'r_n':>5}{'WR%@conf>=60':>13}  flag")
    for (model, verdict), d in sorted(res.items()):
        j = d["joined"]
        wr = round(100 * d["wins"] / j, 1) if j else "-"
        avg_r = round(d["r_sum"] / d["r_n"], 2) if d["r_n"] else "-"
        chj = d["conf_hi_joined"]
        ch_wr = round(100 * d["conf_hi_wins"] / chj, 1) if chj else "-"
        flag = "PROVISIONAL" if j < MIN_N else ""
        print(f"  {model:<22}{verdict:<8}{d['votes']:>6}{j:>7}{str(wr):>7}"
              f"{str(avg_r):>7}{d['r_n']:>5}{str(ch_wr):>13}  {flag}")

    print("\n  Read: a model earns trust when TAKE-WR beats baseline AND BLOCK-WR")
    print("  (trades it wanted to block that ran anyway) sits below baseline, at")
    print(f"  n>={MIN_N} joined each. Anything less stays shadow-only (Evidence Law).")


if __name__ == "__main__":
    main()
