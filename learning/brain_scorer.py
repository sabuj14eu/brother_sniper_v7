#!/usr/bin/env python3
"""
brain_scorer.py  --  Brother Sniper v7 self-learning engine.

The LLM (Gemini/DeepSeek) is a FIXED oracle. This file is the part that LEARNS:
it joins each AI verdict (by REAL signal_id) to the trade's realized net_profit,
then accumulates a per-cluster scorecard answering the only question that matters:

    "Inside THIS cluster, does following the AI's VETO actually avoid losers,
     and does its CONFIRM actually keep winners?"

A cluster only becomes AI-actionable once it has enough joined verdicts AND shows
real separation (VETO avg pnl < 0 < CONFIRM avg pnl, with margin). Until then the
verdict is shadow-only. No training, no weights -- just evidence accumulating per
cluster with Beta smoothing so small samples can't trigger.

stdlib only. Run hourly (systemd timer) or on demand.
"""
import json, os, math, sys, time
from collections import defaultdict

# ---- paths (edit if yours differ) -------------------------------------------
BASE        = os.environ.get("BS7_BASE", "/home/shyam/brother_sniper_v7")
VOTES_PATH  = os.path.join(BASE, "learning", "eye_votes.jsonl")
TRADES_PATH = next((c for c in (os.path.join(BASE, "trades.jsonl"), os.path.join(BASE, "learning", "trades.jsonl")) if os.path.exists(c)), os.path.join(BASE, "learning", "trades.jsonl"))
OUT_PATH    = os.path.join(BASE, "learning", "brain_scorecard.json")

# ---- field auto-detect (handles schema drift) -------------------------------
SIG_KEYS   = ["signal_id", "sid", "sig_id", "signalId"]
PNL_KEYS   = ["net_profit", "profit", "pnl", "net", "netProfit", "realized"]
TAKE_KEYS  = ["take", "vote", "decision", "verdict"]
PROV_KEYS  = ["provider", "model", "eye_model", "source"]
CONF_KEYS  = ["confidence", "conf", "score"]

# ---- learning gates (the pre-committed kill criterion lives here) -----------
MIN_N_CLUSTER   = 12     # joined verdicts before a cluster can go actionable
MIN_SEP_USD     = 0.0    # CONFIRM avg must beat VETO avg by at least this
BETA_PRIOR      = 2.0    # smoothing; higher = more skeptical of small samples
KILL_MIN_GLOBAL = 60     # global joined verdicts before kill-check is meaningful
KILL_MIN_EDGE   = 0.0    # global VETO avg must be below CONFIRM avg by this much


