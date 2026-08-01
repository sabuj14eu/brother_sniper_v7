# Strategy Intelligence — architecture & build plan (2026-08-01)

Your vision: every trade stores ~150 features → nightly auto-analytics → dynamic
per-setup weights **from measured performance, not guesses.** This document maps
that onto what already exists, states what's genuinely missing, and sequences the
build so nothing fights the discipline guards you already paid for.

## The honest starting point (why we don't compute weights today)

1. **Today's journal measures OLD-Pine signals.** The post-audit Pine update means
   the 170 v7 / 89 brain trades describe logic you've since changed. Numbers
   computed now are a baseline to beat, not a verdict.
2. **Samples are small.** Most cluster/segment buckets are PROVISIONAL (n<20).
3. So the deliverable now is the **engine and the capture**, not the weights.
   Weights become trustworthy on their own as new-Pine, well-sampled data lands —
   and the engine is built to *refuse* to trust them until then.

## What already exists (build ON this, not beside it)

| Piece | File | What it already does |
|---|---|---|
| Per-trade record | `learning/trade_memory.py` | ~35 features/trade, append-only jsonl, join by signal_id |
| Cluster store | `learning/cluster_engine.py` | buckets by `symbol_session_regime_vol`, computes EV, 8-trade gate + confidence |
| Weight calibration | `learning/weight_engine.py` | 6 factor weights, EMA, clamp [0.30, 2.00], MIN_SAMPLES=20 |
| Overfit guard | `governance/discipline.py` | weight freeze, decay, delta cap, pre-calibration check |
| Raw signal archive | brain `decisions.jsonl` | full Pine payload verbatim (`signal_raw`) — 100+ fields already |

**The key realization:** your "Strategy Intelligence DB" is ~70% built. The Pine
payload already carries most MARKET / STRUCTURE / CONTEXT / SIGNAL features; they
land in the brain journal today and partially in `TradeRecord`. The real gaps are
narrow and specific (below).

## The 150 features — grouped by WHERE they come from

Legend: ✅ captured now · 🟡 in Pine payload but not on the v7 trade row · 🔴 not captured anywhere (needs new code)

**Market** — Symbol ✅ · ATR ✅ · ADX 🟡 · RSI 🟡 · MACD 🔴 · Bollinger width 🟡 · volatility percentile 🔴 · trend strength 🟡 · regime ✅
**Structure** — BOS/CHoCH/FVG/OrderBlock/LiqSweep 🟡 (Pine `type`/`zone`) · session H/L 🟡 · daily H/L 🔴 · weekly H/L 🔴
**Context** — session ✅ · day-of-week 🟡(derivable) · month 🟡 · news proximity 🟡(Pine `news_window`, but **flag is buggy** — see brain audit P2-2) · DXY 🟡 · VIX 🔴 · US10Y 🟡(`yield_dir`) · Oil 🟡(`oil_spike`)
**Signal** — Pine score ✅ · AI score ✅ · council votes 🟡(brain journal) · Scout/Quant/Risk scores 🟡(brain trace) · confidence 🟡 · grade ✅ · entry reason 🟡 · exit reason ✅
**Execution** — spread 🔴 · slippage 🔴 · fill delay 🔴 · broker latency 🔴 · MT5 latency 🔴  ← **the irrecoverable gap**
**Outcome** — win/loss ✅ · R-multiple ✅(computed) · MAE ✅ · MFE ✅ · exit type ✅ · time-in-trade ✅ · PF contribution ✅(computed)

**Takeaway:** you don't need to build 150 new capture points. You need to (a) copy
the 🟡 fields that already arrive in the Pine payload onto the trade row, and (b)
build the 🔴 execution telemetry, which is the only truly missing, truly
irrecoverable data. Everything else is a join, not a new sensor.

## Build sequence (each stage safe, tested, evidence-gated)

**Stage 0 — Nightly Edge Engine (DONE this PR, read-only).** `nightly_edge.py`:
best/worst per dimension + top/bottom two-way combinations + advisory per-setup
weights, all with empirical-Bayes shrinkage (small n pulled toward global) and
one-SE lower-bound expectancy (a setup scores well only if it's good AND
well-sampled). Advisory weights print but never apply. 9 unit tests on the math.
Cron: `0 2 * * * cd /home/shyam/brother_sniper_v7 && python3 nightly_edge.py --json learning/edge_report.json` → the dashboard reads the JSON.

**Stage 1 — Feature store (the 🟡 join, log-only).** Widen `TradeRecord` with the
fields already in the Pine payload: `setup_type`/`zone`, `adx`, `rsi`, `bb_width`,
`dxy_dir`, `yield_dir`, `oil_spike`, `news_window`, `day_of_week`, `month`, plus
the brain's council votes when the signal_id matches. Append-only (Iron Rule 2) —
old rows keep null. The moment `setup_type`/`zone` land, `nightly_edge` grows the
setup/zone dimensions and the advisory weights automatically (already wired).

**Stage 2 — Execution telemetry (the 🔴 gap, log-only, TIME-SENSITIVE).** Capture
at fill on the v7 bridge + executor: requested-vs-filled price (**slippage**),
bid/ask at fill (**spread**), request→ack time (**fill delay / latency**). This
data *cannot be backfilled* — every day unlogged is gone. It's the single most
valuable thing to start now even though it pays off later. Needs the v7 bridge in
git first (already snapshotted → `sniper_executor.py`).

**Stage 3 — Setup-type expectancy → the EXISTING weight system.** Extend
`cluster_engine`'s key with `setup_type` and let `weight_engine`/`discipline`
consume the shrunk lower-bound expectancy `nightly_edge` computes. Weights flow
through the **existing** freeze/decay/clamp governor — not a parallel path. A new
weight goes live only when: n≥MIN_N in the bucket, on **new-Pine** data, and it's
a logged human flip (Iron Rule 5 & 7). Your example (Trend-Pullback 1.45 / FVG
0.92 / Liq-Sweep 1.68) is exactly the output of Stage 3 — once the setup-type
capture (Stage 1) has enough new-Pine trades behind it.

## The discipline that makes weights honest (baked into Stage 0)

- **Shrinkage** — `shrunk_wr = (wins + K·global) / (n + K)`, K=6 virtual trades.
  A 3/3 "100%" bucket reports ~65%, not 100%.
- **Lower-bound expectancy** — report mean-R minus one standard error, so a
  setup must clear the bar *after* a small-sample penalty.
- **Advisory-only** — `nightly_edge` never writes live weights; it prints them.
  The live path stays in `weight_engine` + `discipline`, unchanged.
- **New-Pine cutoff** — when Stage 1 lands, tag each row with the Pine version so
  reports can filter to post-audit signals and ignore the old baseline.

## What NOT to build
- A second weighting system parallel to `weight_engine`/`cluster_engine` — it
  would fight the overfit governor. Extend, don't duplicate.
- Auto-applied weights. Every live weight change is a reviewed, logged decision.
- 150 brand-new sensors. Most features already arrive from Pine; capture the
  join first, build only the 🔴 execution telemetry as genuinely new.
