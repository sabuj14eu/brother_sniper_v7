#!/usr/bin/env bash
cd /home/shyam/brother_sniper_v7
echo "=== the EXISTING news gate logic (424-445) — what window does it block? ==="
sed -n '424,448p' bot.py
echo ""
echo "=== what news_mins values did the 6 near-news LOSERS actually have? ==="
python3 - << 'PY'
import json
opens={}
for ln in open("learning/trades.jsonl"):
    ln=ln.strip()
    if not ln: continue
    try: r=json.loads(ln)
    except: continue
    if r.get("_type")=="open": opens[r.get("signal_id")]=r
closes={}
for ln in open("learning/trades.jsonl"):
    ln=ln.strip()
    if not ln: continue
    try: r=json.loads(ln)
    except: continue
    if r.get("_type")=="close": closes[r.get("signal_id")]=r
print("near-news trades (news_minutes < 30) and their outcomes:")
for sid,o in opens.items():
    nm=o.get("news_minutes")
    if nm is not None and nm<30:
        c=closes.get(sid,{})
        net=c.get("net_profit")
        print(f"  {o.get('symbol','?'):8} {o.get('direction','?'):5} news_min={nm:>4} net={net} ver={o.get('version')}")
PY
