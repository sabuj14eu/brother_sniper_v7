# V7 DESK EVIDENCE SPECIFICATION
Date: 2026-08-18 · Branch: `claude/trade-desk-architecture-review-hp9xnb`
Status: SPECIFICATION ONLY — nothing here changes execution. Read this beside
`V7_DESK_AUDIT_2026-08-18.md` (the Phase 1 architecture audit).

## STANDING RULES (Phase 1A — permanent)

1. The `/v7` Truth page keeps its philosophy FOREVER: v7 sent it or it reads
   UNKNOWN. The evidence layer specced here sits BESIDE the truth layer,
   clearly labeled as history, never replacing a live UNKNOWN with a guess.
2. Nothing in this spec sends, modifies or cancels an order. Every Desk
   feature is read-only; any future dispatch path is a separate project with
   its own idempotency, audit and kill-switch spec, and starts feature-flag
   OFF.
3. No duplicate analytics. The evidence model REUSES `load_unified()`,
   `cluster_engine`, `nightly_edge`, `mae_study` and the platform's
   DecisionEvent/LaneObservation stores. A second weighting system is
   explicitly forbidden (docs/STRATEGY_INTELLIGENCE.md "What NOT to build").
4. Evidence Law applies to every number: n<20 is luck and reads PROVISIONAL;
   STRONG/WEAK cluster labels require a train/validate split and the
   VALIDATE column decides; new symbols are never pooled with old ones.

---

## 1. WHAT V7 ALREADY EMITS (verified, with sources)

