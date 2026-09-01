# V7 AUTONOMY PLAN — the seven-stage decision order (agreed 2026-08-22)

Shyam's architecture, mapped onto what EXISTS, with a build order that
respects the Evidence Law: one organ per week, shadow before enforce,
two populations before any rule moves. An item deferred in conversation
is an item forgotten — this file is the plan of record.

THE PRIME DIRECTIVE OF THIS PHASE: **v7 only, collect for a week,
judge nothing early.** The platform watches; Pine stays frozen; the
council path is untouched.

## The seven stages → what exists → what's missing

| # | Stage | Already built (verified) | Missing (build order below) |
|---|---|---|---|
| 1 | Data integrity | Candle audit + canonical identity + closed-only + two-witness clock (platform, v4.41–v4.51); dedupe sid guard (bot) | nothing structural |
| 2 | Market freshness | ATR stale-guard (bot `fetch_atr`); Freshness Law on every platform read model; `signal_age_seconds_v` measured at the decision site | **THE GAP THIS WEEK CLOSES**: age was measured but never gated. `filters/freshness_gate.py` v1 (shadow) gates signal age; v2 adds material-move vs live tick |
| 3 | Market context | Structure/EMA200/MTF/VWAP/session/news/vol/spread in DecisionSnapshot (platform); Pine payload context (bot) | weekly/monthly outlook feed (post_outlook.py exists — needs posts) |
| 4 | Scenario | Desk lanes BUY/SELL/WAIT/invalidated + session clock (platform); v7 filter chain (bot) | nothing new — scenarios are OBSERVED for a week, not extended |
| 5 | Production brain | planner.build_plan is the only executable plan (platform); council path (v18) | nothing — this NEVER changes in this phase |
| 6 | Position management | Monitor loop: BE, partial, MAE/MFE, close mirror (bot); mgmt panel `mgmt-v1` UNVALIDATED label (platform) | rule-based SL-modify/TP-continuation beyond BE/partial → **harness first**, per organ |
| 7 | Final safety gate | R:R validation, SL limits, slot/pause/asset gates (bot) | the freshness verdict joins this chain when (and only when) shadow evidence says enforce |

## This week's organ (the only live-file change): FRESHNESS GATE v1

- `filters/freshness_gate.py` + `patch_freshness_gate.py` (anchor-safe).
- SHADOW by default: logs `[FRESH-GATE SHADOW]` + telemetry rejects
  tagged `freshness_shadow`. **It blocks nothing until
  `V7_FRESHNESS_GATE=enforce` is set by a human who has read the shadow
  numbers (n>=20).** That is the Evidence Law applied to our own gate.
- The state it introduces is exactly the missing one:
  `DECISION BLOCKED — DATA FRESHNESS` → the old evaluation is not
  authoritative → NO ACTION → a completely new evaluation decides.
  Never "buy because price moved"; never "refresh and auto-buy".
- v2 (next organ candidate): material-move input — live reference price
  via the bridge (BRIDGE_KEY plumbing), `|ref − entry|/ATR > 1.5` →
  same state. The module already accepts the inputs; only the wire is
  missing.

## Routing the new ideas (recorded so they are not lost, built in order)

- **FVGs, Order Blocks, CISD, Rejection Blocks, Opening Gaps** — these
  are FEATURES, not gates. They go into the PLATFORM's research layer,
  computed from stored CLOSED candles, recorded on lane observations
  the way `entry_dist_atr` is — dark, log-only, each earning its place
  by measured expectancy per bucket (n>=20 per cell, with-trend split,
  two populations). PINE STAYS FROZEN: a sensor that keeps changing
  measures nothing. None of these touches the bot until the table says
  it deserves to.
- **Session-specific SL/TP (Asia / London / NY)** — plausible and
  already half-proven (Asia is PULLBACK's best session, 73.6% WR; the
  session TP ladder 1.0/1.8 ATR is the validated design). But per-session
  SL/entry parameters are a STRATEGY change → the backtest harness
  first (train/validate split, VALIDATE column decides), exactly like
  the pullback stop (1.5×ATR passed, 0.8 FAILED). Session is already
  stamped on every observation, so the cut costs nothing to run.
- **"Don't block high-news-impact time — it moves faster"** — HELD, not
  done. The feeling may be right, but the news gate is a live risk rule
  and feelings don't move risk rules (Iron Rules 5+7). The honest path
  is already flowing: `news_minutes` is on every trade record,
  `news_window` on every Pine payload, news state on every platform
  lane row. After the collection week(s): cut expectancy by news state
  in BOTH populations. If news-window trades measure better, unblocking
  becomes a human decision with data behind it — and it would not be
  the first time the data surprised us in this direction (grades were
  ANTI-predictive). Until then the gate stands.

