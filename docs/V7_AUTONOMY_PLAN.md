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
