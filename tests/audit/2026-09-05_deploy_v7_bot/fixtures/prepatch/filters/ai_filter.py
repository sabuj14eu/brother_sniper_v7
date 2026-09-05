import logging, os, time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("sniper.filter")
_WEIGHT_RELOAD_INTERVAL = 6*3600
_weights_loaded_at = 0.0
_current_weights = {}
_current_threshold = 5

def _load_weights_if_stale():
    global _weights_loaded_at,_current_weights,_current_threshold
    if time.time()-_weights_loaded_at>_WEIGHT_RELOAD_INTERVAL:
        try:
            from learning.weight_engine import load_weights
            data=load_weights()
            _current_weights=data["weights"]; _current_threshold=data["threshold"]
            _weights_loaded_at=time.time()
        except Exception as e:
            log.warning(f"[FILTER] Weight load failed: {e}")
            _current_weights={"session":1.0,"news":1.0,"rr":1.0,"atr_context":1.0,"trend":1.0,"volatility":1.0}
            _current_threshold=5; _weights_loaded_at=time.time()

FACTOR_MAX={"session":25,"news":20,"rr":20,"atr_context":15,"trend":10,"volatility":10}

@dataclass
class FilterResult:
    score:int; passed:bool; breakdown:dict; reason:str
    session:str; recommended:bool; threshold:int; regime:str; weights_age:str

