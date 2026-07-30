import json, collections, statistics

TRADES = "/home/shyam/brother_sniper_v7/learning/trades.jsonl"
FLOW   = "/home/shyam/brother_sniper_v7/learning/flow_vector.jsonl"
PROV_N = 20

trades = collections.OrderedDict()
types  = collections.Counter()
for path in (TRADES,):
    try:
        for line in open(path):
            line = line.strip()
            if not line: continue
            try: r = json.loads(line)
            except Exception: continue
            types[r.get("_type","?")] += 1
            sid = r.get("signal_id")
            if not sid: continue
            rec = trades.setdefault(sid, {})
            for k, v in r.items():
                if v is not None: rec[k] = v
    except FileNotFoundError:
        print(f"missing: {path}")

flow = {}
try:
    for line in open(FLOW):
        line = line.strip()
        if not line: continue
        try: f = json.loads(line)
        except Exception: continue
        sid = f.get("signal_id")
        if sid: flow[sid] = f
except FileNotFoundError:
    print(f"missing: {FLOW}")

for sid, t in trades.items():
    if sid in flow:
        t["flow_vector"] = flow[sid].get("vector")
        if t.get("macro_score") is None:
            t["macro_score"] = flow[sid].get("macro_score")

done = [t for t in trades.values()
        if ("won" in t or "net_profit" in t) and "test" not in str(t.get("signal_id","")).lower()]

def pnl(t): return t.get("net_profit", t.get("gross_profit", 0.0)) or 0.0
def won(t): return bool(t.get("won")) if "won" in t else pnl(t) > 0

n = len(done)
wins   = [t for t in done if won(t)]
losses = [t for t in done if not won(t)]
total  = round(sum(pnl(t) for t in done), 2)
wr     = round(100*len(wins)/n, 1) if n else 0
avg_w  = round(statistics.mean([pnl(t) for t in wins]), 2) if wins else 0
avg_l  = round(statistics.mean([pnl(t) for t in losses]), 2) if losses else 0
gw     = sum(pnl(t) for t in wins); gl = abs(sum(pnl(t) for t in losses))
pf     = round(gw/gl, 2) if gl else float("inf")

print("="*70)
print(f"COMPLETED TRADES: {n}   WIN RATE: {wr}%   NET PnL: {total}")
print(f"avg win: {avg_w}   avg loss: {avg_l}   profit factor: {pf}")
print(f"_type counts: {dict(types)}   flow-joined: {sum(1 for t in done if t.get('flow_vector'))}/{n}")
print(f"(buckets with n<{PROV_N} flagged PROVISIONAL - small-n differences are probably luck)")
print("="*70)

def bucket_num(v, edges):
    if v is None: return None
    try: v = float(v)
    except (TypeError, ValueError): return None
    for lo, hi, label in edges:
        if lo <= v < hi: return label
    return None

def atr_pct_bucket(t):
    e = t.get("entry") or 0; sd = t.get("sl_distance") or 0
    if not e or not sd: return None
    return bucket_num(100*sd/e, [(0,0.3,"<0.3%"),(0.3,0.6,"0.3-0.6%"),(0.6,1.0,"0.6-1%"),(1.0,99,">1%")])

EXTRACTORS = {
    "symbol":      lambda t: t.get("symbol"),
    "asset_class": lambda t: t.get("asset_class"),
    "side":        lambda t: t.get("direction"),
    "grade":       lambda t: t.get("grade"),
    "regime":      lambda t: t.get("regime"),
    "flow_vector": lambda t: t.get("flow_vector"),
    "session":     lambda t: t.get("session"),
    "htf_trend":   lambda t: t.get("htf_trend"),
    "ai_score":    lambda t: bucket_num(t.get("ai_score"), [(0,40,"<40"),(40,55,"40-54"),(55,70,"55-69"),(70,101,"70+")]),
    "rr":          lambda t: bucket_num(t.get("rr"), [(0,2,"<2"),(2,3,"2-3"),(3,99,">3")]),
    "sl_pct":      lambda t: atr_pct_bucket(t),
}

def breakdown(key, fn):
    g = collections.defaultdict(list)
    for t in done:
        v = fn(t)
        if v is not None: g[v].append(t)
    if not g:
        print(f"\n[{key}] -- not present in data"); return
    print(f"\nBY {key.upper()}:")
    print(f"  {'value':<18}{'n':>4}{'wr%':>7}{'net':>10}{'avgW':>8}{'avgL':>8}  flag")
    for v, ts in sorted(g.items(), key=lambda x:-sum(pnl(t) for t in x[1])):
        w  = [t for t in ts if won(t)]; l = [t for t in ts if not won(t)]
        aw = round(statistics.mean([pnl(t) for t in w]),1) if w else 0
        al = round(statistics.mean([pnl(t) for t in l]),1) if l else 0
        flag = "PROVISIONAL" if len(ts) < PROV_N else ""
        print(f"  {str(v):<18}{len(ts):>4}{round(100*len(w)/len(ts),1):>7}{round(sum(pnl(t) for t in ts),2):>10}{aw:>8}{al:>8}  {flag}")

for k, fn in EXTRACTORS.items():
    breakdown(k, fn)

print("\n--- coverage: how many done-trades carry each field ---")
for k, fn in EXTRACTORS.items():
    print(f"  {k:<14}: {sum(1 for t in done if fn(t) is not None)}/{n}")
