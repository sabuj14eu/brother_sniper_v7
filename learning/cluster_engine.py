import json,os,logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime,timezone

log=logging.getLogger("sniper.cluster")
CLUSTER_FILE="learning/clusters.json"
MIN_CLUSTER_TRADES=8; MIN_EV_CONFIDENCE=0.60

@dataclass
class ClusterStats:
    key:str; symbol:str; session:str; regime:str; vol_state:str; n_trades:int
    win_rate:float; avg_win:float; avg_loss:float; expectancy:float; ev_per_risk:float
    confidence:float; trusted:bool; last_updated:str

@dataclass
class ClusterLookup:
    cluster_key:str; stats:Optional[ClusterStats]; ev:float; trusted:bool; confidence:float; message:str

def get_vol_state(atr_vs_avg):
    if atr_vs_avg is None: return "unknown"
    if atr_vs_avg>2.0: return "spike"
    if atr_vs_avg>1.3: return "high"
    if atr_vs_avg>=0.7: return "normal"
    return "low"

def make_cluster_key(symbol,session,regime,vol_state): return f"{symbol}_{session}_{regime}_{vol_state}"

def lookup_cluster(symbol,session,regime,atr_vs_avg):
    vol_state=get_vol_state(atr_vs_avg); cluster_key=make_cluster_key(symbol,session,regime,vol_state)
    clusters=_load_clusters(); stats=clusters.get(cluster_key)
    if not stats or stats["n_trades"]<MIN_CLUSTER_TRADES:
        n=stats["n_trades"] if stats else 0
        return ClusterLookup(cluster_key=cluster_key,stats=None,ev=0.0,trusted=False,confidence=n/MIN_CLUSTER_TRADES if n>0 else 0.0,message=f"{cluster_key}: {n}/{MIN_CLUSTER_TRADES} trades")
    ev=stats["expectancy"]; conf=min(1.0,stats["n_trades"]/(MIN_CLUSTER_TRADES*3)); trusted=conf>=MIN_EV_CONFIDENCE
    cs=ClusterStats(key=cluster_key,symbol=stats["symbol"],session=stats["session"],regime=stats["regime"],vol_state=stats["vol_state"],n_trades=stats["n_trades"],win_rate=stats["win_rate"],avg_win=stats["avg_win"],avg_loss=stats["avg_loss"],expectancy=stats["expectancy"],ev_per_risk=stats.get("ev_per_risk",0),confidence=conf,trusted=trusted,last_updated=stats.get("last_updated","?"))
    return ClusterLookup(cluster_key=cluster_key,stats=cs,ev=ev,trusted=trusted,confidence=conf,message=f"{cluster_key}: n={stats['n_trades']} wr={stats['win_rate']:.0%} EV=${ev:.2f}")

def rebuild_clusters(trades):
    completed=[t for t in trades if t.get("net_profit") is not None]
    if not completed: return {}
    buckets={}
    for t in completed:
        sym=t.get("symbol","?"); session=t.get("session","?"); regime=t.get("regime","UNKNOWN")
        avs=t.get("atr_vs_avg"); vol_state=get_vol_state(avs)
        key=make_cluster_key(sym,session,regime,vol_state)
        buckets.setdefault(key,[]).append(t)
    clusters={}
    for key,bucket in buckets.items():
        wins=[t for t in bucket if t.get("won")]; losses=[t for t in bucket if not t.get("won")]
        ww=sum(t.get("_cal_weight",1.0) for t in wins); wt=sum(t.get("_cal_weight",1.0) for t in bucket)
        wr=ww/wt if wt>0 else 0
        avg_win=_wmean([t.get("net_profit",0) for t in wins],[t.get("_cal_weight",1.0) for t in wins]) if wins else 0
        avg_loss=_wmean([t.get("net_profit",0) for t in losses],[t.get("_cal_weight",1.0) for t in losses]) if losses else 0
        ev=wr*avg_win+(1-wr)*avg_loss
        parts=key.split("_",3)
        clusters[key]={"key":key,"symbol":parts[0] if len(parts)>0 else "","session":parts[1] if len(parts)>1 else "","regime":parts[2] if len(parts)>2 else "","vol_state":parts[3] if len(parts)>3 else "","n_trades":len(bucket),"win_rate":round(wr,4),"avg_win":round(avg_win,4),"avg_loss":round(avg_loss,4),"expectancy":round(ev,4),"ev_per_risk":0,"last_updated":datetime.now(timezone.utc).isoformat()}
    _save_clusters(clusters); log.info(f"[CLUSTER] Rebuilt {len(clusters)} clusters"); return clusters

def top_clusters(n=10):
    c=_load_clusters(); trusted=[x for x in c.values() if x["n_trades"]>=MIN_CLUSTER_TRADES]
    return sorted(trusted,key=lambda x:x["expectancy"],reverse=True)[:n]

def worst_clusters(n=5):
    c=_load_clusters(); trusted=[x for x in c.values() if x["n_trades"]>=MIN_CLUSTER_TRADES]
    return sorted(trusted,key=lambda x:x["expectancy"])[:n]

def _load_clusters():
    if os.path.exists(CLUSTER_FILE):
        try:
            with open(CLUSTER_FILE) as f: return json.load(f)
        except: pass
    return {}

def _save_clusters(clusters):
    os.makedirs(os.path.dirname(CLUSTER_FILE),exist_ok=True)
    with open(CLUSTER_FILE,"w") as f: json.dump(clusters,f,indent=2)

def _wmean(values,weights):
    if not values: return 0.0
    tw=sum(weights)
    return sum(v*w for v,w in zip(values,weights))/tw if tw>0 else 0.0