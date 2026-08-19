# V7 DESK — reviewed work order (2026-08-19)

Origin: the owner's 25-point spec for a single `/v7-desk` page in the main
app (app.signalmesh.dev). Reviewed on the bot side against what the feeds
already deliver. Verdict up front: **the display half (Phase 1) is a good
idea and ~70% of its data already arrives at the platform today. The
decision half (Phase 2 — desk context feeding v7, AI session analyst) is
also sound BUT is a live-logic change and falls under the Evidence Law:
it ships dark, behind kill switches, and earns its way in.**

Ownership: the PAGE is the platform session's work (their repo, their UI).
The FEEDS are the bot session's work (this repo + brother-brain-v2).
Point 23 stands absolutely: **no V18 changes. This project never touches
the v18 brain, the council, or the Pine script.**

---

## Point-by-point map (spec point → status → where the data lives)

| # | Spec item | Status | Data source today |
|---|-----------|--------|-------------------|
| 1 | Single `/v7-desk` page | MISSING (UI) | Platform builds; all feeds below |
| 2 | V7 LIVE truth block | EXISTS | `v7_heartbeat` artifact (status, uptime, W/L, streak, day/week PnL, slots, bridge, open positions) + mirror posts. UNKNOWN rule already the law of the heartbeat |
| 3 | Per-symbol grid + broker facts + reconciliation | EXISTS (data) | Heartbeat carries live reconciliation (trade-desk build, labelled not repaired); mirrors carry per-symbol verdicts with entry/sl/tp/rr/grade/session |
| 4 | Session Edge | EXISTS | `evidence.json`, mirrored to platform nightly (03:25 cron) — n/WR/PF/exp per session with PROVISIONAL/STRONG labels |
| 5 | Symbol Edge | EXISTS | Same `evidence.json` (STRONG/WEAK cluster labels per evidence rules) |
| 6 | Setup Edge (side×grade×setup×session×symbol) | PARTIAL | Journal has direction/grade/session/symbol/type/struct/veto flags → bot side can add a `setup_edge` block to evidence.json. Most combos will be n<20 ⇒ UNPROVEN, and must render that way |
| 7 | Gate effectiveness table | EXISTS (thin) | `counterfactual.jsonl` + evidence.json gate block. Only 2 verdicts stored so far — the lane fills over weeks; render "n=2 UNPROVEN", never hide it |
| 8 | MAE/MFE + stop/target headroom | EXISTS | `mae_m1.jsonl` (nightly M1 replay) + sampled columns in trades.jsonl; evidence.json headroom block. Replay only reaches ~3.5 days back — older trades show sampled values only, labelled |
| 9 | Market context per session | EXISTS (partial) | Bias push market engine: trend, trend_strength, volatility/risk, ATR, DXY (dated contract, labelled), oil; source + as_of on every item. Session VWAP: NOT built — UNKNOWN. Correlation context: NOT built — UNKNOWN. US10Y: only when Pine emits `yield_dir` |
| 10 | News/macro panel | EXISTS | `/webhooks/brain/news` hourly (ForexFactory, impact + forecast/previous/actual). "Next high impact" is a platform-side sort of existing rows |
| 11 | SESSION DESK STATE object | MISSING | New. Platform-derived composite; every field needs created_at / valid_until / source / evidence status. Expiry must actually expire |
| 12 | AI analyzes the SESSION, not each signal | MISSING (Phase 2) | Correct architecture (mirrors the cost lesson from the brain: per-signal AI is what the budget cap exists for). Ships behind `AI_ENABLED=false` |
| 13 | V7 Decision Package | MISSING (Phase 2) | Bot side. v7 already reads its own journal + heartbeat inputs; the package is an assembly step, dark until validated |
| 14 | V7 remains final authority | RULE — agreed | Desk emits context sentences, never verdicts. Same doctrine as "the map plans, v18 confirms" |
| 15 | Decision Explanation stored per verdict | PARTIAL | v7 journals verdict + reason today; the extra context fields land WITH Phase 2, not before (else they'd be fake — v7 doesn't read context yet) |
| 16 | Source classification on every field | PARTIAL | Already the habit (spread_source, market_engine source, as_of). Platform formalizes the enum: V7_FACT / BROKER_FACT / MARKET_FACT / HISTORICAL_EVIDENCE / DESK_DERIVED / AI_CONTEXT |
| 17 | Evidence status labels | EXISTS | Evidence Law thresholds already in evidence.json (n<20 PROVISIONAL etc.). UNPROVEN/PROVISIONAL/ESTABLISHED/STRONG — platform renders, never upgrades |
| 18 | Priority Board | MISSING (UI) | Pure display derivation from evidence.json + heartbeat. DESK_DERIVED label mandatory |
| 19 | "Why Not Trade?" gate counts | EXISTS (data) | Rejection reasons mirrored per verdict (structured `rejected_by`); would-have columns wait for counterfactual n≥20 |
| 20 | Broker reconciliation section | EXISTS (data) | Heartbeat reconciliation states (CONSISTENT/MISMATCH/ORPHAN/UNKNOWN), no auto-repair — already the trade-desk build |
| 21 | Desk never places orders | RULE — agreed | Phase 1 has NO path desk→MT5. Phase 2 execution stays v7→bridge exactly as today |
| 22 | Kill switches | PARTIAL | Mirror/heartbeat flags exist. New: DESK_CONTEXT_ENABLED, AI_ENABLED, AUTO_DISPATCH_ENABLED — all default OFF |
| 23 | No V18 changes | RULE — absolute | Nothing in this project touches brain/, the council, Pine, or the empty pinev18.6 repo |
| 24 | Decision Timeline | EXISTS (data) | Every mirror post is timestamped (signal → verdict → close via `v7-<id>` + `pine_signal_id` join). Timeline is a platform-side sort/render |
| 25 | Target architecture diagram | AGREED | Matches what's already built; Phase 2 adds only the "V7 reads desk context" arrow, dark |

## Phase plan

**Phase 1 — display only (start now, platform session):**
points 1–11, 16–20, 24. Zero new risk: every input is an existing feed,
nothing writes toward the trading path. Missing bot-side piece: `setup_edge`
block in evidence.json (bot session builds, small).

**Phase 2 — context into v7 (later, bot session, Evidence Law applies):**
points 12–15, 21–22. Requirements before ANY of it goes live:
- kill switches in place, defaults OFF, existing v7 behavior byte-identical
  while OFF;
- desk context is ADVISORY input to v7's own rules — v7's gates decide,
  the desk never emits BUY/SELL;
- journal the context v7 saw with each verdict from day one dark, so the
  effect is measurable BEFORE the switch flips (n≥20 minimum, judge ~100);
- AI = session analyst on a schedule (few calls/day), never per-signal,
  under the same spend ledger + weekly cap as the brain.

## The one hard line

The Desk may say: *"GOLD historical evidence is WEAK, regime RANGE, news
risk HIGH."* The Desk may never say: *"SELL GOLD."* Any code path that
turns desk output into a direction is a spec violation, Phase 1 or 2.
