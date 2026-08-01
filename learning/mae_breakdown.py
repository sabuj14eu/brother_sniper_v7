#!/usr/bin/env python3
"""Task 1: per-cluster MAE_R/MFE_R distribution. Read-only. Blocks nothing."""
import json, os, statistics as st
from collections import defaultdict
BASE=os.environ.get("BS7_BASE","/home/shyam/brother_sniper_v7")
TRADES=os.path.join(BASE,"learning","trades.jsonl")

opens,closes={}, {}
with open(TRADES,encoding="utf-8",errors="replace") as f:
    for ln in f:
        ln=ln.strip()
        if not ln: continue
        try: r=json.loads(ln)
        except: continue
        sid=r.get("signal_id")
        if sid is None: continue
        if r.get("_type")=="open": opens[sid]=r
        elif r.get("_type")=="close": closes[sid]=r

def pctl(xs,p):
    if not xs: return None
    xs=sorted(xs); k=(len(xs)-1)*p/100; lo=int(k); hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(k-lo)

trades=[]
for sid,o in opens.items():
    c=closes.get(sid)
    if not c or c.get("net_profit") is None: continue
    if str(sid).startswith("test") or o.get("order_id") in (0,None): continue
    sld=o.get("sl_distance"); mae=c.get("mae"); mfe=c.get("mfe")
    if not sld: continue
    rec={"symbol":o.get("symbol","?"),"direction":(o.get("direction") or "?").upper(),
         "won":float(c["net_profit"])>0,
         "mae_r":(float(mae)/sld) if mae is not None else None,
         "mfe_r":(float(mfe)/sld) if mfe is not None else None}
    trades.append(rec)

def report(label, rows):
    n=len(rows)
    mae=[t["mae_r"] for t in rows if t["mae_r"] is not None]
    mfe=[t["mfe_r"] for t in rows if t["mfe_r"] is not None]
    if not mae:
        print(f"{label:22}{n:>4}  (no mae data)"); return
    noise_stop=sum(1 for x in mae if x>1.0)/len(mae)
    capture=sum(1 for x in mfe if x>1.0)/len(mfe) if mfe else 0
    wr=sum(1 for t in rows if t["won"])/n
    print(f"{label:22}{n:>4}  WR={wr*100:>3.0f}%  "
          f"MAE_R {pctl(mae,50):.2f}/{pctl(mae,75):.2f}/{pctl(mae,95):.2f}  "
          f"MFE_R {pctl(mfe,50):.2f}/{pctl(mfe,75):.2f}/{pctl(mfe,95):.2f}  "
          f"noise-stop={noise_stop*100:.0f}%  1R+move={capture*100:.0f}%")

print("="*112)
print("TASK 1 — PER-CLUSTER MAE_R / MFE_R   (median/75th/95th)")
print("noise-stop% = share with MAE_R>1.0 (adverse move passed the stop)")
print("1R+move%    = share with MFE_R>1.0 (favorable move passed 1R)")
print("="*112)
report("GLOBAL", trades)
print("-"*112)
by_sym=defaultdict(list)
for t in trades: by_sym[t["symbol"]].append(t)
for sym in sorted(by_sym,key=lambda s:-len(by_sym[s])):
    report(sym, by_sym[sym])
    bd=defaultdict(list)
    for t in by_sym[sym]: bd[t["direction"]].append(t)
    if len(bd)>1 and all(len(v)>=8 for v in bd.values()):
        for d,rr in bd.items(): report(f"  {sym}|{d}", rr)
