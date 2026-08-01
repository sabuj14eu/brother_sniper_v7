#!/usr/bin/env python3
"""
cluster_analyzer.py  --  Brother Sniper v7 offline edge extractor.

Pure read-only analysis of learning/trades.jsonl. Touches NO live path, needs NO
key, restarts NO service. Joins open<->close by signal_id, computes PLANNED-R
metrics per cluster with sample-size shrinkage + confidence, drills down only where
the data supports it, and audits execution divergence (planned vs realized risk).

Outputs:
  1. human report  -> stdout
  2. machine file  -> learning/cluster_stats.json  (consult_brain reads this directly)

Stats definitions (locked with Shyam):
  R (planned)      = net_profit / (balance_at_open * risk_pct)   # canonical
  R (realized)     = net_profit / (sl_distance * lot * tickvalue_per_point)  # audit only
  divergence       = |realized_risk - planned_risk| / planned_risk
  MAE_R / MFE_R    = mae / sl_distance , mfe / sl_distance       # both in points
  expectancy       = mean(R_planned) per cluster
  SE               = std(R) / sqrt(n)
  confidence       = n / (n + k),  k = base_k * (1 + std_r)      # variance-aware
  shrunk           = confidence*cluster_mean + (1-confidence)*global_mean
  CI90             = mean +/- 1.645 * SE
  proven           = n>=MIN_N AND confidence>=MIN_CONF AND ci_low>0
"""
import json, os, math, statistics as st
from collections import defaultdict

BASE       = os.environ.get("BS7_BASE", "/home/shyam/brother_sniper_v7")
TRADES     = os.path.join(BASE, "learning", "trades.jsonl")
OUT_JSON   = os.path.join(BASE, "learning", "cluster_stats.json")

MIN_N      = 12      # promotion gate: minimum joined trades
MIN_CONF   = 0.70    # promotion gate: minimum confidence
BASE_K     = 10.0    # shrinkage base; scaled up by return variance
DIVERGE_T  = 0.20    # execution-divergence flag threshold (20%)
CI_Z       = 1.645   # 90% one-ish sided

# tick value per 1.0 price-unit move per 1.0 lot, by symbol family (audit metric only;
# approximate -- realized R is for divergence flagging, not for learning)
def _tick_val(symbol):
    s = symbol.upper()
    if "JPY" in s: return 1000.0      # ~ per 1.000 move, 1 lot (rough)
    if any(x in s for x in ("BTC","ETH","BITCOIN","ETHEREUM")): return 1.0
    if any(x in s for x in ("XAU","GOLD")): return 100.0
    if any(x in s for x in ("XAG","SILVER")): return 5000.0
    if any(x in s for x in ("US30","USTEC","NAS","DOW","SPX","US500")): return 1.0
    return 100000.0                    # generic FX per 1.0 move, 1 lot