## Sequencing (one organ per week)

1. **This week:** freshness gate SHADOW + the collection week runs
   (entry_dist_atr now live, closes now mirrored, outlooks postable).
   Touch nothing else.
2. **Week 2:** read the week: shadow-gate counts, distance buckets in
   BOTH populations, Friday grade verdict, news-state cut. Decide ONE
   thing from evidence (e.g. enforce the gate, or the Location-Gate
   conversation if both populations agree).
3. **Week 3+:** freshness v2 (material move), then position-management
   rules through the harness, then ICT features platform-side, in
   whatever order the evidence names loudest.
4. **Server cleanup / app speed** — after the above stabilizes; it is
   maintenance, not evidence, and must not compete with the collection
   week.

## Authority boundaries (unchanged by any of this)

Council path untouched. Payload append-only. Pine frozen. Risk/sizing
changes and gate enforcement are explicit human decisions with their
rationale logged. Shadow first, n>=20 before judging, ~100 before
trusting, two independent populations before a rule moves. NO
ROBUST EDGE and CANNOT SEPARATE remain first-class outcomes.

## Symbol universe (decided 2026-08-22)

Three doors, all required: Pine detects → v7 accepts → broker probed.
- TRADING/ALERTABLE NOW (7): GOLD, SILVER, BTC, ETH, USDJPY, and — after
  a Windows probe of the literal names USTEC/US30 (the bridge map has no
  entry for them; unmapped names pass through verbatim, the RIPPLE
  failure shape) — US30, US100. EURUSD toggle exists, default OFF.
- CANDLES ONLY (all 14 via BB_CANDLE_SYMBOLS, registry-level append):
  GBPUSD/USDCAD/USDCHF/AUDUSD/NZDUSD (Pine cannot see them — UNKNOWN,
  no webhook by design) and SOL (whole-lot volume_min 1.0: size cannot
  be tuned to risk; digits unverified).
- The five majors + SOL join trading only via a deliberate Pine v18.13
  (detection + per-market thresholds + ceremony), justified by evidence
  after the collection weeks. Depth beats breadth: SILVER/US100 are the
  measured strongest; every added symbol multiplies risk surface, not
  edge. No batch enablement, ever — one instrument, probed end to end.

## Findings from the first radar read (2026-08-24)

- SILVER 3d / US100 5d bias age: alerts CONFIRMED ACTIVE in TradingView;
  the journal shows the raw tickers firing (TVC:SILVER Aug 21 19:45,
  PURPLETRADING:US100 Aug 19). The silence is Pine finding no qualifying
  setup — honest quiet, not a dead feed. Watch this week; escalate only
  if SILVER stays silent through sessions where GOLD fires daily.
- AgentError root cause: WEEKLY AI BUDGET EXHAUSTED ($10.37/$10.00)
  since Aug 22 — council-routed signals fail-soft to pine_trust twice a
  day, then FAIL CLOSED. A money decision, Shyam's alone: raise the cap
  in the brain .env, wait for the weekly reset, or accept fail-closed.
- NEW ORGAN CANDIDATE (stage 6): PENDING-ORDER TTL. A SILVER SELL
  0.03 placed 10 DAYS ago sat PENDING at the broker with no SL/TP
  attached — the freshness-gate scenario in physical form. Manual
  cancel now; the automated rule (cancel/re-evaluate pending orders
  older than N bars) goes through the same shadow-then-enforce path as
  the freshness gate. Journal noise noted: 0x… Polymarket condition_ids
  and TESTUSD/MIRRORTEST rows are historical, outside the 30d bias
  window, harmless.

## DECISION LOG — GOLD demo collection (Shyam, 2026-08-24)

GOLD v7 DEMO COLLECTION
  Gate: ENABLED (un-benched in asset gate, or confirmed never benched)
  Purpose: SECOND-POPULATION MEASUREMENT ONLY — does GOLD still bleed
    when traded under the new instrumentation? Not "more GOLD data";
    the rejected population is rich already. The missing piece is
    ACTUALLY-TRADED GOLD under: entry_dist_atr LIVE · shadow gate LIVE
    · mirrored closes LIVE · rebuilt candle integrity · reject telemetry.
  Account: DEMO (all accounts are demo; no real money exists anywhere)
  Position sizing: UNCHANGED (Iron Rule 7 — nothing widens)
  Production/risk rules: NO CHANGE
  Window: from 2026-08-24 market open to Friday 2026-08-29 close —
    the week's GOLD trades are identified by this timestamp window plus
    this log entry. Populations stay structurally separate as always:
    platform lane observations vs v7 telemetry+trades; nothing from
    this week is "validated production evidence" — collection only.
  Review: at window close. Decision: RE-GATE or KEEP ENABLED, from the
    rejected-vs-traded comparison, never from P/L feelings. If GOLD
    bleeds again under clean instrumentation, that is STRONG evidence
    to keep it gated — a successful experiment either way.
  Explicit non-goal: "GOLD is doing well, enable permanently" is NOT
    an available outcome of this week. COLLECT → MEASURE → REVIEW →
    DECIDE, one step per week, same as everything else here.

