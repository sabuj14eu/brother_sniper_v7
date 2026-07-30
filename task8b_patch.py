#!/usr/bin/env python3
"""
TASK 8 FOLLOW-UP PATCH — Wire breakout_prob/strength/dir + regime + signal_age
to TradeRecord, plus fix the _shutdown_event typo in gunicorn.conf.py.

What this script does (atomic — aborts on any failure, no partial writes):
  1. Backs up bot.py and gunicorn.conf.py
  2. Adds payload extraction for breakout_prob/breakout_strength/breakout_dir
     (after pine_score parsing)
  3. Computes signal_age_seconds from payload "time" field if present
  4. Passes the new fields + regime.regime into the mem_open(TradeRecord(...)) call
  5. Fixes _shutdown_event → _shutdown in gunicorn.conf.py
  6. Validates Python syntax of both files before writing
  7. Reports patch count + rollback command

Run from /home/shyam/brother_sniper_v7/ directory.
"""
import shutil, sys, os, ast
from datetime import datetime

ROOT = "/home/shyam/brother_sniper_v7"
if not os.path.isdir(ROOT):
    print(f"❌ Directory not found: {ROOT}"); sys.exit(1)
os.chdir(ROOT)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
print(f"TASK 8 FOLLOW-UP PATCH — timestamp {ts}\n{'='*60}")

# ── Step 1: Backup ─────────────────────────────────────────────────────────
print("[1/5] Backing up...")
for f in ["bot.py", "gunicorn.conf.py"]:
    if not os.path.exists(f):
        print(f"  ✗ Missing: {f}"); sys.exit(1)
    shutil.copy(f, f"{f}.bak_t8b_{ts}")
    print(f"  ✓ {f}.bak_t8b_{ts}")

# ── Step 2: Read files ─────────────────────────────────────────────────────
with open("bot.py") as f: bot = f.read()
with open("gunicorn.conf.py") as f: gconf = f.read()

n_patches = 0
def patch(content, old, new, label):
    global n_patches
    cnt = content.count(old)
    if cnt == 0:
        print(f"  ✗ FAIL: {label}\n    Pattern not found. ABORTING — no files modified."); sys.exit(1)
    if cnt > 1:
        print(f"  ✗ FAIL: {label}\n    Pattern found {cnt} times (need 1). ABORTING."); sys.exit(1)
    n_patches += 1
    print(f"  ✓ [{n_patches}] {label}")
    return content.replace(old, new)

# ── Step 3: Patch bot.py — add payload extraction for breakout fields ─────
print("\n[2/5] Patching bot.py — payload extraction...")

# Anchor: after pine_score parsing line, insert breakout/age extraction
bot = patch(bot,
'''        pine_score= int(payload["pine_score"])  if payload.get("pine_score") else (int(payload["score"]) if payload.get("score") else None)''',
'''        pine_score= int(payload["pine_score"])  if payload.get("pine_score") else (int(payload["score"]) if payload.get("score") else None)
        # ── v9.7 / TASK 8B: breakout probability fields ─────────────────────
        breakout_prob_v=None
        try:
            if payload.get("breakout_prob") is not None:
                breakout_prob_v=int(float(payload["breakout_prob"]))
        except (TypeError, ValueError): pass
        breakout_strength_v=str(payload["breakout_strength"]) if payload.get("breakout_strength") else None
        breakout_dir_v=str(payload["breakout_dir"]) if payload.get("breakout_dir") else None
        # Signal age in seconds (Pine 'time' field is ms since epoch)
        signal_age_seconds_v=None
        try:
            if payload.get("time"):
                from datetime import datetime as _sdt, timezone as _stz
                _sig_t = float(payload["time"])
                if _sig_t > 1e11:  # ms → s
                    _sig_t = _sig_t / 1000.0
                signal_age_seconds_v = max(0.0, (_sdt.now(_stz.utc).timestamp() - _sig_t))
        except (TypeError, ValueError): pass''',
"Payload: extract breakout_prob/strength/dir + signal_age_seconds")

# ── Step 4: Patch bot.py — pass new fields into mem_open(TradeRecord(...)) ─
print("\n[3/5] Patching bot.py — TradeRecord wiring...")