def _find(d, keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                continue  # tolerate a bad line, keep scoring
    return rows


def _norm_take(v):
    """Map a verdict to 'CONFIRM' / 'VETO' / None regardless of how it's stored."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "CONFIRM" if v else "VETO"
    s = str(v).strip().lower()
    if s in ("true", "1", "confirm", "take", "yes", "y", "long_ok", "ok"):
        return "CONFIRM"
    if s in ("false", "0", "veto", "skip", "no", "n", "block", "reject"):
        return "VETO"
    return None


def _cluster_key(ctx):
    """Prefer an explicit cluster id; else synthesize from the usual dimensions."""
    if not isinstance(ctx, dict):
        return "UNKNOWN"
    explicit = ctx.get("cluster") or ctx.get("cluster_key")
    if isinstance(explicit, str) and explicit:
        return explicit
    parts = [
        str(ctx.get("symbol", "?")).upper(),
        str(ctx.get("side", "?")).upper(),
        str(ctx.get("session", "?")).upper(),
        str(ctx.get("regime", "?")).upper(),
    ]
    return "|".join(parts)


def _beta_mean(success, n, prior=BETA_PRIOR):
    """Posterior mean of a rate with a symmetric Beta(prior,prior) prior."""
    return (success + prior) / (n + 2 * prior) if (n + 2 * prior) > 0 else 0.0


def build():
    votes  = _load_jsonl(VOTES_PATH)
    trades = _load_jsonl(TRADES_PATH)

    # index trades by signal_id -> net_profit
    pnl_by_sig = {}
    for t in trades:
        if t.get("_type") and t.get("_type") != "close":
            continue  # skip open/partial rows; join only on close
        sid = _find(t, SIG_KEYS)
        pnl = _find(t, PNL_KEYS)
        if sid is None or pnl is None:
            continue
        try:
            pnl_by_sig[str(sid)] = float(pnl)
        except (TypeError, ValueError):
            continue

    clusters = defaultdict(lambda: {
        "CONFIRM": {"n": 0, "wins": 0, "pnl": 0.0},
        "VETO":    {"n": 0, "wins": 0, "pnl": 0.0},
        "providers": defaultdict(lambda: {"n": 0, "joined": 0}),
    })

    joined = unmatched = 0
    g = {"CONFIRM": {"n": 0, "pnl": 0.0}, "VETO": {"n": 0, "pnl": 0.0}}

    for v in votes:
        _prov = str(_find(v, PROV_KEYS, "")).lower()
        if _prov in ("shadow", "", "none", "rule", "rule_engine"):
            unmatched += 1
            continue  # rule-engine echo, not a real AI verdict
        sid  = _find(v, SIG_KEYS)
        take = _norm_take(_find(v, TAKE_KEYS))
        prov = _find(v, PROV_KEYS, "unknown")
        ctx  = v.get("context") if isinstance(v.get("context"), dict) else v
        ckey = _cluster_key(ctx)

        c = clusters[ckey]
        c["providers"][prov]["n"] += 1

        if sid is None or take is None:
            unmatched += 1
            continue
        sid = str(sid)
        if sid not in pnl_by_sig:
            unmatched += 1
            continue

        pnl = pnl_by_sig[sid]
        joined += 1
        c["providers"][prov]["joined"] += 1
        bucket = c[take]
        bucket["n"]   += 1
        bucket["pnl"] += pnl
        if pnl > 0:
            bucket["wins"] += 1
        g[take]["n"]   += 1
        g[take]["pnl"] += pnl

    # ---- per-cluster verdicts ----
    scorecard = {}
    for ckey, c in clusters.items():
        cf, vt = c["CONFIRM"], c["VETO"]
        cf_avg = cf["pnl"] / cf["n"] if cf["n"] else 0.0
        vt_avg = vt["pnl"] / vt["n"] if vt["n"] else 0.0
        n_join = cf["n"] + vt["n"]

        # separation = how cleanly the oracle splits winners (CONFIRM) from losers (VETO)
        separation = cf_avg - vt_avg
        veto_loss_rate    = _beta_mean(vt["n"] - vt["wins"], vt["n"])  # VETO that lost = good
        confirm_win_rate  = _beta_mean(cf["wins"], cf["n"])

        # counterfactual: pnl if we had SKIPPED everything the AI vetoed
        actual   = cf["pnl"] + vt["pnl"]
        followed = cf["pnl"]                      # vetoed trades removed
        lift     = followed - actual              # >0 means listening to veto helped

        actionable = (
            n_join >= MIN_N_CLUSTER
            and vt["n"] >= 4
            and separation > MIN_SEP_USD
            and vt_avg < 0.0
        )
        # trust in [0,1]: blend of separation sign-strength and how much VETO avoided loss
        trust = 0.0
        if n_join:
            sep_term  = 1 / (1 + math.exp(-separation / 5.0)) if separation else 0.5
            trust = round(min(1.0, max(0.0, 0.5 * sep_term + 0.5 * veto_loss_rate)), 3)

        scorecard[ckey] = {
            "n_joined": n_join,
            "confirm": {"n": cf["n"], "avg_pnl": round(cf_avg, 2),
                        "win_rate": round(confirm_win_rate, 3)},
            "veto":    {"n": vt["n"], "avg_pnl": round(vt_avg, 2),
                        "loss_rate": round(veto_loss_rate, 3)},
            "separation_usd": round(separation, 2),
            "counterfactual_lift_usd": round(lift, 2),
            "trust": trust,
            "ai_actionable": actionable,
            "providers": {p: dict(s) for p, s in c["providers"].items()},
        }

    # ---- global kill-check (pre-committed: prove edge or ship to /dev/null) ----
    g_cf = g["CONFIRM"]["pnl"] / g["CONFIRM"]["n"] if g["CONFIRM"]["n"] else 0.0
    g_vt = g["VETO"]["pnl"] / g["VETO"]["n"] if g["VETO"]["n"] else 0.0
    g_edge = g_cf - g_vt
    if joined >= KILL_MIN_GLOBAL:
        verdict = "PROVEN" if g_edge > KILL_MIN_EDGE and g_vt < 0 else "NOT_PROVEN -> /dev/null"
    else:
        verdict = f"PENDING ({joined}/{KILL_MIN_GLOBAL} joined)"

    out = {
        "generated_at": int(time.time()),
        "totals": {"votes": len(votes), "trades": len(trades),
                   "joined": joined, "unmatched_votes": unmatched},
        "global": {"confirm_avg": round(g_cf, 2), "veto_avg": round(g_vt, 2),
                   "edge_usd": round(g_edge, 2)},
        "kill_check": verdict,
        "gates": {"min_n_cluster": MIN_N_CLUSTER, "min_global": KILL_MIN_GLOBAL},
        "clusters": dict(sorted(scorecard.items(),
                                key=lambda kv: kv[1]["counterfactual_lift_usd"],
                                reverse=True)),
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return out


def _report(out):
    t = out["totals"]; gl = out["global"]
    print(f"votes={t['votes']} trades={t['trades']} "
          f"joined={t['joined']} unmatched={t['unmatched_votes']}")
    print(f"GLOBAL  confirm_avg={gl['confirm_avg']}  veto_avg={gl['veto_avg']}  "
          f"edge={gl['edge_usd']}")
    print(f"KILL-CHECK: {out['kill_check']}\n")
    act = [k for k, v in out["clusters"].items() if v["ai_actionable"]]
    print(f"actionable clusters: {len(act)}")
    for ckey, v in out["clusters"].items():
        flag = "ACTIONABLE" if v["ai_actionable"] else "shadow"
        print(f"  [{flag:10}] {ckey:32} n={v['n_joined']:>3} "
              f"sep={v['separation_usd']:>8} lift={v['counterfactual_lift_usd']:>8} "
              f"trust={v['trust']}")


if __name__ == "__main__":
    out = build()
    _report(out)
    print(f"\nwrote {OUT_PATH}")