Platform-side ask (relayed to the app session): a /v7 comparison view,
GOLD rejected vs GOLD actually-traded, cut by: candidates, fills, WR,
expectancy, P/L, R:R, entry_dist_atr bucket, grade, session, structure,
rejection reason, MAE/MFE where present. Bot-side data already flows
(capture_reject + telemetry + trades.jsonl, joined by signal_id via
load_unified).

## Weekend work order (2026-08-29/30) — performance is now a FAULT, not polish

Page timeouts reported on desk/chart. Item 4 (server cleanup) pulls
forward: a page that times out is broken, not slow. Triage first
(docker stats + pg table sizes), then the known suspects platform-side:
composite index candles(symbol,tf,ts) (model has three single-column
indexes; every candle query scans without the composite), CACHE the
three v4.52 evidence read models on /desk (funnel + contamination +
consistency each full-scan lane_observations per page load — bot
session owns this mistake), LIMIT chart history queries, and verify
market_status classifies METALS CLOSED on weekends (GOLD showed
"OPEN 24/5" + candles STALE on a Saturday — if the market clock is
wrong, every non-crypto page reads falsely stale all weekend).

## "V7 should trade alone, not wait for Pine" — the phased road (no skips)

The destination IS the V7 Self-Dependence Plan; the road has gates:
Phase 1 Collect (exit: >=200 resolved candidates, every field) ->
Phase 2 Analyze (the adaptive cells — running) -> Phase 3 Train ->
Phase 4 SHADOW (auto-v1 candidates decided beside v7, never executed)
-> Phase 5 controlled deployment = v7 trades without Pine. Check the
Phase-1 exit gate at this weekend's review via collector.coverage().
No phase may be skipped; the paper lanes' record is the resume the
autonomous engine brings to its own job interview.

## PHASE 1 EXIT GATE — MET (measured 2026-08-29)

coverage(): resolved_trades = 14,941 against target 200 (74x over),
33,789 observations across all four engines, spread recorded on
31,749 rows, vol_ratio on 33,281 — both Phase-1 field gaps CLOSED.
Phase 1 (Collect) is complete as measured; FORMALIZE at the Friday
review, then Phase 2 (Analyze) is officially the current phase — the
adaptive cells, confounder cuts and counterfactuals ARE its work.
The road to v7-without-Pine now runs: Phase 2 mature -> Phase 3 Train
(Model Lab, Quant Lab Law) -> Phase 4 SHADOW -> Phase 5 controlled
deployment. Gates checked, never skipped.

## Perf triage read (2026-08-29) — corrected diagnosis

