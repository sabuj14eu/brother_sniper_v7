#!/usr/bin/env python3
"""
Brother Sniper v7 — WEEKLY REPORT v2 (READ-ONLY).

One command, one report. Reads only existing files, writes nothing to live
state, makes no trade decisions.

HONESTY RULES:
  - Sample windows are labelled: "joined (audit)" vs "closed (history)".
  - MAE/MFE shown as R-distributions (median/75/95/max), not a lone average.
  - Cluster confidence uses a Wilson interval on win-rate — deliberately WIDE
    on small n, so you never trust a tiny sample.
  - Sections with no data say "collecting" and name the fix. Never invents.

Usage:
  python3 audit_report.py            # refresh join first (fills grade/entry/sl)
  python3 weekly_report.py [--days 7]
"""
import json, os, sys, math, subprocess, collections
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
L    = os.path.join(BASE, "learning")
LOG  = os.path.join(BASE, "logs", "bot.log")

def _load_jsonl(name):
    path = os.path.join(L, name); rows = []
    if not os.path.exists(path): return rows
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln: continue
        try: rows.append(json.loads(ln))
        except Exception: continue
    return rows

def _load_json(name, default):
    path = os.path.join(L, name)
    if not os.path.exists(path): return default
    try: return json.load(open(path, encoding="utf-8"))
    except Exception: return default

def _pf(gw, gl):
    return float("inf") if (gl == 0 and gw) else (round(gw/abs(gl), 2) if gl else 0.0)

def _pct(sorted_vals, p):
    if not sorted_vals: return None
    k = (len(sorted_vals)-1) * p
    lo = math.floor(k); hi = math.ceil(k)
    if lo == hi: return sorted_vals[int(k)]
    return sorted_vals[lo] + (sorted_vals[hi]-sorted_vals[lo])*(k-lo)