bot = patch(bot,
'''            mem_open(TradeRecord(
                signal_id=sid,order_id=order_id,symbol=symbol,direction=direction,
                timestamp_open=now_utc.isoformat(),entry=entry,raw_sl=raw_sl,
                inst_sl=inst_sl,tp=tp,sl_distance=abs(entry-inst_sl),
                tp_distance=abs(tp-entry),rr=rr,session=filt.session,
                utc_hour=utc_hour,day_of_week=now_utc.weekday(),
                atr=atr,atr_ratio=atr_ratio,fakeout_pad=sl_result.fakeout_pad,
                sl_method=sl_result.method,htf_trend=htf_trend,
                trend_aligned=trend_aligned,news_minutes=news_mins,
                pine_score=pine_score,ai_score=filt.score,
                score_breakdown=filt.breakdown,balance_at_open=balance,
                equity_pct=guard.equity_pct,risk_pct=effective_risk,lot=lot,
            ))''',
'''            mem_open(TradeRecord(
                signal_id=sid,order_id=order_id,symbol=symbol,direction=direction,
                timestamp_open=now_utc.isoformat(),entry=entry,raw_sl=raw_sl,
                inst_sl=inst_sl,tp=tp,sl_distance=abs(entry-inst_sl),
                tp_distance=abs(tp-entry),rr=rr,session=filt.session,
                utc_hour=utc_hour,day_of_week=now_utc.weekday(),
                atr=atr,atr_ratio=atr_ratio,fakeout_pad=sl_result.fakeout_pad,
                sl_method=sl_result.method,htf_trend=htf_trend,
                trend_aligned=trend_aligned,news_minutes=news_mins,
                pine_score=pine_score,ai_score=filt.score,
                score_breakdown=filt.breakdown,balance_at_open=balance,
                equity_pct=guard.equity_pct,risk_pct=effective_risk,lot=lot,
                # ── TASK 8B journal fields ─────────────────────────────────
                asset_class=_ac,
                breakout_prob=breakout_prob_v,
                breakout_strength=breakout_strength_v,
                breakout_dir=breakout_dir_v,
                signal_age_bars=int(signal_age_seconds_v//900) if signal_age_seconds_v is not None else None,  # 15m bars
                regime=regime.regime if regime else None,
            ))''',
"TradeRecord: add asset_class, breakout_*, signal_age_bars, regime")

# ── Step 5: Fix gunicorn.conf.py _shutdown_event typo ──────────────────────
print("\n[4/5] Patching gunicorn.conf.py — _shutdown_event typo...")

gconf = patch(gconf,
'''def on_exit(server):
    server.log.info("[GUNICORN] on_exit — cleanup")
    try:
        from bot import xtb, _shutdown_event
        _shutdown_event.set()
        xtb.disconnect()
    except Exception as e:
        server.log.error(f"Cleanup error: {e}")''',
'''def on_exit(server):
    server.log.info("[GUNICORN] on_exit — cleanup")
    try:
        from bot import xtb, _shutdown
        _shutdown.set()
        xtb.disconnect()
    except Exception as e:
        server.log.error(f"Cleanup error: {e}")''',
"gunicorn.conf.py: _shutdown_event → _shutdown (matches actual bot var)")

# ── Step 6: Validate Python syntax ─────────────────────────────────────────
print("\n[5/5] Validating Python syntax...")
try:
    ast.parse(bot)
    print("  ✓ bot.py syntax OK")
except SyntaxError as e:
    print(f"  ✗ bot.py SYNTAX ERROR at line {e.lineno}: {e.msg}\n    ABORTING — no files modified."); sys.exit(1)
try:
    ast.parse(gconf)
    print("  ✓ gunicorn.conf.py syntax OK")
except SyntaxError as e:
    print(f"  ✗ gunicorn.conf.py SYNTAX ERROR at line {e.lineno}: {e.msg}\n    ABORTING — no files modified."); sys.exit(1)

# ── Step 7: Write new files ────────────────────────────────────────────────
print("\nWriting patched files...")
with open("bot.py", "w") as f: f.write(bot)
with open("gunicorn.conf.py", "w") as f: f.write(gconf)
print("  ✓ bot.py written")
print("  ✓ gunicorn.conf.py written")

print(f"\n{'='*60}")
print(f"✅ TASK 8 FOLLOW-UP COMPLETE — {n_patches} patches applied")
print(f"{'='*60}")
print(f"Backup suffix: bak_t8b_{ts}")
print(f"\nNext steps (run in order):")
print(f"  1. sudo systemctl restart sniper-bot")
print(f"  2. sleep 3 && sudo systemctl is-active sniper-bot")
print(f"  3. tail -10 logs/sniper.log")
print(f"  4. Watch first crypto trade tonight — trades.jsonl should now show:")
print(f"     asset_class, breakout_prob, breakout_strength, breakout_dir, regime, signal_age_bars")
print(f"\nROLLBACK if anything goes wrong:")
print(f"  cp bot.py.bak_t8b_{ts} bot.py && cp gunicorn.conf.py.bak_t8b_{ts} gunicorn.conf.py && sudo systemctl restart sniper-bot")