Measured: candles 957,526 rows / 219 MB; lane_observations 33,789 /
35 MB; app CPU 0.35% idle, RAM fine; db NET OUT 271 GB cumulative.
CORRECTION to the earlier guess: the composite candle index already
exists via UniqueConstraint uq_candle(symbol,tf,ts) — indexing is NOT
the problem. The signature (idle CPU + timeouts + huge repeated reads)
points to: (1) a SINGLE app worker (DEPLOYMENT.md's own scaling note),
so requests queue behind slow ones; (2) the in-process sweeper
(record_all/resolve_all) periodically occupying that worker; (3) the
v4.52 desk read models full-scanning lane_observations three times per
page view, uncached; (4) unbounded chart/radar candle pulls, with 1m
feeds growing ~26k rows/day. Fixes are platform-side: cache evidence
read models (~60s), add uvicorn workers, bound queries, consider 1m
retention (e.g. 30d) later. Handover written; measure per-endpoint
before and after.

## Bot-side rulings on the platform's one-time list (2026-08-29)

- US100 LIVE CANDLES 400: the bridge's map has no USTEC/US100 entry
  (measured 2026-08-22), so the bridge rejects the platform's "US100".
  RULING: caller-side fix — the platform requests USTEC for bridge
  reads (its ingest already canonicalizes USTEC->US100). No Windows
  deploy needed; the bridge map gains the alias whenever the executor
  file next ships through the hash/relay process, not before.
- US10Y CONFLICT (brain push BEARISH vs AssetPulse up). RULING: for
  MACRO symbols (DXY/US10Y/US30Y/OIL/VIX) the journal-derived bias
  push is NOT authoritative — it is an echo of whatever old signal
  context last mentioned the symbol, weak provenance by construction.
  The authoritative macro direction is the platform's OWN
  trend_context computed from stored CLOSED candles (reproducible,
  fresh, already built). Platform: switch the macro strip to
  trend_context and label journal-derived macro rows "journal echo".
  Bot side will exclude macro symbols from push_bias in a future
  tidy-up; not urgent once the strip reads the right source.
- EARNINGS EVENTS: the FF feed is macro-econ only — earnings need a
  separate, deliberately chosen source (probe before trust). FUTURE
  ORGAN, not improvised. Meanwhile a single high-impact earnings event
  can be posted manually through the same /webhooks/brain/news
  contract when it matters (authored content, like outlooks).

## THE REVIEW'S TWO NEW QUESTIONS (Shyam's live-trading push, 2026-08-29)

1. AUTO-V1'S OWN VERDICT: per-engine paper record (resolved n, WR,
   expectancy, total R) from lane_observations. If auto-v1's record is
   negative, "make it live" dies on evidence. If positive, remember the
   resolver charges NO COSTS (documented in lane-resolve-v1): no
   spread, no slippage. A thin paper edge can be a real-money loss —
   any live decision must survive a spread-cost discount first.
