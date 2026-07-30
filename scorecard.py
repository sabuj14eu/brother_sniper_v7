#!/usr/bin/env python3
"""
Brother Sniper v7 — FULL SCORECARD (read-only, run anytime)
===========================================================
Rates every section of the bot in ONE place. Joins all data sources.
Sections with too little data say INSUFFICIENT DATA and fill in over time.

    python3 scorecard.py

NOTHING is written, NOTHING is traded. Pure analysis.
HONESTY: every metric shows n. n<MIN_N is flagged PROVISIONAL (likely luck).
"""
import json, collections, statistics, os
from datetime import datetime, timezone

BASE   = "/home/shyam/brother_sniper_v7"
TRADES = f"{BASE}/learning/trades.jsonl"
FLOW   = f"{BASE}/learning/flow_vector.jsonl"
VOTES  = f"{BASE}/learning/eye_votes.jsonl"
READS  = f"{BASE}/learning/analyst_reads.jsonl"

MIN_N  = 20     # below this, a rating is PROVISIONAL (probably luck, not edge)

def _load(path):
    rows = []
    try:
        for line in open(path):
            line = line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except Exception: pass
    except FileNotFoundError:
        pass
    return rows

def _bar(): print("=" * 72)
def _hdr(t): _bar(); print(t); _bar()

# ── Load + merge trades by signal_id ──────────────────────────────────────────
raw = _load(TRADES)
trades = collections.OrderedDict()
for r in raw:
    sid = r.get("signal_id")
    if not sid: continue
    rec = trades.setdefault(sid, {})
    for k, v in r.items():
        if v is not None: rec[k] = v

flow = {f.get("signal_id"): f for f in _load(FLOW) if f.get("signal_id")}
for sid, t in trades.items():
    if sid in flow: t["flow_vector"] = flow[sid].get("vector")

done = [t for t in trades.values()
        if ("won" in t or "net_profit" in t) and "test" not in str(t.get("signal_id","")).lower()]

def pnl(t): return t.get("net_profit", t.get("gross_profit", 0.0)) or 0.0
def won(t): return bool(t.get("won")) if "won" in t else pnl(t) > 0

def stats(ts):
    n = len(ts)
    if n == 0: return None
    w = [t for t in ts if won(t)]; l = [t for t in ts if not won(t)]
    gw = sum(pnl(t) for t in w); gl = abs(sum(pnl(t) for t in l))
    return {
        "n": n, "wr": round(100*len(w)/n, 1), "net": round(sum(pnl(t) for t in ts), 2),
        "avg_w": round(statistics.mean([pnl(t) for t in w]), 2) if w else 0,
        "avg_l": round(statistics.mean([pnl(t) for t in l]), 2) if l else 0,
        "pf": round(gw/gl, 2) if gl else (float("inf") if gw else 0),
    }

def verdict_pf(pf, n):
    if n < MIN_N: return "PROVISIONAL (need more trades)"
    if pf >= 1.5:  return "STRONG (profitable)"
    if pf >= 1.1:  return "OK (mild edge)"
    if pf >= 0.95: return "BREAKEVEN"
    return "POOR (losing)"

print(f"\nBROTHER SNIPER v7 — SCORECARD   {datetime.now(timezone.utc).isoformat()}")
print(f"(metrics with n<{MIN_N} are PROVISIONAL — small samples are probably luck)")

# ══ SECTION 1: ENTRY QUALITY (the Pine foundation) ════════════════════════════
_hdr("SECTION 1 — ENTRY QUALITY (overall + by segment)")
ov = stats(done)
if not ov:
    print("  INSUFFICIENT DATA — no completed trades yet.")
else:
    print(f"  OVERALL: n={ov['n']}  WR={ov['wr']}%  net={ov['net']}  PF={ov['pf']}  "
          f"avgW={ov['avg_w']} avgL={ov['avg_l']}")
    print(f"  VERDICT: {verdict_pf(ov['pf'], ov['n'])}")
    def seg(key, fn):
        g = collections.defaultdict(list)
        for t in done:
            v = fn(t)
            if v is not None: g[v].append(t)
        if not g: 
            print(f"\n  by {key}: (no data)"); return
        print(f"\n  by {key}:")
        print(f"    {'value':<16}{'n':>4}{'wr%':>7}{'net':>10}{'PF':>7}  flag")
        for v, ts in sorted(g.items(), key=lambda x:-sum(pnl(t) for t in x[1])):
            s = stats(ts); flag = "PROV" if s["n"] < MIN_N else ""
            print(f"    {str(v):<16}{s['n']:>4}{s['wr']:>7}{s['net']:>10}{s['pf']:>7}  {flag}")
    seg("symbol",  lambda t: t.get("symbol"))
    seg("side",    lambda t: t.get("direction"))
    seg("session", lambda t: t.get("session"))
    seg("regime",  lambda t: t.get("regime"))