def _wilson(wins, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = wins/n; d = 1 + z*z/n
    centre = (p + z*z/(2*n)) / d
    half = (z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / d
    return (max(0.0, centre-half), min(1.0, centre+half))

def _bucket(rows, keyfn):
    g = collections.defaultdict(lambda: {"n":0,"w":0,"net":0.0,"gw":0.0,"gl":0.0})
    for r in rows:
        k = keyfn(r)
        if k is None: continue
        net = r["net"]; g[k]["n"]+=1; g[k]["net"]+=net
        if r["won"]: g[k]["w"]+=1; g[k]["gw"]+=net
        else:        g[k]["gl"]+=net
    return g

def _print_bucket(title, g, min_n):
    print(f"\n  {title}")
    if not g:
        print("    (collecting - no data)"); return
    out = []
    for k, v in g.items():
        wr = v["w"]/v["n"]*100 if v["n"] else 0
        pf = _pf(v["gw"], v["gl"])
        out.append((v["net"], k, v["n"], wr, pf))
    for net, k, n, wr, pf in sorted(out):
        pfs = "inf" if pf==float("inf") else f"{pf:.2f}"
        flag = "PROV" if n < min_n else ""
        print(f"    {str(k):12} n={n:3}  wr={wr:4.0f}%  PF={pfs:>4}  net={net:8.2f}  {flag}")

def _grep_count(pattern, extended=False):
    if not os.path.exists(LOG): return "n/a"
    try:
        flag = "-cE" if extended else "-c"
        r = subprocess.run(["grep", flag, pattern, LOG], capture_output=True, text=True)
        return r.stdout.strip() or "0"
    except Exception:
        return "n/a"

def main():
    days = 7
    if "--days" in sys.argv:
        try: days = int(sys.argv[sys.argv.index("--days")+1])
        except Exception: pass
    cutoff = datetime.now(timezone.utc).timestamp() - days*86400

    trades   = _load_jsonl("trades.jsonl")
    audit    = _load_json("audit_report.json", [])
    clusters = _load_json("clusters.json", {})
    audit_by = {r.get("signal_id"): r for r in audit}

    rows, in_window = [], 0
    for t in trades:
        if t.get("net_profit") is None: continue
        a = audit_by.get(t.get("signal_id"), {})
        entry = a.get("entry"); sl = a.get("sl")
        risk = abs(entry - sl) if isinstance(entry,(int,float)) and isinstance(sl,(int,float)) and entry!=sl else None
        ts = t.get("timestamp_close") or 0
        try: ts = float(ts)
        except Exception: ts = 0
        if ts and ts >= cutoff: in_window += 1
        rows.append({
            "sid": t.get("signal_id"), "net": t.get("net_profit") or 0.0,
            "won": bool(t.get("won")), "mae": t.get("mae"), "mfe": t.get("mfe"),
            "sym": a.get("symbol"), "side": a.get("direction"),
            "session": a.get("session"), "regime": a.get("regime"),
            "grade": a.get("grade"), "cluster": a.get("cluster"), "risk": risk,
        })
    n = len(rows)

    print("\n" + "="*64)
    print("  BROTHER SNIPER - WEEKLY REPORT  v2")
    print(f"  {datetime.now(timezone.utc).isoformat()}")
    print("="*64)
    print("\n  SAMPLE")
    print(f"    Signals joined (audit, ~last {len(audit)}) : {len(audit)}")
    print(f"    Closed trades analysed (history)      : {n}")
    print(f"    Closed within last {days}d               : {in_window}")
    print("    NOTE: segments below use FULL history, not just the window,")
    print("          because only the joined signals carry context so far.")
    if n == 0:
        print("\n  No closed trades. Nothing to score.\n" + "="*64); return

    wins = [r for r in rows if r["won"]]
    gw = sum(r["net"] for r in wins); gl = sum(r["net"] for r in rows if not r["won"])
    net = gw+gl; wr = len(wins)/n*100; pf = _pf(gw, gl)
    losers = [r for r in rows if not r["won"]]
    avgw = gw/len(wins) if wins else 0; avgl = gl/len(losers) if losers else 0
    exp_R = (net/n)/abs(avgl) if avgl else 0
    lo_wr, hi_wr = _wilson(len(wins), n)
    print("\n  PERFORMANCE (history)")
    print(f"    Win rate     : {wr:.0f}%   (95% CI {lo_wr*100:.0f}-{hi_wr*100:.0f}%)")
    print(f"    Profit factor: {'inf' if pf==float('inf') else pf}")
    print(f"    Net          : {net:+.2f}")
    print(f"    Avg win/loss : {avgw:+.2f} / {avgl:+.2f}")
    print(f"    Expectancy   : {exp_R:+.2f}R (approx)")
    v = "EDGE" if net>0 and pf>=1.1 else "MARGINAL" if net>0 else "LOSING"
    print(f"    Verdict      : {v}")

    _print_bucket("BY SIDE",    _bucket(rows, lambda r: r["side"]),    15)
    _print_bucket("BY SYMBOL",  _bucket(rows, lambda r: r["sym"]),     20)
    _print_bucket("BY SESSION", _bucket(rows, lambda r: r["session"]), 15)
    _print_bucket("BY REGIME",  _bucket(rows, lambda r: r["regime"]),  15)

    grades = [r for r in rows if r["grade"]]
    if len(grades) >= 3:
        _print_bucket("BY GRADE", _bucket(rows, lambda r: r["grade"]), 15)
    else:
        print("\n  BY GRADE")
        print(f"    grade on {len(grades)}/{n} trades - signal_bus grade-logging was just")
        print("    fixed; fills in as NEW trades close. Collecting.")

    print("\n  EXCURSION (MAE/MFE in R - needs joined entry/sl)")
    mae_R = sorted(r["mae"]/r["risk"] for r in rows if r["mae"] and r["risk"])
    mfe_R = sorted(r["mfe"]/r["risk"] for r in rows if r["mfe"] and r["risk"])
    if len(mae_R) >= 3:
        def dist(name, arr):
            print(f"    {name}_R  n={len(arr):3}  median={_pct(arr,0.5):.2f}  75%={_pct(arr,0.75):.2f}  95%={_pct(arr,0.95):.2f}  max={arr[-1]:.2f}")
        dist("MAE", mae_R); dist("MFE", mfe_R)
        med_mae = _pct(mae_R, 0.5)
        if med_mae >= 0.85:
            print(f"    ! median MAE_R={med_mae:.2f} - trades routinely dig near the stop")
            print("      before working. Stop placement may be limiting expectancy.")
    else:
        print(f"    only {len(mae_R)} trades have joined entry/sl - collecting.")
        print("    (fills in as new signals flow through the fixed signal_bus join)")

    print("\n  CLUSTERS (learned)")
    cl = [(k, v) for k, v in clusters.items() if isinstance(v, dict) and v.get("n_trades")]
    trusted = [(k,v) for k,v in cl if v.get("n_trades",0) >= 8]
    pending = [(k,v) for k,v in cl if 0 < v.get("n_trades",0) < 8]
    print(f"    trusted (n>=8): {len(trusted)}    pending (<8): {len(pending)}")
    if trusted:
        ranked = sorted(trusted, key=lambda kv: kv[1].get("expectancy",0))
        def line(tag, kv):
            k,v = kv; n_=v.get("n_trades",0); wr_=v.get("win_rate",0)
            lo,hi=_wilson(round(wr_*n_), n_)
            print(f"    {tag}: {k}")
            print(f"        n={n_}  exp={v.get('expectancy',0):+.3f}R  wr={wr_*100:.0f}%  (CI {lo*100:.0f}-{hi*100:.0f}%)")
        line("BEST ", ranked[-1]); line("WORST", ranked[0])
    else:
        print("    no cluster has >=8 trades yet - none trusted. Collecting.")

    print("\n  EXECUTION HEALTH (from bot.log, all-time)")
    print(f"    Orphans adopted        : {_grep_count('Orphan adopted')}")
    print(f"    Timeout / read-timeout : {_grep_count('timed out|timeout', extended=True)}")
    print(f"    Partial close failed   : {_grep_count(r'\[PARTIAL\] close failed', extended=True)}")
    print(f"    Breakeven modify failed: {_grep_count(r'\[BE\] modify failed', extended=True)}")
    print(f"    Mgmt errors            : {_grep_count(r'\[MGMT\] error', extended=True)}")
    print(f"    SL widened events      : {_grep_count('widened SL')}")
    print("    (text-logged, all-time - not per-trade or windowed)")

    print("\n  RECOMMENDATIONS (data-driven)")
    recs = []
    for side, vv in _bucket(rows, lambda r: r["side"]).items():
        if vv["n"]>=15 and vv["net"]<0:
            recs.append(f"! {side} losing (n={vv['n']} net={vv['net']:.0f}) - gate/stand down.")
        elif vv["n"]>=15 and _pf(vv['gw'],vv['gl'])>=1.2:
            recs.append(f"+ {side} has edge (PF {_pf(vv['gw'],vv['gl'])}) - lean in.")
    for sym, vv in _bucket(rows, lambda r: r["sym"]).items():
        if vv["n"]>=10 and vv["net"]<-50:
            recs.append(f"! {sym} bleeding (net {vv['net']:.0f}) - review entries.")
        elif vv["n"]>=10 and _pf(vv['gw'],vv['gl'])>=1.3:
            recs.append(f"+ {sym} strong (PF {_pf(vv['gw'],vv['gl'])}) - raise confidence.")
    for ses, vv in _bucket(rows, lambda r: r["session"]).items():
        if vv["n"]>=10 and _pf(vv['gw'],vv['gl'])<0.9:
            recs.append(f"! {ses} session weak (PF {_pf(vv['gw'],vv['gl'])}).")
    if len(mae_R) >= 5 and _pct(mae_R,0.5) >= 0.85:
        recs.append("+ PRIORITY: investigate stop width - median MAE_R near 1.0 "
                     "means noise is stopping trades before they work.")
    if not recs:
        recs.append("Not enough per-segment data - keep collecting.")
    for r in recs[:12]:
        print(f"    {r}")

    print("\n" + "="*64)
    print("  Mirror only - informs your decisions, changes nothing in the bot.")
    print("="*64 + "\n")

if __name__ == "__main__":
    main()
