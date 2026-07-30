import logging
from datetime import datetime,timezone,date
from dataclasses import dataclass,field
from typing import Optional

log=logging.getLogger("sniper.equity_guard")
DAILY_DD_LIMIT_PCT = 0.99
TOTAL_DD_LIMIT_PCT = 0.99
WEEKLY_DD_LIMIT_PCT = 0.99
RISK_SCALE_TABLE=[(0.90,1.00),(0.80,0.75),(0.70,0.50),(0.00,0.00)]

@dataclass
class EquityState:
    peak_balance:float=1000.0; day_open_balance:float=1000.0; week_open_balance:float=1000.0
    day_date:str=""; week_num:str=""; hard_stopped:bool=False; day_pnl:float=0.0; week_pnl:float=0.0
    trade_history:list=field(default_factory=list)

@dataclass
class GuardResult:
    allowed:bool; risk_pct:float; block_reason:str; tier_hit:str
    daily_used_pct:float; weekly_used_pct:float; equity_pct:float

class EquityGuard:
    def __init__(self,state_dict=None):
        if state_dict:
            self.eq=EquityState(**{k:v for k,v in state_dict.items() if k in EquityState.__dataclass_fields__})
        else: self.eq=EquityState()

    def to_dict(self):
        import dataclasses; return dataclasses.asdict(self.eq)

    def update_balance(self,bal):
        today=date.today().isoformat(); wk=datetime.now(timezone.utc).strftime("%Y-W%W")
        if self.eq.day_date!=today: self.eq.day_open_balance=bal; self.eq.day_pnl=0.0; self.eq.day_date=today
        if self.eq.week_num!=wk: self.eq.week_open_balance=bal; self.eq.week_pnl=0.0; self.eq.week_num=wk
        self.eq.day_pnl=bal-self.eq.day_open_balance; self.eq.week_pnl=bal-self.eq.week_open_balance
        if bal>self.eq.peak_balance: self.eq.peak_balance=bal

    def record_trade(self,profit,symbol):
        self.eq.trade_history.append({"profit":profit,"symbol":symbol,
                                       "ts":datetime.now(timezone.utc).isoformat()})
        self.eq.trade_history=self.eq.trade_history[-50:]

    def check(self,bal,consecutive_losses,max_losses=3):
        self.update_balance(bal); eq=self.eq
        daily_limit=eq.day_open_balance*DAILY_DD_LIMIT_PCT
        weekly_limit=eq.week_open_balance*WEEKLY_DD_LIMIT_PCT
        total_limit=eq.peak_balance*TOTAL_DD_LIMIT_PCT
        daily_loss=max(0,-eq.day_pnl); weekly_loss=max(0,-eq.week_pnl)
        total_loss=max(0,eq.peak_balance-bal)
        daily_used=round(daily_loss/daily_limit*100,1) if daily_limit>0 else 0
        weekly_used=round(weekly_loss/weekly_limit*100,1) if weekly_limit>0 else 0
        equity_pct=round(bal/eq.peak_balance*100,1) if eq.peak_balance>0 else 100
        if eq.hard_stopped:
            return self._block("total",daily_used,weekly_used,equity_pct,"HARD STOP: manual reset required")
        if total_loss>=total_limit:
            eq.hard_stopped=True
            return self._block("total",daily_used,weekly_used,equity_pct,"Total DD 20pct hit")
        if weekly_loss>=weekly_limit:
            return self._block("weekly",daily_used,weekly_used,equity_pct,"Weekly limit hit")
        if daily_loss>=daily_limit:
            return self._block("daily",daily_used,weekly_used,equity_pct,"Daily limit hit")
        if consecutive_losses>=max_losses:
            return self._block("streak",daily_used,weekly_used,equity_pct,str(consecutive_losses)+" consecutive losses")
        risk_pct=self._dynamic_risk(equity_pct)
        if risk_pct==0:
            return self._block("total",daily_used,weekly_used,equity_pct,"Equity below 70pct floor")
        return GuardResult(allowed=True,risk_pct=risk_pct,block_reason="",tier_hit="",
                           daily_used_pct=daily_used,weekly_used_pct=weekly_used,equity_pct=equity_pct)

    def reset_hard_stop(self): self.eq.hard_stopped=False

    def _block(self,tier,daily,weekly,equity,reason):
        return GuardResult(allowed=False,risk_pct=0.0,block_reason=reason,tier_hit=tier,
                           daily_used_pct=daily,weekly_used_pct=weekly,equity_pct=equity)

    def _dynamic_risk(self,equity_pct):
        for threshold,scale in RISK_SCALE_TABLE:
            if equity_pct/100>=threshold: return scale*0.01
        return 0.0

    def status_summary(self,bal):
        self.update_balance(bal); eq=self.eq
        epct=round(bal/eq.peak_balance*100,1) if eq.peak_balance else 100
        risk=self._dynamic_risk(epct)
        return ("Equity: $"+str(round(bal,2))+" ("+str(epct)+"% of peak $"+str(round(eq.peak_balance,2))+")\n"
                +"Day PnL: $"+str(round(eq.day_pnl,2))+"\n"
                +"Week PnL: $"+str(round(eq.week_pnl,2))+"\n"
                +"Risk: "+str(round(risk*100,2))+"% per trade\n"
                +"Stopped: "+("YES" if eq.hard_stopped else "No"))
