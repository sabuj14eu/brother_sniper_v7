import logging
from dataclasses import dataclass
from typing import Optional

log=logging.getLogger("sniper.regime")

@dataclass
class RegimeResult:
    regime:str; confidence:float; atr_multiplier:float; score_threshold:int; risk_scale:float; description:str

REGIME_CONFIG={
    "TREND":{"atr_multiplier":1.2,"score_threshold":50,"risk_scale":1.0},
    "RANGE":{"atr_multiplier":0.9,"score_threshold":58,"risk_scale":0.85},
    "VOLATILE":{"atr_multiplier":1.8,"score_threshold":68,"risk_scale":0.5},
    "UNKNOWN":{"atr_multiplier":1.2,"score_threshold":45,"risk_scale":1.0},
}

def detect_regime(atr_pct=None,atr_vs_avg=None,adx=None,bb_width=None,htf_trend=None):
    votes={"TREND":0,"RANGE":0,"VOLATILE":0}; total_voters=0
    if adx is not None:
        total_voters+=1
        if adx>30: votes["TREND"]+=1.5
        elif adx>20: votes["TREND"]+=0.7
        elif adx<15: votes["RANGE"]+=1.2
        else: votes["RANGE"]+=0.5
    if atr_vs_avg is not None:
        total_voters+=1
        if atr_vs_avg>2.0: votes["VOLATILE"]+=2.0
        elif atr_vs_avg>1.5: votes["VOLATILE"]+=1.0
        elif atr_vs_avg>1.2: votes["TREND"]+=0.8
        elif atr_vs_avg<0.7: votes["RANGE"]+=1.2
        else: votes["TREND"]+=0.3
    if atr_pct is not None:
        total_voters+=1
        if atr_pct>0.025: votes["VOLATILE"]+=1.5
        elif atr_pct>0.015: votes["VOLATILE"]+=0.7
        elif atr_pct<0.005: votes["RANGE"]+=1.0
        else: votes["TREND"]+=0.3
    if bb_width is not None:
        total_voters+=1
        if bb_width>0.04: votes["VOLATILE"]+=1.2
        elif bb_width>0.02: votes["TREND"]+=0.8
        elif bb_width<0.008: votes["RANGE"]+=1.5
        else: votes["RANGE"]+=0.4
    if htf_trend is not None:
        total_voters+=1
        if htf_trend.upper()=="RANGE": votes["RANGE"]+=1.0
        else: votes["TREND"]+=0.8
    if total_voters==0:
        cfg=REGIME_CONFIG["UNKNOWN"]
        return RegimeResult(regime="UNKNOWN",confidence=0.0,atr_multiplier=cfg["atr_multiplier"],score_threshold=cfg["score_threshold"],risk_scale=cfg["risk_scale"],description="No indicators")
    winner=max(votes,key=votes.get); total_vote=sum(votes.values())
    confidence=round(votes[winner]/total_vote,2) if total_vote>0 else 0.5
    cfg=REGIME_CONFIG[winner]
    desc=f"regime={winner} conf={confidence:.2f}"
    if adx: desc+=f" ADX={adx:.1f}"
    if atr_vs_avg: desc+=f" ATR_exp={atr_vs_avg:.2f}x"
    log.info(f"[REGIME] {desc}")
    return RegimeResult(regime=winner,confidence=confidence,atr_multiplier=cfg["atr_multiplier"],score_threshold=cfg["score_threshold"],risk_scale=cfg["risk_scale"],description=desc)