def score_signal(symbol,direction,entry,sl_price,tp,regime_result=None,atr=None,htf_trend=None,news_minutes=None,custom_score=None,signal_id=None):
    _load_weights_if_stale()
    weights=_current_weights; threshold=_current_threshold
    regime_name="UNKNOWN"
    if regime_result is not None:
        regime_name=regime_result.regime  # PILOT MODE: ignore regime threshold override
    now_utc=datetime.now(timezone.utc); hour=now_utc.hour
    session=_get_session(hour); breakdown={}
    raw_session={"overlap":25,"london":20,"new_york":18,"asian":10,"dead":0}
    s1=min(round(raw_session.get(session,10)*weights.get("session",1.0)),FACTOR_MAX["session"])
    breakdown["session"]={"score":s1,"max":FACTOR_MAX["session"],"detail":session}
    if news_minutes is None: s2_raw,nd=15,"unknown"
    elif news_minutes<30: s2_raw,nd=0,f"{news_minutes}m-danger"
    elif news_minutes<60: s2_raw,nd=8,f"{news_minutes}m-caution"
    elif news_minutes<120: s2_raw,nd=14,f"{news_minutes}m-watchful"
    else: s2_raw,nd=20,"clear"
    s2=min(round(s2_raw*weights.get("news",1.0)),FACTOR_MAX["news"])
    breakdown["news"]={"score":s2,"max":FACTOR_MAX["news"],"detail":nd}
    sl_dist=abs(entry-sl_price); tp_dist=abs(tp-entry)
    rr=(tp_dist/sl_dist) if sl_dist>0 else 0
    rr_raw=20 if rr>=3.0 else 16 if rr>=2.0 else 10 if rr>=1.5 else 4 if rr>=1.0 else 0
    s3=min(round(rr_raw*weights.get("rr",1.0)),FACTOR_MAX["rr"])
    breakdown["rr"]={"score":s3,"max":FACTOR_MAX["rr"],"detail":f"1:{rr:.2f}"}
    if atr and atr>0 and sl_dist>0:
        ar=sl_dist/atr
        atr_raw=15 if 0.8<=ar<=2.0 else 10 if 0.5<=ar<0.8 else 8 if 2.0<ar<=3.0 else 2
        atr_det=f"ratio={ar:.2f}"
    else: atr_raw,atr_det=12,"no ATR"  # P0.5: neutral when blind, not penalty
    s4=min(round(atr_raw*weights.get("atr_context",1.0)),FACTOR_MAX["atr_context"])
    breakdown["atr_context"]={"score":s4,"max":FACTOR_MAX["atr_context"],"detail":atr_det}
    if htf_trend is None: s5_raw,td=5,"unknown"
    elif htf_trend.upper()==direction.upper().replace("BUY","UP").replace("SELL","DOWN"): s5_raw,td=10,f"with({htf_trend})"
    elif htf_trend=="RANGE": s5_raw,td=6,"ranging"
    else: s5_raw,td=0,f"counter({htf_trend})"
    s5=min(round(s5_raw*weights.get("trend",1.0)),FACTOR_MAX["trend"])
    breakdown["trend"]={"score":s5,"max":FACTOR_MAX["trend"],"detail":td}
    vol_raw={"overlap":10,"london":9,"new_york":8,"asian":5,"dead":1}.get(session,5)
    s6=min(round(vol_raw*weights.get("volatility",1.0)),FACTOR_MAX["volatility"])
    breakdown["volatility"]={"score":s6,"max":FACTOR_MAX["volatility"],"detail":session}
    base=s1+s2+s3+s4+s5+s6
    if custom_score is not None:
        cs=max(0,min(100,int(custom_score))); final=round(base*0.70+cs*0.30)
        breakdown["pine_score"]={"score":cs,"detail":"30% blend"}
    else: final=base
    # [F8 2026-07-02] COUNTER-TREND PENALTY: the old 10-point trend factor let a
    # confirmed counter-trend trade keep ~90% of its score — arithmetically the
    # SELL-side disease (SELL PF 0.54, WR ~19%). A confirmed counter-trend signal
    # now keeps only 65% of its score; aligned/range/unknown are untouched.
    if td.startswith("counter"):
        # [F8-DIAL 08-01, OFF BY DEFAULT] evidence-gated tightening 0.65 -> 0.50.
        # Flip with F8_CT_50=true in .env after weekend review approves.
        # Evidence to flip: counter-trend trades since F8 (07-02) still PF<0.9
        # at n>=20 (counter-trend is the #1 documented loss driver, SELL -406).
        _ct_mult = 0.5 if os.getenv("F8_CT_50", "false").lower() in ("1", "true", "yes") else 0.65
        final=round(final*_ct_mult)
        breakdown["counter_trend_penalty"]={"detail":f"final ×{_ct_mult} (F8) — confirmed counter-trend"}
    final=max(0,min(100,final)); passed=final>=threshold; recommended=final>=threshold+15
    flags=[]
    if s1<15: flags.append(f"session({session})")
    if s2<10: flags.append("news")
    if s3<10: flags.append(f"RR(1:{rr:.1f})")
    if atr and atr>0 and s4<8: flags.append("ATR")  # P0.5: no flag on missing data
    if s5==0: flags.append("counter-trend")
    reason=f"Score {final}/{threshold} - {'strong' if recommended else 'ok' if passed else 'blocked'}. {', '.join(flags)}"
    try:
        from learning.weight_engine import load_weights
        w_age=load_weights().get("updated_at","never")
    except Exception: w_age="never"
    log.info(f"[FILTER] {symbol} {direction}: {final}/{threshold} passed={passed} regime={regime_name}")
    # [F6 2026-07-02] never let the AI override a news-flagged block — trading
    # into a high-impact window on LLM confidence is how "soft filter" becomes
    # "no filter". Session/RR blocks remain overridable as designed.
    if not passed and "news" in flags:
        log.info(f"[FILTER] {symbol} {direction}: news-flagged block — AI override disabled")
    elif not passed:
        try:
            from filters.deepseek_vote import deepseek_tiebreak
            _ctx={"signal_id":signal_id,"symbol":symbol,"direction":direction,"entry":entry,"sl":sl_price,"tp":tp,
                  "rule_score":final,"threshold":threshold,"session":session,"regime":regime_name,
                  "htf_trend":htf_trend,"atr":atr,"flags":flags,"breakdown":breakdown}
            _v=deepseek_tiebreak(_ctx)
            if _v is not None:
                _take,_conf,_dsreason=_v
                breakdown["deepseek"]={"take":_take,"confidence":_conf,"reason":_dsreason}
                if _take and _conf>=60:
                    passed=True
                    reason=f"AI OVERRIDE (conf {_conf}): {_dsreason} | was: {reason}"
                    log.info(f"[FILTER] {symbol} {direction}: DeepSeek OVERRODE block conf={_conf}")
                else:
                    reason=f"{reason} | AI agreed block (conf {_conf})"
        except Exception as _e:
            log.warning(f"[FILTER] DeepSeek hook error: {_e}")
    return FilterResult(score=final,passed=passed,breakdown=breakdown,reason=reason,session=session,recommended=recommended,threshold=threshold,regime=regime_name,weights_age=w_age)

def _get_session(h=None):
    # [F9 2026-07-02] DST-aware sessions. Old table was static UTC ("new_york"
    # starting 16:00 UTC = noon in NY all summer), which mislabeled sessions,
    # cluster keys and the Asia-bleed analysis. `h` kept for call compatibility
    # but ignored — real exchange timezones are authoritative.
    from zoneinfo import ZoneInfo
    now  = datetime.now(timezone.utc)
    ldn  = now.astimezone(ZoneInfo("Europe/London"))
    ny   = now.astimezone(ZoneInfo("America/New_York"))
    tky  = now.astimezone(ZoneInfo("Asia/Tokyo"))
    ldn_h = ldn.hour + ldn.minute/60.0
    ny_h  = ny.hour  + ny.minute/60.0
    ldn_open = 8.0 <= ldn_h < 16.5          # LSE 08:00-16:30 local
    ny_open  = 9.5 <= ny_h  < 16.0          # NYSE 09:30-16:00 local
    if ldn_open and ny_open: return "overlap"
    if ldn_open:             return "london"
    if ny_open:              return "new_york"
    if 9 <= tky.hour < 18:   return "asian"  # Tokyo 09:00-18:00 local
    return "dead"