# ══ SECTION 2: TRADE MANAGEMENT (BE / partial / MAE) ══════════════════════════
_hdr("SECTION 2 — TRADE MANAGEMENT (breakeven / partial / MAE)")
be_fired      = [t for t in done if t.get("be_done")]
partial_fired = [t for t in done if t.get("partial_done")]
has_mae       = [t for t in done if t.get("mae") is not None]
print(f"  breakeven fired on:   {len(be_fired)} trades")
print(f"  partial-close fired:  {len(partial_fired)} trades")
print(f"  trades with MAE data: {len(has_mae)} / {len(done)}")
if len(be_fired) < 5 and len(partial_fired) < 5:
    print("  VERDICT: INSUFFICIENT DATA — management just went live; needs +1R trades to rate.")
else:
    bs = stats(be_fired); ps = stats(partial_fired)
    if bs: print(f"  BE trades:      n={bs['n']} WR={bs['wr']}% PF={bs['pf']} net={bs['net']}")
    if ps: print(f"  Partial trades: n={ps['n']} WR={ps['wr']}% PF={ps['pf']} net={ps['net']}")
    print("  (compare these PF vs Section-1 overall PF to judge if management helps)")

# ══ SECTION 3: FILTER / AI SCORE (is it helping or hurting?) ══════════════════
_hdr("SECTION 3 — FILTER / AI SCORE QUALITY")
scored = [t for t in done if t.get("ai_score") is not None]
if len(scored) < 10:
    print("  INSUFFICIENT DATA.")
else:
    def sb(lo, hi): 
        return [t for t in scored if lo <= (t.get("ai_score") or 0) < hi]
    print(f"    {'ai_score band':<16}{'n':>4}{'wr%':>7}{'net':>10}{'PF':>7}")
    for lo, hi, lab in [(0,40,"<40"),(40,55,"40-54"),(55,70,"55-69"),(70,101,"70+")]:
        ts = sb(lo, hi)
        if ts:
            s = stats(ts)
            print(f"    {lab:<16}{s['n']:>4}{s['wr']:>7}{s['net']:>10}{s['pf']:>7}")
    # is score correlated with success the RIGHT way?
    hi_band = sb(55, 101); lo_band = sb(0, 55)
    if hi_band and lo_band:
        hs, ls = stats(hi_band), stats(lo_band)
        if hs["wr"] > ls["wr"] + 5:
            print(f"  VERDICT: filter WORKS (high-score WR {hs['wr']}% > low-score {ls['wr']}%)")
        elif ls["wr"] > hs["wr"] + 5:
            print(f"  VERDICT: filter BACKWARDS (low-score WR {ls['wr']}% > high-score {hs['wr']}%) — scoring is anti-helpful")
        else:
            print(f"  VERDICT: filter NEUTRAL (high {hs['wr']}% vs low {ls['wr']}% — no clear signal)")

# ══ SECTION 4: SHADOW EYES (Gemini/DeepSeek grading Pine) ═════════════════════
_hdr("SECTION 4 — SHADOW EYES (eye votes vs outcomes)")
votes = _load(VOTES)
if not votes:
    print("  INSUFFICIENT DATA — no eye votes logged yet (eye fires only on BLOCKED signals).")
else:
    # join votes to outcomes by signal_id
    by_model = collections.defaultdict(lambda: {"take_win":0,"take_lose":0,"block_win":0,"block_lose":0,"total":0,"nojoin":0})
    for v in votes:
        m = v.get("model","?"); sid = v.get("signal_id")
        by_model[m]["total"] += 1
        if not sid or sid not in trades or not ("won" in trades[sid] or "net_profit" in trades[sid]):
            by_model[m]["nojoin"] += 1
            continue
        w = won(trades[sid]); take = v.get("take")
        if take is True:  by_model[m]["take_win" if w else "take_lose"] += 1
        elif take is False: by_model[m]["block_win" if w else "block_lose"] += 1
    print(f"    {'model':<24}{'votes':>6}{'joined':>7}{'take_WR':>9}")
    for m, d in by_model.items():
        joined = d["total"] - d["nojoin"]
        tw, tl = d["take_win"], d["take_lose"]
        twr = round(100*tw/(tw+tl),1) if (tw+tl) else "-"
        print(f"    {m:<24}{d['total']:>6}{joined:>7}{str(twr):>9}")
    print("  (take_WR = win rate when the eye said TAKE; compare models. needs joined votes to mean anything)")
    if all((d['total']-d['nojoin'])<5 for d in by_model.values()):
        print("  VERDICT: INSUFFICIENT DATA — too few joined votes yet.")