def load_pairs():
    opens, closes = {}, {}
    raw = 0
    with open(TRADES, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            raw += 1
            sid = r.get("signal_id")
            if sid is None:
                continue
            if r.get("_type") == "open":
                opens[sid] = r            # last open wins (dedup)
            elif r.get("_type") == "close":
                closes[sid] = r
    return opens, closes, raw


def hygiene(opens, closes):
    paired, rej = [], defaultdict(int)
    for sid, o in opens.items():
        c = closes.get(sid)
        # reject reasons (counted transparently)
        if str(sid).startswith("test") or o.get("order_id") in (0, None):
            rej["test_or_synthetic"] += 1; continue
        if c is None:
            rej["unpaired_open"] += 1; continue
        if c.get("net_profit") is None:
            rej["no_close_pnl"] += 1; continue
        bal = o.get("balance_at_open"); rp = o.get("risk_pct"); sld = o.get("sl_distance")
        if not bal or not rp or not sld:
            rej["missing_risk_fields"] += 1; continue
        paired.append((sid, o, c))
    return paired, rej


def build_trades(paired):
    trades = []
    for sid, o, c in paired:
        bal = float(o["balance_at_open"]); rp = float(o["risk_pct"])
        sld = float(o["sl_distance"]);     lot = float(o.get("lot") or 0)
        net = float(c["net_profit"])
        planned_risk = bal * rp
        if planned_risk <= 0:
            continue
        r_planned = net / planned_risk
        # realized risk (audit): money that would be lost at initial SL given filled lot
        realized_risk = sld * lot * _tick_val(o.get("symbol", ""))
        divergence = abs(realized_risk - planned_risk) / planned_risk if planned_risk else None
        mae = c.get("mae"); mfe = c.get("mfe")
        mae_r = (float(mae) / sld) if (mae is not None and sld) else None
        mfe_r = (float(mfe) / sld) if (mfe is not None and sld) else None
        trades.append({
            "sid": sid, "symbol": o.get("symbol", "?"),
            "direction": (o.get("direction") or "?").upper(),
            "session": (o.get("session") or "?").lower(),
            "regime": (o.get("regime") or "?").upper(),
            "r": r_planned, "won": net > 0,
            "net": net, "planned_risk": planned_risk, "realized_risk": realized_risk,
            "divergence": divergence,
            "mae_r": mae_r, "mfe_r": mfe_r,
            "hold_min": (float(c["hold_time_seconds"]) / 60.0) if c.get("hold_time_seconds") else None,
        })
    return trades


def _agg(rows, global_mean):
    n = len(rows)
    rs = [t["r"] for t in rows]
    mean_r = st.mean(rs)
    std_r = st.pstdev(rs) if n > 1 else 0.0
    se = std_r / math.sqrt(n) if n else float("inf")
    k = BASE_K * (1 + std_r)
    conf = n / (n + k) if (n + k) else 0.0
    shrunk = conf * mean_r + (1 - conf) * global_mean
    ci_low, ci_high = mean_r - CI_Z * se, mean_r + CI_Z * se
    wins = [t for t in rows if t["won"]]
    losses = [t for t in rows if not t["won"]]
    gross_w = sum(t["net"] for t in wins)
    gross_l = abs(sum(t["net"] for t in losses))
    pf = (gross_w / gross_l) if gross_l > 0 else (float("inf") if gross_w > 0 else 0.0)
    mae_rs = [t["mae_r"] for t in rows if t["mae_r"] is not None]
    mfe_rs = [t["mfe_r"] for t in rows if t["mfe_r"] is not None]
    holds = [t["hold_min"] for t in rows if t["hold_min"] is not None]
    divs = [t["divergence"] for t in rows if t["divergence"] is not None]
    proven = (n >= MIN_N and conf >= MIN_CONF and ci_low > 0)
    return {
        "n": n, "wr": round(len(wins) / n, 3) if n else 0.0,
        "pf": round(pf, 2) if pf != float("inf") else 999.0,
        "expectancy_raw": round(mean_r, 3),
        "expectancy_shrunk": round(shrunk, 3),
        "expectancy_ci_low": round(ci_low, 3),
        "expectancy_ci_high": round(ci_high, 3),
        "median_r": round(st.median(rs), 3),
        "std_r": round(std_r, 3), "se_r": round(se, 3),
        "confidence": round(conf, 3),
        "avg_mae_r": round(st.mean(mae_rs), 3) if mae_rs else None,
        "avg_mfe_r": round(st.mean(mfe_rs), 3) if mfe_rs else None,
        "avg_hold_min": round(st.mean(holds), 1) if holds else None,
        "avg_divergence": round(st.mean(divs), 3) if divs else None,
        "max_divergence": round(max(divs), 3) if divs else None,
        "trades_diverged": sum(1 for d in divs if d > DIVERGE_T),
        "proven": proven,
    }


def drill(trades, global_mean):
    """Staged auto-drill: descend a level only if BOTH (all) children clear MIN_N."""
    out = {}

    def level(rows, keyfn, label_fn):
        groups = defaultdict(list)
        for t in rows:
            groups[keyfn(t)].append(t)
        return groups

    # Stage 1: symbol
    by_sym = level(trades, lambda t: t["symbol"], None)
    for sym, rows in by_sym.items():
        out[sym] = _agg(rows, global_mean)
        # Stage 2: symbol x direction (only if it splits cleanly)
        by_dir = defaultdict(list)
        for t in rows:
            by_dir[t["direction"]].append(t)
        if len(by_dir) > 1 and all(len(v) >= MIN_N for v in by_dir.values()):
            for d, rr in by_dir.items():
                k2 = f"{sym}|{d}"
                out[k2] = _agg(rr, global_mean)
                # Stage 3: x session
                by_ses = defaultdict(list)
                for t in rr:
                    by_ses[t["session"]].append(t)
                if len(by_ses) > 1 and all(len(v) >= MIN_N for v in by_ses.values()):
                    for ses, r3 in by_ses.items():
                        k3 = f"{sym}|{d}|{ses}"
                        out[k3] = _agg(r3, global_mean)
                        # Stage 4: x regime
                        by_reg = defaultdict(list)
                        for t in r3:
                            by_reg[t["regime"]].append(t)
                        if len(by_reg) > 1 and all(len(v) >= MIN_N for v in by_reg.values()):
                            for reg, r4 in by_reg.items():
                                out[f"{sym}|{d}|{ses}|{reg}"] = _agg(r4, global_mean)
    return out


def main():
    opens, closes, raw = load_pairs()
    paired, rej = hygiene(opens, closes)
    trades = build_trades(paired)
    if not trades:
        print("No valid trades after hygiene. Nothing to analyze."); return

    gmean = st.mean([t["r"] for t in trades])
    clusters = drill(trades, gmean)

    report = {
        "generated_from": TRADES,
        "raw_records": raw,
        "opens": len(opens), "closes": len(closes),
        "valid_paired": len(trades),
        "rejected": dict(rej),
        "global": {
            "n": len(trades),
            "expectancy_r": round(gmean, 3),
            "wr": round(sum(1 for t in trades if t["won"]) / len(trades), 3),
            "avg_divergence": round(st.mean([t["divergence"] for t in trades if t["divergence"] is not None]), 3) if any(t["divergence"] is not None for t in trades) else None,
            "trades_diverged_gt20": sum(1 for t in trades if t["divergence"] and t["divergence"] > DIVERGE_T),
        },
        "gates": {"min_n": MIN_N, "min_conf": MIN_CONF, "diverge_threshold": DIVERGE_T},
        "clusters": dict(sorted(clusters.items(),
                                key=lambda kv: (kv[1]["proven"], kv[1]["expectancy_shrunk"]),
                                reverse=True)),
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2)

    # ---- human report ----
    g = report["global"]
    print("=" * 64)
    print("BROTHER SNIPER v7 — CLUSTER EDGE REPORT")
    print("=" * 64)
    print(f"raw records:   {raw}")
    print(f"opens/closes:  {len(opens)}/{len(closes)}")
    print(f"valid paired:  {len(trades)}")
    if rej:
        print("rejected:      " + ", ".join(f"{k}={v}" for k, v in rej.items()))
    print(f"\nGLOBAL  n={g['n']}  expectancy={g['expectancy_r']}R  WR={g['wr']:.0%}  "
          f"avg_exec_divergence={g['avg_divergence']}  >20%={g['trades_diverged_gt20']}")
    print(f"gates: n>={MIN_N} AND conf>={MIN_CONF} AND CI-low>0\n")
    print(f"{'cluster':30} {'n':>4} {'WR':>5} {'PF':>6} {'rawR':>7} {'shrR':>7} "
          f"{'CIlow':>7} {'conf':>5} {'MAE_R':>6} {'div':>5} {'':4}")
    print("-" * 100)
    for ck, v in report["clusters"].items():
        flag = "PROVEN" if v["proven"] else ""
        divflag = "!" if (v["max_divergence"] or 0) > DIVERGE_T else " "
        print(f"{ck:30} {v['n']:>4} {v['wr']*100:>4.0f}% {v['pf']:>6} "
              f"{v['expectancy_raw']:>7} {v['expectancy_shrunk']:>7} "
              f"{v['expectancy_ci_low']:>7} {v['confidence']*100:>4.0f}% "
              f"{str(v['avg_mae_r']):>6} {str(v['trades_diverged']):>4}{divflag} {flag}")
    print(f"\nwrote {OUT_JSON}")


if __name__ == "__main__":
    main()
