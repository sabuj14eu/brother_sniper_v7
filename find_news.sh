#!/usr/bin/env bash
cd /home/shyam/brother_sniper_v7
echo "=== where news_mins is computed + used ==="
grep -n "news_mins\|news_minutes\|news_window\|nearest.*news\|ff_calendar\|_news" bot.py | head -25
echo ""
echo "=== the EV gate / filter return points (so I place the news gate BEFORE them) ==="
grep -n 'return {"status":"blocked"\|return {"status":"rejected"\|return {"status":"filtered"\|ev_gate_passed\|filt.passed' bot.py | head
echo ""
echo "=== show the block just BEFORE score_signal (where news_mins is in scope) ==="
sed -n '820,845p' bot.py