# ══ SECTION 5: INDEPENDENT ANALYST EYE (does its read predict price?) ═════════
_hdr("SECTION 5 — INDEPENDENT ANALYST EYE")
reads = _load(READS)
if not reads:
    print("  INSUFFICIENT DATA — no analyst reads logged yet.")
else:
    by_model = collections.defaultdict(lambda: collections.Counter())
    for r in reads:
        m = r.get("model","?"); call = r.get("call")
        by_model[m][call or "ERR"] += 1
    print(f"    {'model':<24}{'reads':>6}{'BUY':>6}{'SELL':>6}{'NOTHING':>9}{'ERR':>6}")
    for m, c in by_model.items():
        tot = sum(c.values())
        print(f"    {m:<24}{tot:>6}{c.get('BUY',0):>6}{c.get('SELL',0):>6}{c.get('NOTHING',0):>9}{c.get(None,0)+c.get('ERR',0):>6}")
    actionable = sum(c.get('BUY',0)+c.get('SELL',0) for c in by_model.values())
    print(f"  actionable calls (BUY/SELL) so far: {actionable}")
    print("  NOTE: scoring 'did the call predict price?' requires matching each read's")
    print("        timestamp to forward price move — that's a future scoring pass once")
    print("        enough actionable calls accumulate. For now this shows read activity.")
    if actionable < 10:
        print("  VERDICT: INSUFFICIENT DATA — needs more BUY/SELL calls to score predictive value.")

# ══ SECTION 6: PROTECTION (stops / SL_PCT) ════════════════════════════════════
_hdr("SECTION 6 — PROTECTION (stop-distance quality)")
def sl_pct(t):
    e = t.get("entry") or 0; sd = t.get("sl_distance") or 0
    return (100*sd/e) if (e and sd) else None
buckets = collections.defaultdict(list)
for t in done:
    p = sl_pct(t)
    if p is None: continue
    lab = "<0.3%" if p<0.3 else "0.3-0.6%" if p<0.6 else "0.6-1%" if p<1.0 else ">1%"
    buckets[lab].append(t)
if not buckets:
    print("  INSUFFICIENT DATA.")
else:
    print(f"    {'SL distance':<14}{'n':>4}{'wr%':>7}{'net':>10}{'PF':>7}")
    order = [">1%","0.6-1%","0.3-0.6%","<0.3%"]
    for lab in order:
        if lab in buckets:
            s = stats(buckets[lab])
            print(f"    {lab:<14}{s['n']:>4}{s['wr']:>7}{s['net']:>10}{s['pf']:>7}")
    tight = stats(buckets.get("<0.3%", [])) if "<0.3%" in buckets else None
    wide  = stats(buckets.get(">1%", [])) if ">1%" in buckets else None
    if tight and wide:
        if wide["wr"] > tight["wr"] + 10:
            print(f"  VERDICT: tight stops BLEED (WR <0.3%={tight['wr']}% vs >1%={wide['wr']}%) — floor is critical")
        else:
            print(f"  VERDICT: stop-distance effect unclear so far")

# ══ SUMMARY ═══════════════════════════════════════════════════════════════════
_hdr("ONE-LINE SUMMARY")
if ov:
    print(f"  Entry:      PF {ov['pf']} / WR {ov['wr']}% (n={ov['n']}) — {verdict_pf(ov['pf'],ov['n'])}")
print(f"  Management: BE×{len(be_fired)} Partial×{len(partial_fired)} MAE×{len(has_mae)} — {'rateable' if len(be_fired)+len(partial_fired)>=5 else 'collecting'}")
print(f"  Filter:     {len(scored)} scored trades — see Section 3 verdict")
print(f"  Shadow eyes:{sum(len(_load(VOTES)) for _ in [0])} votes — {'rateable' if len(_load(VOTES))>=20 else 'collecting'}")
print(f"  Analyst eye:{len(reads)} reads — collecting")
print(f"  Protection: see Section 6 (SL_PCT) verdict")
print()
