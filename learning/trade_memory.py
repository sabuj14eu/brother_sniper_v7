import json,os,logging,threading
from dataclasses import dataclass,asdict,field
from datetime import datetime,timezone
from typing import Optional

log=logging.getLogger("sniper.memory")
MEMORY_FILE="learning/trades.jsonl"
_write_lock=threading.Lock()

@dataclass
class TradeRecord:
    signal_id:str; order_id:Optional[int]; symbol:str; direction:str; timestamp_open:str
    entry:float; raw_sl:float; inst_sl:float; tp:float; sl_distance:float; tp_distance:float; rr:float
    session:str; utc_hour:int; day_of_week:int; atr:Optional[float]; atr_ratio:Optional[float]
    fakeout_pad:float; sl_method:str; htf_trend:Optional[str]; trend_aligned:Optional[bool]
    news_minutes:Optional[int]; pine_score:Optional[int]; ai_score:int; score_breakdown:dict
    balance_at_open:float; equity_pct:float; risk_pct:float; lot:float
    timestamp_close:Optional[str]=None; close_price:Optional[float]=None
    gross_profit:Optional[float]=None; swap:Optional[float]=None; commission:Optional[float]=None
    net_profit:Optional[float]=None; won:Optional[bool]=None; outcome_ratio:Optional[float]=None
    retail_sl_would_have_died:Optional[bool]=None
    # ── v8 / TASK 8 additions ─────────────────────────────────────────────
    asset_class:Optional[str]=None              # metals|crypto|forex|other
    breakout_prob:Optional[int]=None            # 0-100 from v9.7 Pine
    breakout_strength:Optional[str]=None        # Strong|Building|Weak|Fake
    breakout_dir:Optional[str]=None             # UP|DOWN|NONE
    hold_time_seconds:Optional[float]=None      # filled at close
    # Reserved fields (null until populated by future stages):
    spread_at_entry:Optional[float]=None
    dxy_value:Optional[float]=None
    usdjpy_direction:Optional[str]=None
    signal_age_bars:Optional[int]=None
    regime:Optional[str]=None
    mae:Optional[float]=None                    # max adverse excursion (needs poll loop)
    mfe:Optional[float]=None                    # max favorable excursion (needs poll loop)
    version:str="v8"

def open_trade(record:TradeRecord):
    d=asdict(record); d["_type"]="open"; _append_raw(d)
    log.info("MEMORY open: %s %s", record.signal_id, record.symbol)

def close_trade(signal_id,close_price,gross_profit,swap,commission,hold_time_seconds=None,mae=None,mfe=None,
                be_done=None,partial_done=None):
    # 08-01 [TASK-1 FIX] be_done/partial_done: the monitor set these on the
    # tracked dict but they were dropped at clear_open_trade -- scorecard.py
    # counted a field NO producer emitted ("breakeven fired: 0" forever while
    # logs showed 33 [BE] lines). Append-only: old rows simply lack the keys.
    net=gross_profit+swap+commission
    rec={"_type":"close","signal_id":signal_id,
         "timestamp_close":datetime.now(timezone.utc).isoformat(),
         "close_price":close_price,"gross_profit":gross_profit,
         "swap":swap,"commission":commission,
         "net_profit":net,"won":net>0,"version":"v8"}
    if hold_time_seconds is not None:
        rec["hold_time_seconds"]=round(hold_time_seconds,1)
    if mae is not None:
        rec["mae"]=mae
    if mfe is not None:
        rec["mfe"]=mfe
    if be_done is not None:
        rec["be_done"]=bool(be_done)
    if partial_done is not None:
        rec["partial_done"]=bool(partial_done)
    _append_raw(rec)
    log.info("MEMORY close: %s net=%.2f hold=%ss", signal_id, net, rec.get("hold_time_seconds","?"))

def _append_raw(data):
    os.makedirs(os.path.dirname(MEMORY_FILE),exist_ok=True)
    with _write_lock:
        with open(MEMORY_FILE,"a",encoding="utf-8") as f:
            f.write(json.dumps(data,default=str)+"\n")

def load_all():
    if not os.path.exists(MEMORY_FILE): return []
    opens={}; closes={}
    with open(MEMORY_FILE,encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try:
                rec=json.loads(line); sid=rec.get("signal_id","")
                if rec.get("_type")=="open": opens[sid]=rec
                elif rec.get("_type")=="close": closes[sid]=rec
            except: continue
    merged=[]
    for sid,op in opens.items():
        row=dict(op)
        if sid in closes: row.update(closes[sid])
        merged.append(row)
    return merged

def get_recent(n=50):
    return [r for r in load_all() if r.get("net_profit") is not None][-n:]

def stats_summary(n=50):
    recent=get_recent(n)
    if not recent: return {"trades":0}
    wins=[r for r in recent if r.get("won")]
    losses=[r for r in recent if not r.get("won")]
    wr=len(wins)/len(recent)*100
    avg_win=sum(r.get("net_profit",0) for r in wins)/max(len(wins),1)
    avg_loss=sum(r.get("net_profit",0) for r in losses)/max(len(losses),1)
    exp=round((wr/100*avg_win)+((1-wr/100)*avg_loss),2)
    return {"trades":len(recent),"win_rate":round(wr,1),
            "avg_win":round(avg_win,2),"avg_loss":round(avg_loss,2),"expectancy":exp}
