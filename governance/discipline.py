import json,os,logging,time
from datetime import datetime,timezone,timedelta
from dataclasses import dataclass
from typing import Optional

log=logging.getLogger("sniper.discipline")
DISCIPLINE_FILE="governance/discipline_state.json"
MAX_WEIGHT_DELTA=0.25
FREEZE_DD_THRESHOLD=0.04
DECAY_DAYS=30
DECAY_CAP=0.40
MIN_EV_FLOOR=-0.5
REGIME_CONF_THRESHOLDS={"full":0.65,"reduced":0.40,"minimal":0.00}

@dataclass
class DisciplineState:
    weights_frozen:bool=False; freeze_reason:str=""; freeze_started_at:str=""
    last_calibration_at:str=""; daily_calibrations:int=0; cal_date:str=""; total_weight_updates:int=0

@dataclass
class DisciplineResult:
    allow_calibration:bool; calibration_reason:str; position_scale:float
    position_reason:str; ev_gate_passed:bool; ev_gate_reason:str; frozen:bool

class DisciplineGovernor:
    def __init__(self):
        self.state=self._load()
    def _load(self):
        os.makedirs(os.path.dirname(DISCIPLINE_FILE),exist_ok=True)
        if os.path.exists(DISCIPLINE_FILE):
            try:
                with open(DISCIPLINE_FILE) as f: d=json.load(f)
                return DisciplineState(**{k:v for k,v in d.items() if k in DisciplineState.__dataclass_fields__})
            except: pass
        return DisciplineState()
    def _save(self):
        import dataclasses
        with open(DISCIPLINE_FILE,"w") as f: json.dump(dataclasses.asdict(self.state),f,indent=2)
    def apply_weight_limits(self,old_weights,proposed_weights):
        clamped={}; messages=[]
        for factor,proposed in proposed_weights.items():
            old=old_weights.get(factor,1.0); delta=proposed-old
            if abs(delta)>MAX_WEIGHT_DELTA:
                cv=old+(MAX_WEIGHT_DELTA if delta>0 else -MAX_WEIGHT_DELTA)
                clamped[factor]=round(cv,4); messages.append(f"{factor}:{old:.3f}->{cv:.3f}(clamped)")
            else: clamped[factor]=proposed
        return clamped,messages
    def check_freeze(self,daily_dd_pct):
        if daily_dd_pct>FREEZE_DD_THRESHOLD:
            if not self.state.weights_frozen:
                self.state.weights_frozen=True; self.state.freeze_reason=f"DD {daily_dd_pct*100:.1f}%>{FREEZE_DD_THRESHOLD*100:.0f}%"
                self.state.freeze_started_at=datetime.now(timezone.utc).isoformat(); self._save()
            return True
        elif self.state.weights_frozen and daily_dd_pct<FREEZE_DD_THRESHOLD*0.5:
            self.state.weights_frozen=False; self.state.freeze_reason=""; self._save()
        return self.state.weights_frozen
    def apply_decay(self,trades):
        now=datetime.now(timezone.utc); result=[]
        for t in trades:
            try:
                ts=datetime.fromisoformat(t.get("timestamp_open",""))
                if ts.tzinfo is None: ts=ts.replace(tzinfo=timezone.utc)
                age=(now-ts).days
                w=DECAY_CAP if age>DECAY_DAYS else 1.0-(1.0-DECAY_CAP)*(age/DECAY_DAYS)
            except: w=1.0
            t=dict(t); t["_cal_weight"]=round(w,3); result.append(t)
        return result
    def check_ev_gate(self,ev):
        if ev<MIN_EV_FLOOR: return False,f"EV ${ev:.2f}<floor ${MIN_EV_FLOOR:.2f}"
        return True,f"EV ${ev:.2f} OK"
    def regime_position_scale(self,confidence):
        if confidence>=REGIME_CONF_THRESHOLDS["full"]: return 1.00,f"conf {confidence:.0%}->full"
        elif confidence>=REGIME_CONF_THRESHOLDS["reduced"]: return 0.75,f"conf {confidence:.0%}->75%"
        else: return 0.50,f"conf {confidence:.0%}->50%"
    def pre_calibration_check(self,daily_dd_pct):
        frozen=self.check_freeze(daily_dd_pct)
        if frozen: return False,f"Frozen: {self.state.freeze_reason}"
        return True,"OK"
    def pre_trade_check(self,ev,regime_confidence,daily_dd_pct):
        frozen=self.check_freeze(daily_dd_pct)
        ev_ok,ev_reason=self.check_ev_gate(ev)
        pos_scale,pos_reason=self.regime_position_scale(regime_confidence)
        return DisciplineResult(allow_calibration=not frozen,calibration_reason=self.state.freeze_reason if frozen else "ok",position_scale=pos_scale,position_reason=pos_reason,ev_gate_passed=ev_ok,ev_gate_reason=ev_reason,frozen=frozen)
    def reset_hard_stop(self): self.state.weights_frozen=False; self._save()
    def status_dict(self):
        import dataclasses
        return {**dataclasses.asdict(self.state),"max_weight_delta":MAX_WEIGHT_DELTA,"freeze_threshold_pct":FREEZE_DD_THRESHOLD*100,"decay_days":DECAY_DAYS,"ev_floor":MIN_EV_FLOOR}