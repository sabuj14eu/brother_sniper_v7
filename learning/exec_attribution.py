#!/usr/bin/env python3
"""Execution attribution + MAE/MFE distribution. Read-only. Blocks nothing."""
import json, os, math, statistics as st
from collections import defaultdict
BASE=os.environ.get("BS7_BASE","/home/shyam/brother_sniper_v7")
TRADES=os.path.join(BASE,"learning","trades.jsonl")

def _tickval(sym):
    s=sym.upper()
    if "JPY" in s: return 1000.0
    if any(x in s for x in ("BTC","ETH","BITCOIN","ETHEREUM")): return 1.0
    if any(x in s for x in ("XAU","GOLD")): return 100.0
    if any(x in s for x in ("XAG","SILVER")): return 5000.0
    if any(x in s for x in ("US30","USTEC","NAS","SPX","US500")): return 1.0
    return 100000.0

opens,closes={}, {}
SLIP_FIELDS=["fill_price","requested_entry","signal_price","price_requested",
             "exec_price","execution_ms","latency_ms","fill_ts","request_ts"]
slip_found=set()
with open(TRADES,encoding="utf-8",errors="replace") as f:
    for ln in f:
        ln=ln.strip()
        if not ln: continue
        try: r=json.loads(ln)
        except: continue
        sid=r.get("signal_id")
        if sid is None: continue
        for sf in SLIP_FIELDS:
            if sf in r and r[sf] is not None: slip_found.add(sf)
        if r.get("_type")=="open": opens[sid]=r
        elif r.get("_type")=="close": closes[sid]=r

print("="*60)
print("SLIPPAGE FIELD SCAN (does ANY fill-vs-request data exist?)")
print("="*60)
print("found:", sorted(slip_found) if slip_found else "NONE -> slippage stays in 'unknown' bucket")
print()

buckets=defaultdict(lambda:{"n":0,"div_sum":0.0,"usd":0.0})
rows=[]
for sid,o in opens.items():
    c=closes.get(sid)
    if not c or c.get("net_profit") is None: continue
    if str(sid).startswith("test") or o.get("order_id") in (0,None): continue
    bal=o.get("balance_at_open"); rp=o.get("risk_pct"); sld=o.get("sl_distance")
    lot=o.get("lot"); raw_sl=o.get("raw_sl"); inst_sl=o.get("inst_sl")
    if not (bal and rp and sld and lot): continue
    sym=o.get("symbol","?")
    planned=bal*rp
    realized=sld*lot*_tickval(sym)
    if planned<=0: continue
    div=abs(realized-planned)/planned
    usd=abs(realized-planned)
    sl_widened=(raw_sl is not None and inst_sl is not None and abs(inst_sl-raw_sl)>1e-9)
    intended_lot=(rp*bal)/(sld*_tickval(sym)) if sld>0 else None
    lot_clamped=(intended_lot is not None and abs(lot-intended_lot)/max(intended_lot,1e-9)>0.10)
    if div>0.20:
        if sl_widened and not lot_clamped: cause="SL_floor/widen"
        elif lot_clamped and not sl_widened: cause="lot_clamp"
        elif sl_widened and lot_clamped: cause="SL+lot"
        else: cause="unknown(incl.slippage)"
    else:
        cause="within_20pct"
    buckets[cause]["n"]+=1; buckets[cause]["div_sum"]+=div; buckets[cause]["usd"]+=usd
    rows.append((sym,div,c.get("mae"),c.get("mfe"),sld))

print("="*60); print("DIVERGENCE ATTRIBUTION (why planned != realized risk)"); print("="*60)
print(f"{'cause':24}{'n':>5}{'avg_div':>9}{'$impact':>10}")
for cause,b in sorted(buckets.items(),key=lambda kv:-kv[1]["usd"]):
    ad=b["div_sum"]/b["n"] if b["n"] else 0
    print(f"{cause:24}{b['n']:>5}{ad:>9.2f}{b['usd']:>10.0f}")

def pctl(xs,p):
    if not xs: return None
    xs=sorted(xs); k=(len(xs)-1)*p/100; lo=int(k); hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(k-lo)
mae_r=[m/s for _,_,m,_,s in rows if m is not None and s]
mfe_r=[m/s for _,_,_,m,s in rows if m is not None and s]
print(); print("="*60); print("MAE_R / MFE_R DISTRIBUTION (stop & target placement)"); print("="*60)
for name,xs in [("MAE_R",mae_r),("MFE_R",mfe_r)]:
    if xs:
        print(f"{name}: mean={st.mean(xs):.2f}  median={pctl(xs,50):.2f}  "
              f"75th={pctl(xs,75):.2f}  95th={pctl(xs,95):.2f}  max={max(xs):.2f}")
print(f"\n(MAE_R>1.0 means adverse move exceeded the initial stop distance)")