| Store | Written by | One row per | Key fields |
|---|---|---|---|
| `learning/telemetry.jsonl` `_type:telemetry_open` | `learning/telemetry.py:88` via `bot.py:1029` | executed trade, at open | signal_id, symbol, side, session, hour, regime, bid/ask/**spread (bridge fill)**, atr, adx, rsi, dxy, us10y, zone, setup_type, strategy_id (DNA), grade, ai_score, pine_score, **requested_price, fill_price, slippage, latency, retries, requotes** |
| `learning/telemetry.jsonl` `_type:reject` | `telemetry.py:97` via `bot.py:1160` | rejected/blocked signal | same market snapshot + `reject_status`, `reject_reason`, strategy DNA. **Every gate verdict since 2026-08-01 is here.** |
| `learning/trades.jsonl` open+close | `learning/trade_memory.py` | executed trade | ~40 open fields (rr, risk_pct, balance_at_open, news_minutes, atr, regime…) + close: net_profit, won, **mae, mfe**, hold_time_seconds, swap, commission, be_done, partial_done. Joined by signal_id. |
| `learning/v7_status.json` + platform push | `core/v7_status.py` (2026-08-18) | every finished verdict + 5-min heartbeat | stance, **gate tag**, gate_detail, levels, executed, order_id; heartbeat: paused/hard_stopped, equity, slots w/ MAE/MFE, bridge_ok |
| `learning/flow_vector.jsonl` | `bot.py:731` | signal | dxy_dir, yield_dir, vol_regime, adx, macro_score, ny_regime, trend_day |
| `signal_memory.json` | `core/signal_memory.py` | EVERY signal incl. rejected (100/symbol ring) | entry/sl/tp, score, rsi, adx, session, zone, htf_agree, traded, trade_win, trade_pnl, future_5/15/30/60m |
| `state.json` | `bot.py` | live | slots, equity guard state, trade_history(50) |
| Bridge `/history` | `sniper_executor.py:111` | broker deal | position_id, profit, swap, commission, open/close price, close_time, close_comment — **broker truth, 168h window** |

## 2. WHAT HISTORICAL OUTCOMES ALREADY EXIST

- **Executed trades**: complete. Open facts (telemetry) ⋈ outcome (trades
  close row) by signal_id = `load_unified()` (`learning/telemetry.py:125`)
  — one trade, one row, already the feature-store join. R is derivable:
  `R = net_profit / (balance_at_open × risk_pct)` (canonical, used by
  `nightly_edge`, `cluster_analyzer`, `shadow_eye_score`).
- **Rejected signals**: the verdict and full market snapshot exist
  (telemetry reject rows), **but no outcome** — see §3/§6.
- **Cluster stats**: `learning/clusters.json` (n/wr/expectancy per
  symbol|side|session|regime) and `nightly_edge.py` (per-dimension +
  two-way combos, empirical-Bayes shrinkage K=6, one-SE lower bound,
  MIN_N=20) already compute most of "historical edge". PF is derivable from
  stored avg_win/avg_loss/wr — one small addition, not a new system.

## 3. WHAT IS MISSING (the honest gap list)

| Gap | Severity | Remedy |
|---|---|---|
| **Counterfactual outcomes for rejected signals** — `update_future_prices()` (`core/signal_memory.py:171`) exists but has **zero call sites**; every `future_*` field is null | HIGH — gate effectiveness is impossible without it | Do NOT wire a live price poller. Replay post-hoc from bridge `/candles` (§6) — deterministic, retroactive over all stored rejects, zero live-path change. The proven template is the brain's `council_calibration.py` (fill within window else NO_FILL; same-bar TP+SL ⇒ SL; 48h resolve). |
| Decision-time spread on rejects | MEDIUM (v7 audit: "spread not modeled — symmetric blind spot") | v7 bridge has no `/spread` endpoint (fill-time spread only, `sniper_executor.py:259`). Option A: add read-only `GET /spread` to the bridge (Windows ceremony). Option B: leave UNKNOWN. Never approximate from candles. |
| `news_minutes` on reject rows | LOW | Computed at `bot.py:838` but only journaled on opens. Append it to the v7_decision record at the choke point (one guarded field, append-only). |
| **Comment-hash mismatch** — bot searches `BS_<sid>` but bridge writes `BS_+md5(sid)[:8]` (`sniper_executor.py:223` vs `bot.py:1103`) | HIGH for reconciliation | Fix before any reconciliation ships: bridge stores full `BS_<sid>` when ≤31 chars (MT5 comment limit), md5 fallback only beyond; bot matches both forms. Windows deploy ceremony. |
| Dedup window is 10 min (`bot.py:288`) | MEDIUM before any Desk→bot path | Extend `seen_signal_ids` retention; a prerequisite listed in the audit, not this phase. |
| MAE/MFE 60s sampling understates extremes | LOW (documented in `mae_study.py:24`) | §5. |

## 4. LINKAGE: SIGNAL → ORDER → POSITION → RESULT

The spine already exists; one link is weak.

```
signal_id  (Pine SS-…/PB-… id, minted fallback sha256 at bot.py:284)
   │  trades.jsonl open row stores order_id   ← STRONG (written at fill)
   ▼
order_id / ticket  == broker position ticket  ← STRONG
   │  bridge /history deals carry position_id ← STRONG
   ▼
close row (net_profit, mae, mfe, duration) keyed back by signal_id
```

- **Weak link**: crash-recovery matches by MT5 *comment*, and the hash
  mismatch (§3) means the exception-path RECONCILE can never match. The
  ticket-based paths are unaffected; fix the comment anyway.
- **Platform linkage**: v7_decision.signal_id → `DecisionEvent.signal_ref`;
  broker orders arrive via the MT5 reporter into `Trade` rows. **The Desk
  must display the MT5 account number on every broker-truth row** — v7 is
  52834417; a reporter on the v18 account (52901228) or a manual order on
  either would otherwise masquerade as v7 flow (see §7).

## 5. MAE / MFE

- Today: `_monitor` samples every 60s (`bot.py:451-466`), persists through
  restarts, lands on the close row. Bias: understated extremes, documented.
- **Recommended addition (batch, $0, no live change): post-close M1 replay.**
  A nightly job pulls M1 candles for [open_ts, close_ts] from `/candles` and
  recomputes exact-to-the-minute MAE/MFE for every closed trade, storing
  `mae_m1/mfe_m1` beside the sampled values — retroactive for the entire
  journal, and the two columns cross-validate each other. `mae_study.py`
  already contains the replay math to extend.
- MAE_R / MFE_R = value ÷ sl_distance (existing convention,
  `learning/cluster_analyzer.py:23`).

## 6. HISTORICAL EDGE — the calculation, deterministically

**Executed lane (exists):** `load_unified()` rows → buckets by any of
symbol, side, session, grade, regime, DNA strategy_id, score band, hour →
n, WR, net, avg R, expectancy, PF (add: `PF = (wr×avg_win)/((1−wr)×|avg_loss|)`).
Shrinkage and MIN_N rules stay exactly as `nightly_edge.py` ships them.

**Rejected lane (new, the missing half):** a replay engine,
`v7_counterfactual.py`, batch/cron, read-only:
1. Input: telemetry reject rows (they carry entry/sl/tp/side/ts).
2. Fetch M1/M15 candles from the bridge for ts → ts+48h.
3. Honesty rules copied verbatim from `pullback_backtest.py:14-19` /
   `council_calibration.py`: no lookahead; entry must be touched within the
   fill window else NO_FILL; same-bar TP+SL ⇒ SL; conservative always.
4. Output per reject: `would_have = HIT | SL | NO_FILL | OPEN`, would-have R.
5. **Gate effectiveness table** = for each gate tag: signals killed, their
   would-have expectancy, vs the kept lane's realized expectancy —
   train/validate split, VALIDATE column decides. *A gate that killed 100
   signals of which 80 would have lost is a great gate; one that killed 70
   winners is a bad gate.* Until n≥20 per gate per validate window, the
   table prints PROVISIONAL and no gate is touched (Iron Rule 5; changing a
   gate is a strategy change, separate project).
6. Session/asset matrices (the STRONG/WEAK cluster view) come from the same
   two lanes; a cluster label is only ever printed with its n, PF and
   validate status attached.

## 7. RECONCILIATION — v7 state vs broker state (read-only, flag never fix)

Per symbol, three independent facts:
`V7 verdict` (latest v7_decision) · `V7 tracked` (state.json slot) ·
`Broker` (bridge /positions + /history).

| Case | Label | Example from the live page |
|---|---|---|
| tracked ticket present at broker, directions equal | CONSISTENT | — |
| broker position, `BS_` comment, not tracked | ORPHAN (existing `[SLOT-RECON]` adopts) | — |
| tracked, absent at broker | GHOST → close-out path | — |
| open position older than the latest opposite verdict | EXPLAINED_BY_HISTORY | **US30**: verdict=REJECT SELL, broker=2 SELLs — positions predate the verdict; a rejected signal never closes an open trade |
| position with no `BS_` comment | NOT_PLACED_BY_V7 | **SILVER**: v7's last verdict was BUY approved (a market order), yet broker shows a *pending* SELL LIMIT — v7 never places pending orders (`TRADE_ACTION_DEAL` only, `sniper_executor.py:215-226`). That order is manual or another system on the account. |
| none of the above | UNEXPLAINED ⚠ — display + Telegram, never auto-act | — |

Also mandatory: broker-truth rows always name their MT5 account; two SELLs
on one symbol cannot both be current v7 (one slot per class) — the labels
above make that legible instead of alarming.

## 8. FUTURE DESK STATE FIELDS (Phase 2 of the audit; unchanged)

`{session, regime, per-symbol: {bias, confidence}, risk_mode, news_risk,
volatility, preferred_direction, avoid, key_levels?, created_at, updated_at,
valid_until, source, version}` — a FILE first (JSONL platform convention),
written by deterministic producers (session_caller math + push_bias
EMA/ATR regime), observe-only until journal evidence justifies a gate.
Expired ⇒ reads STALE; consumers fall back to deterministic rules.

## 9. WHAT IS DETERMINISTIC

Everything in §§4-7: joins, R, PF, WR, expectancy, MAE/MFE replay,
counterfactuals, gate effectiveness, reconciliation labels, session/asset
matrices, Desk State's deterministic producers. Cost: $0, cron/batch,
no AI dependency, works when the AI provider is down.

## 10. WHAT (IF ANYTHING) NEEDS AI

Exactly one job: **session commentary** — interpreting the finished
deterministic tables into three sentences at session boundaries
("Silver carries the strongest validated v7 edge this session; Gold's
range-regime cluster is weak — don't force it"). Inputs: the tables above +
news/macro state. Structured output, session cadence only, platform
`ai_ledger` single-door + `BB_AI_WEEKLY_BUDGET_USD` cap, template fallback
`AI_CONTEXT_UNAVAILABLE` on any failure. AI never produces a number that
is not already in the tables, never a level, never an approval.

---

## BUILT 2026-08-19 — steps 1-5 shipped

| Step | Ships as | Notes / corrections the code forced |
|---|---|---|
| 1 | `learning/decisions.jsonl` (append in `core/v7_status.py`) + `v7_counterfactual.py` | **Spec §3 was wrong**: telemetry reject rows carry no entry/sl/tp and no timestamp, so they cannot drive a replay. Verdicts now journal their own levels; `signal_memory.json` backfills history. `update_future_prices()` stays unused — the batch replay supersedes it. |
| 2 | `gate_effectiveness.py` | GOOD / COSTLY / NEUTRAL / UNPROVEN from the VALIDATE half only; PF is None when either side of the ratio is missing; NO_FILL scores 0R (a gate that blocked something that would never fill is neutral, not protective). |
| 3 | `mae_recompute.py` -> `learning/mae_m1.jsonl` | Sidecar, never edits the append-only journal. Reports what 60s sampling missed, plus winners-near-stop and losers-that-reached-1R. |
| 4 | `core/order_comment.py` + `core/reconcile.py` | The comment mismatch was fixed **bot-side only** — matching both forms needs no bridge deploy and no change to what is sent to MT5. New label `MIXED_OWNERSHIP` (US30's real state). Two latent bugs found while testing: MT5 encodes BUY as integer `0`, which is falsy, so both `type or direction` and `str(v or "")` erased it. |
| 5 | `v7_evidence_report.py` -> `learning/evidence.json`; heartbeat gains `reconciliation`; dashboard panels | One computation per statistic: when the report exists it is authoritative and the dashboard's own journal join steps aside, with the page naming its source. Cluster labels STRONG (PF>=1.30 **and** positive expectancy) / WEAK / NEUTRAL / UNPROVEN. |

Cron (nightly, beside `nightly_edge.py`):
```
0 2 * * * cd /home/shyam/brother_sniper_v7 && python3 v7_counterfactual.py \
          && python3 mae_recompute.py && python3 v7_evidence_report.py
```
Still true after all five: nothing dispatches, nothing changes a gate,
threshold, level or weight, and every number carries its sample size.

## BUILD ORDER (each its own commit, each read-only)

1. `v7_counterfactual.py` replay engine + reject-lane outcomes (§6) — the
   single highest-value missing piece.
2. PF + gate-effectiveness table in the existing analytics (extend
   `nightly_edge`/`cluster_analyzer`, no new weighting system).
3. M1 MAE/MFE post-close recompute (§5).
4. Reconciliation labels on the desk pages (§7) — after the comment fix.
5. Evidence panels (session/asset matrices with n/PF/validate flags) on
   both desks, platform lane building from the same pushed records.
6. Desk State file, observe-only (§8). AI commentary last (§10).

Execution/dispatch remains OUT OF SCOPE for all six steps.