2. THE AGREEMENT CUT (Shyam's hybrid, half 1): on evaluated
   DecisionRecords, does Pine perform better when auto-v1 AGREES with
   the direction vs when it disagrees/waits? If agreement cells show
   better expectancy at n>=20, "require bot agreement on Pine signals"
   becomes a proposable GATE TIGHTENING (reduces trades, never widens
   risk) — still shadow-first, still human-approved.
Half 2 (bot fires without Pine) remains Phase 5, reachable only through
a positive cost-discounted record + the execution-path build + explicit
approval. No live change happens by chat decision on a weekend.

## WEEK-2 AUTONOMY COLLECTION (Shyam's order, 2026-08-31) — SHADOW STAYS SHADOW

The weekend report proved auto_live GENERATES without Pine; Week-2 must
prove the whole lifecycle THINKS without Pine. Execution stays unarmed.
What shipped for it (all read-only or dry-run):

- SCENARIO RECORD (§1/2/5): auto_live.scenario() now logs every state
  transition per symbol to logs/auto_scenarios.jsonl — ⚪ WAIT /
  🟡 DEVELOPING / 🟢 BUY READY / 🔴 SELL READY / ⛔ DATA FRESHNESS —
  each with bullish_condition, bearish_condition, missing_confirmation,
  invalidation, next_thing_to_watch, and pine_dependency=NONE by
  construction. Event phase and macro context are recorded as UNKNOWN
  until their feeds are wired — never manufactured. candidate() remains
  the sole firing authority; tests pin scenario↔candidate equivalence.
- MGMT REPLAY (§6): mgmt_replay.py compares ENTRY-ONLY vs BREAKEVEN+1R
  from recorded MAE/MFE with honest BEST/WORST bounds (sampled extremes
  cannot order events). TP1/trail/runner/news-aware = UNKNOWN: they need
  the price path the monitor does not record. SL MAY ONLY TIGHTEN.
- STATE AUDIT (§7): audit_mgmt_state.py — required zeros:
  closed_reactivated, double_close, partial_fired, sl_wrong_side,
  negative_excursion, widen_guard_missing (verifies bot.py's _tighter
  line still stands). Writes logs/mgmt_audit_last.json for the scorecard.
- DAILY SCORECARD (§8): autonomy_scorecard.py prints the §8 counts from
  the bot's own logs and --post ships them to the platform as kind:"doc"
  path AUTONOMY_SCORECARD_<date>.md (same artifact webhook as readiness).
- §9/§10 (missed opportunities, gate counterfactuals) ride the platform's
  truth layer over the scenario log — every WAIT carries level, distance
  and bar_ts, so replay needs no new capture. §11 is conditional_profile.
- §12 is Friday's question, answered from this week's record only; any
  UNKNOWN keeps the verdict at SHADOW. AUTO_LIVE_ARM=1 stays a human act.

## NEWS SEMANTIC ENGINE v1 (Shyam's order, 2026-08-31) — CONTEXT, NEVER SIGNAL

filters/news_semantic.py: NEWS -> EVENT CLASS -> SURPRISE -> STANCE ->
PRESSURE MAP, embedded in every scenario record; price keeps the final
vote and v7's hard news gate is untouched. Laws pinned by test:
numbers beat words (wording never sets surprise when actual+forecast
exist); inverted series (unemployment, jobless) carry explicit polarity;
non-USD pressure = UNKNOWN in v1; two opposite-stance in-window events =
CONFLICTING NEWS, no direction forced; agreement() declares
CONFIRMED / ⚠ CONFLICT — WAIT between news pressure and price bias.
Phases PRE-EVENT/INITIAL/STRUCTURE/RETEST/POST-NEWS from event minutes.
Feed = the same FF calendar bot.py's gate already fetches; no new feed.
Learning: scenario records now carry event_class/surprise/phase, so
conditional_profile's cells (GOLD + HOT PCE + NY + WITH-TREND ...) accrue
from the same journal; no learned edge is claimed under the floor.
AI's role stays explanation-only; nothing in this engine places trades.

## EXTERNAL REVIEW VERDICTS (2026-08-31) — every claim verified before belief

| Claim | Verdict | Action |
|---|---|---|
| P0 executor reports MT5 failure as zero positions -> fake $0 losses, self-pause | CONFIRMED (worse: MT5-disconnect returns clean count:0 HTTP 200; ensure_mt5() return ignored) | patch_truth_guards.py (bot: shape guard + 10-cycle unverified-close guard) + patch_executor_positions.py (Windows: 503 on disconnect) |
| P0 webhook auth self-defeating (secret self-injection + spoofable XFF) | CONFIRMED (bot.py 584-589, _guard XFF-first) | patch_truth_guards.py: XFF honored only from loopback (our nginx); injection now sits behind a real IP check. Removing injection outright would cut Pine off — not done. |
| P0 signal_id collision GOLD/SILVER same bar -> dedup drops second trade | REFUTED — v7 mints its own dedup key sha256(symbol-direction-entry) at bot.py:286; symbol is already in it | none needed |
| push_bias reads Pine fields at wrong nesting -> journal bias always empty | CONFIRMED — same bug class as check_pine_ver v1; pass-through keys live in context.market_snapshot | fixed in brain repo (reads both levels), rehearsed on both shapes |
| v7 drops ALL PULLBACK signals via noise filter | CONFIRMED — bot.py:623 `_typ != "SMART_SCALP"` drops every BSv17/18 non-scalp type, PULLBACK included, while PULLBACK is the VALIDATED trigger (n=640, PF 1.30-1.45) | DECISION CARD for Shyam — enabling a signal class is a live-trading change, never silent |
| DD guard 99% while claiming 20% | CONFIRMED — risk/equity_guard.py daily/weekly/total all 0.99 | DECISION CARD for Shyam — Iron Rule 7: risk limits are his call, logged |
| /webhook/polymarket unauthenticated, costs AI budget per hit | CONFIRMED | env-gated PM_WEBHOOK_SECRET (brain repo); unset = unchanged |
| auto_live payloads rejected when armed (found during verification, not in the review) | CONFIRMED — no secret, AUTOLIVE not in trust list | secret added at POST time only; test pins that it never reaches the dry log |
| journal outcomes only via unscheduled manual script; can destroy live rows | NOT YET VERIFIED | queued — verify before Friday |
| one-witness clock in executor /candles | NOT YET VERIFIED | queued |
| dashboard AI-mode toggle unauthenticated | NOT YET VERIFIED (dashboard is platform/brain surface) | queued, relay to platform session |
| EV/cluster learning layer structurally inert | NOT YET VERIFIED | queued — needs its own reading, not a drive-by |

### DECISION CARDS — Shyam's call, not mine (Iron Rule 7 / Evidence Law)

1. PULLBACK on v7: the validated trigger (n=640, out-of-sample PF
   1.30-1.45, Asia 73.6% WR) never reaches v7 — the noise filter drops
   every non-SMART_SCALP type. Options: (a) leave as is (v7 stays the
   scalp arm; PULLBACK lives in auto_live's own engine, which is the
   same trigger family and already shadow-deployed), (b) allow type
   PULLBACK through v7's full gate chain. My recommendation: (a) for
   now — auto_live IS the pullback path, with dry-run evidence accruing;
   revisit at Friday's review with the dry week in hand.
2. DD guard: daily/weekly/total all effectively OFF at 99%. On DEMO the
   money risk is zero but the MEASUREMENT risk is real (a runaway loss
   streak pollutes every population). If you want real limits, name the
   numbers (e.g. daily 5% / weekly 10% / total 20%) and I ship them as
   an explicit, logged change. Tightening only — never widened silently.
