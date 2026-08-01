#!/usr/bin/env python3
"""Does the news agent actually help trade decisions, or just decorate?
Read-only. Checks: (1) feed alive, (2) news score in trade path, (3) does
news context correlate with win/loss outcomes."""
import json, os, sys
from collections import defaultdict
BASE=os.environ.get("BS7_BASE","/home/shyam/brother_sniper_v7")
TRADES=os.path.join(BASE,"learning","trades.jsonl")

# ---- 1. is the calendar feed reachable + fresh? ----
print("="*72); print("[1] NEWS FEED — alive and fresh?"); print("="*72)
try:
    import urllib.request
    req=urllib.request.Request("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                               headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=10) as r:
        data=json.loads(r.read().decode())
    print(f"    feed OK: {len(data)} events this week")
    # show next few high-impact
    hi=[e for e in data if str(e.get("impact","")).lower() in ("high","red")]
    print(f"    high-impact events: {len(hi)}")
    for e in hi[:4]:
        print(f"      {e.get('date','?')[:16]} {e.get('country','?')} {e.get('title','?')[:40]} [{e.get('impact')}]")
except Exception as e:
    print(f"    FEED FAILED: {e}  -> news scoring would fall back to 'clear' (blind)")

# ---- 2/3. does news score appear in trades + correlate with outcome? ----
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

print("\n"+"="*72); print("[2] IS NEWS IN THE TRADE RECORD?"); print("="*72)
sample=next((o for o in opens.values() if o.get("order_id") not in (0,None)
             and not str(o.get("signal_id","")).startswith("test")), {})
nm=sample.get("news_minutes"); sb=sample.get("score_breakdown",{}) or {}
print(f"    news_minutes present: {nm is not None}  (sample value={nm})")
print(f"    news in score_breakdown: {'news' in sb}")
if "news" in sb:
    print(f"    sample news score: {sb['news']}")

print("\n"+"="*72); print("[3] DOES NEWS CONTEXT CORRELATE WITH OUTCOME?"); print("="*72)
# bucket trades by news proximity (news_minutes = mins to nearest event) and by news score
buckets=defaultdict(lambda:{"n":0,"win":0,"pnl":0.0})
score_buckets=defaultdict(lambda:{"n":0,"win":0,"pnl":0.0})
for sid,o in opens.items():
    c=closes.get(sid)
    if not c or c.get("net_profit") is None: continue
    if str(sid).startswith("test") or o.get("order_id") in (0,None): continue
    net=float(c["net_profit"]); won=net>0
    nm=o.get("news_minutes")
    if nm is not None:
        if nm<30: b="0-30min (near news)"
        elif nm<120: b="30-120min"
        elif nm<480: b="2-8hr"
        else: b="8hr+ (clear)"
        buckets[b]["n"]+=1; buckets[b]["win"]+=won; buckets[b]["pnl"]+=net
    sb=o.get("score_breakdown",{}) or {}
    ns=sb.get("news",{}).get("score") if isinstance(sb.get("news"),dict) else None
    if ns is not None:
        score_buckets[ns]["n"]+=1; score_buckets[ns]["win"]+=won; score_buckets[ns]["pnl"]+=net

print("  BY PROXIMITY TO NEWS (does trading near news lose?):")
print(f"    {'bucket':22}{'n':>4}{'WR':>6}{'avg$':>9}")
for b in ["0-30min (near news)","30-120min","2-8hr","8hr+ (clear)"]:
    if b in buckets:
        d=buckets[b]; wr=d["win"]/d["n"] if d["n"] else 0
        print(f"    {b:22}{d['n']:>4}{wr*100:>5.0f}%{d['pnl']/d['n']:>9.2f}")

print("\n  BY NEWS SCORE (does the news score predict outcome?):")
print(f"    {'news_score':12}{'n':>4}{'WR':>6}{'avg$':>9}")
for s in sorted(score_buckets):
    d=score_buckets[s]; wr=d["win"]/d["n"] if d["n"] else 0
    print(f"    {str(s):12}{d['n']:>4}{wr*100:>5.0f}%{d['pnl']/d['n']:>9.2f}")

print("\nREAD: if WR is flat across news buckets -> news isn't separating win/loss (decoration).")
print("      if near-news WR is much worse -> news SHOULD gate but may not be.")
print("      if feed FAILED -> news scores are blind 'clear', not real.")
