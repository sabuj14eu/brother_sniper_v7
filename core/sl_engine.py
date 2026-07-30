import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("sniper.sl_engine")

FAKEOUT_PAD = {"GOLD":8.0,"SILVER":0.12,"BITCOIN":300.0,"ETHEREUM":25.0,"LITECOIN":1.0,"RIPPLE":0.008,"USDJPY":0.05,"EURUSD":0.0005,"GBPUSD":0.0005,"AUDUSD":0.0005,"NZDUSD":0.0005,"USDCAD":0.0005,"USDCHF":0.0005,"US30":3.0,"USTEC":3.0}
ATR_MULTIPLIER = 1.2
MIN_SL_PCT = {"GOLD":0.010,"SILVER":0.010,"BITCOIN":0.012,"ETHEREUM":0.015,"LITECOIN":0.020,"RIPPLE":0.020,"USDJPY":0.0010,"EURUSD":0.0010,"GBPUSD":0.0010,"AUDUSD":0.0010,"NZDUSD":0.0010,"USDCAD":0.0010,"USDCHF":0.0010,"US30":0.0015,"USTEC":0.0015}  # metals floors raised 2026-06-26: <1% stops bled -432 (17%WR) vs >1% +280 (80%WR)
MAX_SL_PCT = {"GOLD":0.040,"SILVER":0.050,"BITCOIN":0.100,"ETHEREUM":0.120,"LITECOIN":0.060,"RIPPLE":0.060,"USDJPY":0.008,"EURUSD":0.008,"GBPUSD":0.008,"AUDUSD":0.008,"NZDUSD":0.008,"USDCAD":0.008,"USDCHF":0.008,"US30":0.015,"USTEC":0.015}

@dataclass
class SLResult:
    sl_price:float; sl_distance:float; method:str; atr_used:float
    fakeout_pad:float; within_limits:bool; rejection_reason:str

def calculate_institutional_sl(symbol,direction,entry,raw_sl,atr=None,swing_low=None,swing_high=None):
    pad=FAKEOUT_PAD.get(symbol,5.0)
    atr_val=atr if atr and atr>0 else _estimate_atr(symbol,entry)
    atr_buf=atr_val*ATR_MULTIPLIER
    if direction=="BUY":
        anchor=swing_low if swing_low and swing_low<entry else raw_sl
        sl_raw=anchor-atr_buf-pad
    else:
        anchor=swing_high if swing_high and swing_high>entry else raw_sl
        sl_raw=anchor+atr_buf+pad
    sl_distance=abs(entry-sl_raw)
    method="structure+atr+pad" if ((direction=="BUY" and swing_low) or (direction=="SELL" and swing_high)) else "atr+pad"
    min_dist=entry*MIN_SL_PCT.get(symbol,0.008)
    max_dist=entry*MAX_SL_PCT.get(symbol,0.030)
    rejection=""
    if sl_distance<min_dist:
        sl_distance=min_dist
        sl_raw=entry-sl_distance if direction=="BUY" else entry+sl_distance
        method="min_pct_floor"
    if sl_distance>max_dist:
        rejection=f"SL distance {sl_distance:.2f} exceeds max {max_dist:.2f}. Setup too risky."
    sl_final=round(sl_raw,2)
    log.info(f"[SL] {symbol} {direction}: entry={entry} final_sl={sl_final} dist={sl_distance:.2f} method={method}")
    return SLResult(sl_price=sl_final,sl_distance=sl_distance,method=method,atr_used=atr_val,fakeout_pad=pad,within_limits=not rejection,rejection_reason=rejection)

def _estimate_atr(symbol,entry):
    pct={"GOLD":0.0085,"SILVER":0.0120,"BITCOIN":0.0300,"ETHEREUM":0.0350,"LITECOIN":0.0400,"RIPPLE":0.0350,"US30":0.005,"USTEC":0.008}.get(symbol,0.010)
    return entry*pct

def validate_rr(entry,sl_price,tp,direction,min_rr=1.5):
    sl_dist=abs(entry-sl_price); tp_dist=abs(tp-entry)
    if sl_dist<=0: return 0.0,"SL distance is zero"
    rr=round(tp_dist/sl_dist,2)
    if rr<min_rr: return rr,f"R:R {rr:.2f} below minimum {min_rr}."
    if direction=="BUY" and tp<=entry: return 0.0,f"TP {tp} must be above entry {entry}"
    if direction=="SELL" and tp>=entry: return 0.0,f"TP {tp} must be below entry {entry}"
    return rr,""