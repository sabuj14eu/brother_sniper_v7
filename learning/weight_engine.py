import json,os,logging
from datetime import datetime,timezone

log=logging.getLogger("sniper.weights")
WEIGHTS_FILE="learning/weights.json"
MIN_SAMPLES=20; EMA_ALPHA=0.3; MIN_WEIGHT=0.30; MAX_WEIGHT=2.00; DEFAULT_THRESHOLD=5
DEFAULT_WEIGHTS={"session":1.0,"news":1.0,"rr":1.0,"atr_context":1.0,"trend":1.0,"volatility":1.0}

def load_weights():
    if os.path.exists(WEIGHTS_FILE):
        try:
            with open(WEIGHTS_FILE) as f: saved=json.load(f)
            weights=dict(DEFAULT_WEIGHTS)
            weights.update({k:v for k,v in saved.get("weights",{}).items() if k in DEFAULT_WEIGHTS})
            return {"weights":weights,"threshold":saved.get("threshold",DEFAULT_THRESHOLD),
                    "updated_at":saved.get("updated_at","never"),"sample_count":saved.get("sample_count",0)}
        except Exception as e: log.warning("WEIGHTS load error: %s", e)
    return {"weights":dict(DEFAULT_WEIGHTS),"threshold":DEFAULT_THRESHOLD,"updated_at":"never","sample_count":0}

def save_weights(weights,threshold,sample_count,extra=None):
    os.makedirs(os.path.dirname(WEIGHTS_FILE),exist_ok=True)
    data={"weights":weights,"threshold":threshold,
          "updated_at":datetime.now(timezone.utc).isoformat(),
          "sample_count":sample_count,**(extra or {})}
    with open(WEIGHTS_FILE,"w") as f: json.dump(data,f,indent=2)

def recalibrate(daily_dd_pct=0.0,min_samples=MIN_SAMPLES):
    from learning.trade_memory import load_all
    from learning.cluster_engine import rebuild_clusters
    from governance.discipline import DisciplineGovernor
    disc=DisciplineGovernor()
    allowed,reason=disc.pre_calibration_check(daily_dd_pct)
    if not allowed: return {"status":"frozen","reason":reason,"weights":load_weights()["weights"]}
    all_trades=load_all()
    trades=[t for t in all_trades if t.get("net_profit") is not None]
    if len(trades)<min_samples:
        return {"status":"insufficient_data","trades":len(trades),"needed":min_samples,"weights":load_weights()["weights"]}
    trades=disc.apply_decay(trades)
    current=load_weights(); old_weights=dict(current["weights"]); raw_weights=dict(old_weights); report={}
    overall_wr=_overall_wr(trades)
    session_wr=_wr_by_key(trades,"session")
    if session_wr:
        raw_weights["session"]=_factor_weight(session_wr,overall_wr,old_weights["session"])
        report["session"]=session_wr
    old_thresh=current["threshold"]
    # ── Bug #2 fix: threshold FROZEN during data-collection phase (until 100 trades) ──
    # Adaptive drift was choking trade flow (35->38 unbidden, climbs +3 toward 75 ceiling).
    # Pin it so the 100-trade measurement runs at a STABLE filter bar. Re-enable after.
    # Original adaptive logic (restore to un-freeze):
    # new_thresh=min(old_thresh+3,75) if overall_wr<0.40 else max(old_thresh-2,45) if overall_wr>0.60 else old_thresh
    new_thresh=old_thresh
    clamped_weights,clamp_msgs=disc.apply_weight_limits(old_weights,raw_weights)
    if clamp_msgs: report["clamped"]=clamp_msgs
    save_weights(clamped_weights,new_thresh,len(trades))
    rebuild_clusters(trades)
    return {"status":"calibrated","trades_used":len(trades),
            "old_weights":old_weights,"new_weights":clamped_weights,
            "threshold":new_thresh,"report":report}

def format_calibration_telegram(result):
    if result["status"]=="frozen": return "Weights frozen: "+result.get("reason","")
    if result["status"]=="insufficient_data":
        return "Need more trades: "+str(result["trades"])+"/"+str(result["needed"])
    old,new=result["old_weights"],result["new_weights"]
    lines=["Weights recalibrated ("+str(result["trades_used"])+" trades)"]
    for factor,nw in new.items():
        ow=old.get(factor,1.0); delta=nw-ow
        arrow="up" if delta>0.05 else "down" if delta<-0.05 else "same"
        lines.append("  "+factor+": "+str(round(ow,3))+"->"+str(round(nw,3))+" ("+arrow+")")
    return "\n".join(lines)

def _overall_wr(trades):
    if not trades: return 0.5
    ww=sum(t.get("_cal_weight",1.0) for t in trades if t.get("won"))
    wt=sum(t.get("_cal_weight",1.0) for t in trades)
    return ww/wt if wt>0 else 0.5

def _wr_list(trades):
    if not trades: return 0.5
    ww=sum(t.get("_cal_weight",1.0) for t in trades if t.get("won"))
    wt=sum(t.get("_cal_weight",1.0) for t in trades)
    return ww/wt if wt>0 else 0.5

def _wr_by_key(trades,key):
    buckets={}
    for t in trades: buckets.setdefault(str(t.get(key,"?")), []).append(t)
    return {k:{"n":len(v),"win_rate":_wr_list(v)} for k,v in buckets.items() if len(v)>=3}

def _factor_weight(wr_by_bucket,overall_wr,current_w):
    if not wr_by_bucket: return current_w
    best=max(v["win_rate"] for v in wr_by_bucket.values())
    return _clamp(current_w*_ema(best/max(overall_wr,0.01),1.0,EMA_ALPHA))

def _ema(new,old,alpha): return alpha*new+(1-alpha)*old
def _clamp(w): return round(max(MIN_WEIGHT,min(w,MAX_WEIGHT)),4)
