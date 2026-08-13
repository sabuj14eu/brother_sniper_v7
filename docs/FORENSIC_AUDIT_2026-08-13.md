# FULL PROJECT FORENSIC AUDIT — Brother Sniper / SignalMesh
**Date:** 2026-08-13 · **Scope:** all four attached repositories, read-only · **No code was modified.**

Repos audited:
`sabuj14eu/brother-brain-v2` · `sabuj14eu/brother_sniper_v7` · `sabuj14eu/session_caller` · `sabuj14eu/pinev18.6`

---

## 0. SCOPE CORRECTION — READ THIS FIRST

> **AMENDED 2026-08-13, after publication.** The system described in the brief **does exist** — in
> `sabuj14eu/Sniper-System`, branch `claude/brother-bot-trading-platform-58o7gr`, which was not
> attached to this session. `decision_snapshot.py`, `opportunity.py`, `planner.py`
> (`build_plan` / `build_session_call`), the three-lane template, SQLAlchemy models, Postgres and
> 163 test functions are all there. The Autonomous Bot (auto-v1) also lives there, paper-only, as
> designed. **This report audits the bot box only** — v18 brain, v7, session_caller, executors —
> which is a genuinely separate codebase on separate hardware. Read every "does not exist" below as
> "is not part of the bot box." Nothing is missing; two systems share a vocabulary.
>
> Cross-check worth recording: the platform independently detected ~2× stat inflation from outside,
> and P0-2 below identifies the cause from inside. Two independent audits, same conclusion.

The audit brief describes a system that **does not exist in these repositories**. Before any finding
below can be read correctly, this has to be stated plainly.

The brief asks for an audit of: `app/services/decision_snapshot.py`, `build_plan()`, a Decision
Funnel at `/funnel`, an "Autonomous Bot (auto-v1)", a Research Lab, `research_view()`, a three-lane
Pine/Bot/AI architecture, `canonical_opportunity_id`, `market_time.py`, `exchange_clock.py`,
`build_session_call()`, a Postgres/Redis-backed FastAPI platform, and 149 passing tests.

Verified absent — a case-insensitive content search across all four repos returns **zero hits** for
every one of these identifiers:

```
decision_snapshot / DecisionSnapshot  → 0 files
build_plan                            → 0 files
funnel                                → 0 files
three_lane / three-lane               → 0 files
research_view                         → 0 files
canonical_opportunity                 → 0 files
build_session_call                    → 0 files
market_time / exchange_clock          → 0 files
"autonomous"                          → 1 hit, in a prose docs file only
```

Facts on disk:

| Repo | Files | Reality |
|---|---|---|
| `brother-brain-v2` | 141 | v18 brain (FastAPI, 6-agent council), IC Markets + Polymarket executors, dashboard, watchdog. No DB — **JSONL files only**, no Postgres, no Redis, no ORM, no migrations. |
| `brother_sniper_v7` | 65 | v7 mechanical bot (Flask), filters, learning modules, MT5 bridge. |
| `session_caller` | 6 | 4 standalone scripts. |
| `pinev18.6` | **0** | **Empty repo. No commits on any branch. The Pine source is not in version control at all.** |

Test count is **72, not 149** (45 in v7, 27 in brain) — all pass, verified by running them.

**What this means for the audit.** I have not reported on components that do not exist, and I have
not invented findings to fill the requested phase headings. What I have done instead is run the
brief's *analytical method* — trace production paths, find gates that silently suppress decisions,
find measurement that cannot be trusted — against the code that is actually here. The mapping:

| Brief's concept | Nearest real component | Verdict |
|---|---|---|
| DecisionSnapshot | *(none)* | No frozen snapshot exists anywhere. Each consumer re-reads the market independently. |
| `build_plan()` gate chain | `bot.py::handle_signal` (v7), `main.py::_run_v18_council` (brain) | Audited in full, §4. |
| Three-lane Pine / Bot / AI | Pine→brain(council) and Pine→v7(mechanical), 2 lanes on 2 accounts | Audited, §7. **There is no third lane and no independent bot.** |
| Autonomous Bot (auto-v1) | `session_caller_v2.py` — paper only, 3×/day, never reaches an executor | Audited, §8. |
| Outcome / research evaluator | `reconciler.py::_track_closes` + `truth_layer.py` | Audited, §6. |
| Decision Funnel | *(none)* | Rejections are journaled but never aggregated or reconciled. |

The rest of this report is findings on the real system.

---

## A. EXECUTIVE VERDICT

# **NOT READY** — as a measurement system.

The trading path has genuinely good safety engineering: Ed25519-signed dispatch, nonce replay
protection, clock-sync startup guard, fail-closed margin and slot gates, an LLM-output sanity
validator (`_validate_prep_payload`), a naked-stop reconciler kill switch. That work is real and
should not be undone.

The **evidence layer underneath it is not sound**, and that is the thing the brief was actually
asking about. Six independent defects, each confirmed by code and three by execution, mean the
numbers this system reports about itself cannot currently be trusted:

1. **The decision journal's outcome fields are never written.** `outcome`, `pnl_net`, `exit_reason`,
   `closed_at` are hardcoded `None` at write time and nothing in any repo ever updates them
   (P0-1).
2. **The brain discards Pine's stable `signal_id` and mints a random one**, so the same Pine alert
   arriving twice becomes two independent decisions everywhere, and the executor's own
   idempotency guard cannot catch it (P0-2). *This is the duplication cause you asked about.*
3. **Every candle read in the system includes the live, unclosed bar** (`copy_rates_from_pos(...,0,n)`
   in both bridges) — ATR, structure, swing levels and session-call entries all repaint (P0-3).
4. **Candle timestamps are broker-server time but compared against `time.time()` UTC**, which both
   disables v7's stale-data guard and lets `session_caller` grade a call against candles that
   predate the call (P0-4).
5. **`EquityGuard`'s drawdown limits are set to 0.99** — daily, weekly and total capital protection
   are effectively disabled, while the block message still says `"Total DD 20pct hit"` (P0-5).
6. **The institutional SL engine rounds every stop to 2 decimals** — the exact bug the F3 fix
   claims to have eliminated, still live in the base path. Reproduced: EURUSD stop 1.08350 comes
   back as **1.08**, an actual 50-pip stop where 27.2 pips was computed, and the `within_limits`
   check is evaluated against the *pre-rounding* number (P0-6).

Verdict is not "unsafe to run" — it is demo, and the dispatch path is hardened. Verdict is
**you cannot yet learn anything reliable from it**, which is the stated purpose. Fix the six P0s
before running another comparison.

---

## B. CRITICAL BUGS

### P0-1 — Decision journal outcomes are never backfilled
**File** `brain/src/utils/decision_journal.py:170-174` · **Function** `write_decision`

```python
# ---- filled later by Piece B (executor close-tracker); null until then ----
"outcome": None,        # WIN | LOSS | BE | OPEN
"pnl_net": None,        # realized P/L (numeric)
"exit_reason": None,    # TP | SL | MANUAL_CLOSE | TIMEOUT | RISK_KILL
"closed_at": None,
```

**Root cause.** "Piece B" was built as a *separate* store — `executor_ic_markets/logs/outcomes.jsonl`
written by `reconciler.py::_track_closes`. Nothing ever writes back into `decisions.jsonl`. A repo-wide
search for any writer of these four fields returns only `write_decision` itself, which always writes
`None`.

**Impact.**
- The journal — described in `CLAUDE.md` as the system's memory of record ("grep the journal … this
  system's history is measured, not remembered") — contains **no outcomes at all**.
- Anything reading `decisions.jsonl` for results reads nulls. Confirmed downstream victim:
  `dashboard/backend/main.py:1066`, `"v18_net": d.get("pnl_net")` — the head-to-head panel's v18
  column is **structurally always empty** while the v7 column shows real money. The A/B comparison
  the dashboard advertises cannot render.
- `truth_layer.py` works around this by joining live against the executor's `/outcomes` at runtime,
  which means **every analysis depends on the Windows box being reachable** and no historical
  snapshot of joined truth is ever persisted.

**Reproduction.** `grep -rn '"outcome"' brain/` → only the `None` literal in `decision_journal.py`
and `patch_journal_fields.py` (the patch script that installed the same `None` literals).

**Fix.** A backfill job (or reconciler callback) that joins `outcomes.jsonl` → `decisions.jsonl` by
`ticket_id` and rewrites the four fields. Must be idempotent and must never mutate the decision
fields — only the outcome fields (see §D on immutability).

**Test.** Write a decision row with `ticket_id=X`, append an outcome for `X`, run backfill, assert
the row now carries `outcome`/`pnl_net` and that `entry`/`sl`/`tp`/`approved` are byte-identical.

---

### P0-2 — One Pine signal can become two decisions (**the duplication finding**)
**Files** `brain/src/main.py:126-135, 222-229, 244` · `brain/src/utils/decision_journal.py:42-49`

This is the item the brief flagged for special priority. Confirmed, with an exact cause.

Pine sends a stable `signal_id` in every payload (it is a protected field under Iron Rule 2). The
brain **throws it away as an identity** and mints a new one containing 2 bytes of randomness:

```python
# decision_journal.py:42-49
def new_signal_id(opportunity: dict, ts: datetime) -> str:
    ...
    tag = secrets.token_hex(2)          # ← random
    return f"{src}_{sym}_{side}_{stamp}_{tag}"
```

```python
# main.py:244
signal_id = new_signal_id(opportunity, ts_received)   # Pine's signal_id never consulted
```

Pine's real id survives only as a *display* field (`main.py:85` → `title` → journaled as
`alert_name`). It is never the key.

The only duplicate defence is `_dedupe_key`:

```python
# main.py:130-135
def _dedupe_key(body: dict) -> str:
    _side = body.get("side") or body.get("direction") or body.get("signal")
    return f"{body.get('symbol')}|{_side}|{body.get('entry')}|{body.get('sl')}|{body.get('origin','')}"
_recent_signals: dict = {}   # in-memory
_DEDUPE_WINDOW_S = 300
```

**Four independent ways the same Pine alert becomes two decisions:**

1. **Process restart.** `_recent_signals` is a plain in-memory dict (`main.py:128`). A brain restart
   or redeploy inside the 5-minute window clears it. The comment on that line even concedes the
   point — "*Brain restart clears, executor slot guard is the backstop*" — but the slot guard is a
   *trading* backstop, not a *journal* backstop. The duplicate row is written either way.
2. **Window expiry.** TradingView retries and nginx retries beyond 300s are not caught at all.
3. **Float formatting.** The key interpolates `entry`/`sl` via `f"{...}"` on the raw JSON value. The
   same price delivered once as `4288.82` and once as `4288.8200` produces two different keys.
4. **The executor guard cannot help.** `main.py:455` sets
   `result.signal_payload.setdefault("signal_id", signal_id)` — the **minted** id. The executor's
   idempotency store (`executor_ic_markets/src/main.py:196`,
   `_signal_ids.check_and_mark(str(_sid))`) therefore keys on a value that is *different for every
   duplicate*. It can only catch the same brain-decision dispatched twice; it is structurally blind
   to a duplicated Pine signal.

**Impact.** Every count in the system is inflated by an unknown factor: approval rate, rejection
mix, per-grade statistics, council calibration, cost estimates, and any Pine-vs-v7 comparison. Two
rows describing one market event are indistinguishable from two rows describing two events.

**Fix — canonical identity at the data layer, not the UI.** Derive the identity from the signal
itself and carry it everywhere:

```
canonical_id = pine.signal_id                      if present
             = sha256(symbol|side|entry|sl|tp|bar_close_ts)[:16]   otherwise
```
Use it as the journal primary key, as the executor idempotency key, and as the dedupe key. Persist
the dedupe set to disk (the executor's `NonceStore` already does exactly this and can be reused).
Keep the minted `signal_id` as a per-*evaluation* id if useful — one canonical signal may legitimately
be evaluated twice (entry, then manage) — but the canonical id is what stats must group by.

**Test.** POST the identical Pine body twice with a brain restart in between; assert exactly one
canonical id in the journal and exactly one dispatch.

> **STATUS UPDATE 2026-08-13 — the `pine_signal_id` fix is real but PARTIAL and UNMERGED.**
> Verified across every remote branch of both bot repos. `pine_signal_id` appears exactly once,
> in `brain/src/platform_mirror.py:84` on branch `origin/claude/brain-platform-mirror-fcacwl`:
> ```python
> "pine_signal_id": snap.get("signal_id"),   # join key for the platform
> ```
> What this **does** fix: the platform now receives Pine's real id on both arms' posts and can
> collapse the v18/v7 twins. The externally-detected ~2× inflation is addressed **on the platform
> side**.
>
> What it does **not** fix — confirmed by diffing that branch against `origin/main`:
> - `decision_journal.py` is **untouched**. `new_signal_id()` still appends `secrets.token_hex(2)`,
>   so the brain's own journal is still keyed on a random id.
> - The 300 s dedupe (`main.py:130-135`) still ignores Pine's id and is still in-memory.
> - The executor's duplicate guard (`executor_ic_markets/src/main.py:325`) is still keyed on the
>   **minted** id and remains structurally blind to a duplicated Pine signal. The only changes to
>   that file on the branch are an MT5 reconnect fix and a new `/cansize` endpoint.
> - **The branch is not merged.** `origin/main` is still `bcea0f9`; `git grep pine_signal_id
>   origin/main` returns nothing in either repo.
>
> Net: the platform is protected from double-counting; **the bot box's own journal and idempotency
> guard are not**. P0-2 should not be considered closed. Residual risk if Pine ever omits
> `signal_id`: `snap.get("signal_id")` yields `None` and the platform loses its join key silently.

---

### P0-3 — Every candle read includes the live, unclosed bar
**Files** `brother_sniper_v7/sniper_executor.py:330` · `brother-brain-v2/executor_ic_markets/src/main.py:262`

```python
rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)     # start_pos = 0 → CURRENT forming bar
```

Both bridges. Position 0 in MT5 is the bar in progress, whose `high`, `low` and `close` change on
every tick.

**Confirmed downstream consumers, all repainting:**

| Consumer | File | What repaints |
|---|---|---|
| v7 live ATR fallback | `bot.py:61-90` | `ATR(14)` includes a partial bar → **systematically understated early in a bar** → the `1.2 × atr` stop floor at `bot.py:901` is too tight exactly when a signal fires on a fresh bar |
| Council market vision | `brain/src/market_vision.py` | HTF trend, swing S/R, position-in-range |
| Session call generation | `session_caller_v2.py:174-207` | `atr(m15)`, `swing_lo`/`swing_hi` over `m15[-24:]`, therefore **the entry and SL prices themselves** |
| Session call grading | `session_caller_v2.py:145` | fill / SL / TP decided partly on an unclosed bar |

**Impact.** No decision in this system is reproducible. Re-running the same logic sixty seconds later
against the same "data" yields different levels. This makes backtest-vs-live comparison invalid and
violates the brief's determinism requirement at the source.

**Fix.** `copy_rates_from_pos(symbol, tf, 1, n)` — start at index 1 — in both bridges, or drop
`rows[-1]` at every consumer. Prefer the bridge: one change, all consumers fixed. Add `bar_closed`
and the bar's close timestamp to the response so consumers can assert it.

**Test.** Assert `rows[-1]["time"] + tf_seconds <= server_now` for every returned series.

---

### P0-4 — Candle timestamps are broker time, compared against UTC
**Files** `brother_sniper_v7/sniper_executor.py:334` · `bot.py:75-79` · `session_caller_v2.py:147`

The bridge returns MT5's raw `r["time"]` verbatim. MT5 rate timestamps are **broker server time**
(IC Markets ≈ UTC+2/+3), expressed as an epoch. Two consumers treat it as a UTC epoch:

**(a) v7's stale-candle guard is structurally dead** — `bot.py:75-79`:
```python
bar_s = int(tf) * 60 if str(tf).isdigit() else 900
if _t.time() - int(rows[-1]["time"]) > bar_s * 3:
    log.warning(f"[ATR] {symbol} stale candles ...")
    return None
```
With the server 2–3 h ahead, `rows[-1]["time"]` is ~7200–10800 s **greater** than `time.time()`.
The subtraction is negative, never exceeds `2700`, and the guard **can never fire** — including on a
genuinely frozen feed. This is precisely the Iron Rule 6 failure mode ("an executor served 200s for
6 days while placing nothing"), re-created in the freshness check itself.

**(b) `session_caller` grades against candles that predate the call** —
`session_caller_v2.py:147`:
```python
rows = [r for r in rows if r["t"] > c["ts"]]     # r["t"] = broker epoch, c["ts"] = time.time() UTC
```
The filter admits bars from **2–3 hours before the call was created**. A BUY LIMIT can therefore be
recorded as *filled*, and even as *HIT* or *SL*, on price action that happened before the call
existed. Fill rates and outcome counts from the only outcome-measuring component in the system are
contaminated with look-back.

Note the two bugs are mutually confirming: the same "epoch == UTC" assumption cannot be correct for
both, and in fact it is correct for neither.

**Fix.** Return an explicit UTC epoch from both bridges (`datetime.fromtimestamp(r['time'], broker_tz)
.astimezone(utc)`), or return the broker offset alongside and normalise at every consumer. Add the
server offset to `/health` so drift is observable.

**Test.** Freeze the feed, assert `fetch_atr` returns `None`. Create a call, assert grading ignores
all bars with `t <= call.ts` after normalisation.

---

### P0-5 — Capital protection is disabled while reporting that it is active
**File** `brother_sniper_v7/risk/equity_guard.py:7-9, 56-62`

```python
DAILY_DD_LIMIT_PCT  = 0.99
TOTAL_DD_LIMIT_PCT  = 0.99
WEEKLY_DD_LIMIT_PCT = 0.99
```

A 99 % drawdown limit is not a limit. Daily, weekly and total drawdown protection — priority 1 in
the documented decision chain (`bot.py:9-11`) — is off. Worse, the message it would emit still
claims a different number:

```python
# equity_guard.py:56-58
if total_loss >= total_limit:
    eq.hard_stopped = True
    return self._block("total", ..., "Total DD 20pct hit")     # ← says 20 %, threshold is 99 %
```

**Impact.** A reader of the code, the Telegram alert, or `/status` believes a 20 % total-drawdown
guard exists. It does not. This is the report's clearest example of the pattern the brief was
hunting: *architecture that looks correct while the behaviour underneath is absent.*

What **is** still live in this file: `_dynamic_risk` blocks entirely below 70 % of peak equity
(`equity_guard.py:66-67, 77-80`), and `consecutive_losses >= 3` blocks (line 63). So the guard is not
inert — it is *selectively* inert, in the least obvious way.

**Fix.** Restore intended values (or state in-file, with a dated rationale, that they are
deliberately relaxed for the demo soak — Iron Rule 7 requires risk changes to be explicit and
logged). Derive every block message from the constant, never from a literal.

**Test.** Parametrised: for each limit constant, assert a loss just over it blocks and that the
message quotes the constant.

---

### P0-6 — Institutional SL engine rounds every stop to 2 decimals
**File** `brother_sniper_v7/core/sl_engine.py:38` · **Function** `calculate_institutional_sl`

```python
sl_final = round(sl_raw, 2)
```

The `[F3 2026-07-02]` fix added `round_px()` with per-symbol digits to `bot.py` (lines 151-158) and
applied it to the trust+floor, regime-pad and breakeven paths — but **not to the SL engine itself**.
The base path `inst_sl = sl_result.sl_price` (`bot.py:921`) and the regime-pad path (`bot.py:919`,
which uses `sl_result.sl_price` as its base) both consume the 2-decimal value.

**Reproduced** (executed against the real module):

```
EURUSD BUY  entry=1.08500  raw_sl=1.08350  atr=0.00060
  returned sl_price     = 1.08
  reported sl_distance  = 0.00272     ← what within_limits was checked against
  ACTUAL distance       = 0.005       ← 1.8× the reported figure, ~50 pips
  within_limits         = True        (max allowed 0.00868)
```

Two distinct defects in one line:
- **Quantisation.** 5-digit FX stops collapse to 1-cent granularity. This is the exact failure F3
  documents ("EURUSD 1.17345 → 1.17 = SL moved ~35 pips"), still live in the engine.
- **Stale validation.** `sl_distance` and `within_limits` are computed *before* the rounding
  (lines 27-37) and never recomputed. The min/max distance bands are enforced against a number
  that is not the stop that gets sent.

**Reachability.** `trust_pine_sl` (`bot.py:881-884`) covers BSv17/BSv18/BSv11 and high-score v9.x.
Everything else — including all lower-score v9.x — takes the affected path. `SYMBOL_MAP`
(`bot.py:140-148`) admits seven 5-digit FX pairs.

**Fix.** `sl_final = round_px(symbol, sl_raw)`; recompute `sl_distance = abs(entry - sl_final)` and
evaluate `within_limits` after rounding. `round_px` must move into a shared module — it currently
lives in `bot.py` while the engine that needs it is in `core/`.

**Test.** For each symbol in `_PX_DIGITS`, assert `sl_price` retains full precision and that
`sl_distance == abs(entry - sl_price)` exactly.

---

## C. LOGIC ERRORS

### P1-1 — The Pine-score blend is arithmetically a flat penalty
**File** `brother_sniper_v7/filters/ai_filter.py:72-74` · also `bot.py:736-742`

```python
# bot.py:736 — the stated intent
# Patch L: v18 score is 0-7 (vetoes passed), v9.7 score is 0-9. Normalize to 0-100 for filter blend.
```
```python
# ai_filter.py:72-74 — what actually happens
if custom_score is not None:
    cs = max(0, min(100, int(custom_score)))     # ← NO normalisation. 0-9 clamped into a 0-100 scale.
    final = round(base * 0.70 + cs * 0.30)
```

**Executed, with `base = 76`:**

| Pine score | Blended final |
|---|---|
| 0 / 9 | 53 |
| 3 / 9 | 54 |
| 6 / 9 | 55 |
| 9 / 9 | 56 |

The entire Pine score range moves the result by **3 points**, while the blend unconditionally
destroys ~23 points of the rule score. A perfect Pine signal scores essentially the same as a
worthless one, and both score far below an unblended signal.

**Why this matters beyond the arithmetic.** `CLAUDE.md` records as settled evidence that
"SMART_SCALP grades/scores are ANTI-predictive (score ≤ 6 beat 9+)". That conclusion was drawn from
data produced by this code path. A scoring input that is compressed to a 3-point range and applied
as a 23-point flat penalty is a **plausible mechanical explanation for the observed anti-predictivity**
— it is at minimum a confound that must be eliminated before the strategy conclusion can stand.
Per Iron Rule 5 (evidence law), the finding should be re-derived after the bug is fixed rather than
acted on now.

**Fix.** `cs = round(100 * custom_score / max_score_for_system)` with the scale carried in the
payload, not inferred. Then re-run the score/grade analysis and revisit the constitution entry.

---

### P1-2 — The AI filter threshold is 5 out of 100, and the real value is not in the repo
**Files** `learning/weight_engine.py:6` · `filters/ai_filter.py:10, 88` · `.gitignore`

`DEFAULT_THRESHOLD = 5`, on a 0-100 score. Effectively no gate — `passed = final >= 5`. Meanwhile
`regime_detector.py:11-16` defines thresholds of 45/50/58/68 for the same scale, and
`ai_filter.py:37` disables them outright (`# PILOT MODE: ignore regime threshold override`). The
comment at `weight_engine.py:48-50` implies production actually runs ~35-38.

The operative value lives in `learning/weights.json`, and `learning/` is **gitignored**. So:
- The repository **cannot reproduce production behaviour** of its primary soft gate.
- Four different threshold scales coexist in the code (5, 45-68, 35-38, and `recommended = threshold+15`).
- `regime.score_threshold` is computed on every signal and used by nothing — dead weight that reads
  as an active gate.

**Fix.** Commit a `weights.default.json`, log the effective threshold at startup and on every
decision, delete or wire up `regime.score_threshold`.

---

### P1-3 — Cluster EV gate is an absorbing state and is denominated in dollars
**Files** `governance/discipline.py:12, 68-70` · `learning/cluster_engine.py:29-37` · `bot.py:826-839`

```python
MIN_EV_FLOOR = -0.5
def check_ev_gate(self, ev):
    if ev < MIN_EV_FLOOR: return False, f"EV ${ev:.2f}<floor ${MIN_EV_FLOOR:.2f}"
```

`ev` is `stats["expectancy"]` — a **weighted mean of `net_profit` in account currency**
(`cluster_engine.py:55`). Two problems:

**(a) Self-sealing feedback loop.** Cluster stats are built only from trades v7 actually executed
(`rebuild_clusters` filters `net_profit is not None`). Once a cluster key's EV drops below −$0.50,
`handle_signal` returns at `bot.py:839` before execution → no new trade → no new data for that
cluster → the EV never updates → **the cluster is blocked permanently**. There is no decay, no
re-sampling, no exploration term. Cluster keys are `symbol_session_regime_volstate`, so this
quietly retires specific market conditions forever, invisibly, one at a time.

**(b) Currency-denominated threshold on a growing account.** A −$0.50 floor is a different edge
requirement at 0.01 lots than at 0.10 lots. As `state.json` shows the balance moving
(peak 6749.72 from a 1000 base), the *same* percentage edge crosses this floor at different times.
The gate tightens as the account grows, for no strategic reason.

**Impact.** This is the strongest candidate in the codebase for "silently prevents the system from
producing useful decisions" — it is a historical-performance gate (the brief's Q7) that is invisible
in every dashboard, has no expiry, and cannot recover.

**Fix.** Denominate in R, not dollars. Add an exploration allowance (e.g. always admit 1 in N
signals from a blocked cluster, at minimum size, tagged as exploration) so blocked clusters keep
generating data. Emit the block to the journal with the cluster's n and EV so it is countable.

---

### P1-4 — Risk-sizing machinery is inert; the floor dominates
**File** `bot.py:950-960`

```python
_cluster_scale = 0.25 if _cn < 10 else 0.50 if _cn < 30 else 1.00
effective_risk = guard.risk_pct * regime.risk_scale * disc_result.position_scale * _cluster_scale
effective_risk = max(0.003, min(effective_risk, 0.01))
```

Typical live values: `guard.risk_pct = 0.01`, `regime.risk_scale ∈ {0.5, 0.85, 1.0}`,
`position_scale = 0.75` (regime confidence is `votes[winner]/total` and lands in 0.40-0.65 for most
multi-voter cases — `regime_detector.py:52-53`), `_cluster_scale = 0.25` while clusters are young.

`0.01 × 0.85 × 0.75 × 0.25 = 0.0016` → clamped up to the **0.003 floor**. Every term is discarded.
Four layers of adaptive sizing produce one constant. Not a safety bug, but the logs, Telegram
messages and `/status` present a rich sizing model that is not operating.

---

### P1-5 — The news gate is global, symmetric, and unscoped by symbol
**File** `bot.py:354-368`

```python
if diff <= 1800:  return True, ...                      # ±30 min, ANY high-impact event, ANY symbol
if diff <= 2700 and _cur in ("USD","EUR","JPY","GBP","CAD","AUD","XAU","XAG","BTC"):
    return True, ...                                    # ±45 min
```

- `diff = abs(t - now)` — the window is **symmetric**, blocking 30/45 min *after* an event as well
  as before. The variable name (`news_mins`) and the Telegram text ("News in Nmin") both present it
  as forward-looking only.
- Currency is read but **never matched against the traded symbol**. A JPY release blocks EURUSD,
  BITCOIN and US30 identically. The in-code justification ("metals/indices/crypto get whipsawed by
  ANY high-impact news") is defensible for metals; extending it to crypto and every FX cross is not
  argued anywhere.
- The `_cur` list covers essentially every currency the calendar marks high-impact, so the ±45 min
  branch is the effective rule, not the exception.
- The function returns on the **first** matching event, so the reported `mins` is not the nearest
  event — `closest` is tracked but discarded on the blocking path.

**Not** confirmed as "accidentally permanent": timezone handling is correct
(`fromisoformat` with the feed's offset, `.replace("Z","+00:00")` for Z-suffixed), and fetch failure
fails **open** (stale cache holds past-dated events whose `diff` is large). I could not quantify
actual blocked minutes/day — that needs the live calendar plus `logs/bot.log`, neither of which is
in the repo. **Recommend measuring before tuning**: the ±45 min symmetric window across ~10-25
high-impact events/week is the single most likely mechanical source of WAIT volume, and it is
cheap to count.

---

### P1-6 — Council routing: most signals never reach the council
**File** `brain/src/main.py:379-390`

```python
import random
_g = str(... "grade" ...).upper().strip()
if _g in ("A", "A+") or (_g == "B" and random.random() < (1.0 / 3.0)):
    result = await asyncio.to_thread(council.evaluate, opportunity)
else:
    result = approve_from_pine(opportunity)          # ← no council, straight to dispatch
```

Two observations, stated carefully because Iron Rule 1 is involved:

- **Iron Rule 1 says "NOTHING bypasses the council."** In the implemented system, only A/A+ and a
  sampled third of B-grades are evaluated by the council. Everything else — and *everything* when
  `AI_ENABLED` is absent (`main.py:276`) — is approved by `approve_from_pine` and dispatched. I read
  the rule's intent as "no path reaches an executor without brain-side adjudication", which
  `pine_trust` arguably satisfies (it is a coded gate, it re-validates grade/geometry, and it
  explicitly refuses `origin == "mt5_scanner"` at `pine_trust.py:59-61`, which is the rule's actual
  historical cause). Flagging it as a **documentation/enforcement gap, not a violation**: the rule
  as written does not describe the system as built, and that gap is exactly how the next bypass gets
  rationalised.
- **`random.random()` makes decisions irreproducible.** The same signal replayed takes a different
  path 1/3 of the time. No seed, and the sampling decision is not journaled — the trace records
  `mode: pine_trust` but not *why* the council was skipped. Any council-vs-pine_trust comparison is
  therefore confounded by an unrecorded coin flip. Use a deterministic hash of the canonical id
  (`int(sha256(cid),16) % 3 == 0`) and journal the routing reason.

---

### P1-7 — `BRAIN_DISPATCH_MODE` defaults to `print`
**File** `brain/src/signals/dispatcher.py:18, 37-40`

```python
self.mode = os.getenv("BRAIN_DISPATCH_MODE", "print").lower()
...
if self.mode == "print":
    return {"mode": "print", "envelope": wire}       # nothing posted
```

If the env var is unset or misspelled, the brain journals the decision, calls
`_precise_mode(result, dispatched=True)` → `"council_print"`, posts an **approved** Telegram
message, and sends nothing to MT5. The journal row's `ticket_id` is `None`, so it silently drops out
of every outcome join. This is the "green light, no tickets" failure Iron Rule 6 was written for,
sitting in a default value. Log the resolved mode at startup and surface it on `/health` (it is
already there — `main.py:62` — good) *and* on the dashboard service card.

---

## D. DATA-INTEGRITY ERRORS

| # | Finding | File · Line | Severity |
|---|---|---|---|
| D-1 | Duplicate decisions from random signal ids | `decision_journal.py:48`, `main.py:244` | **P0** (= P0-2) |
| D-2 | Outcomes never joined to decisions | `decision_journal.py:170-174` | **P0** (= P0-1) |
| D-3 | **Partial closes overwrite each other.** `_track_closes` writes one row per `DEAL_ENTRY_OUT` deal, keyed `ticket_id = position_id` (`reconciler.py:203`). `truth_layer.py:29` builds `{int(o["ticket_id"]): o for o in rows}` — **last row wins**. A scaled-out position reports only its final partial's P&L and outcome. v7's partial-close logic (`bot.py:472`) is currently disabled via `if False`, but v18 `CLOSE_ONE` and any manual partial hit this today. | `reconciler.py:191-216`, `truth_layer.py:29` | **P1** |
| D-4 | **Outcome timestamps mix timezones.** `"ts": datetime.utcnow().isoformat()+"Z"` (naive UTC, correctly labelled) alongside `"closed_at": datetime.fromtimestamp(d.time).isoformat()` — **naive local time on the Windows box, no offset, from a broker-time epoch**. Two different clocks in one record, neither self-describing. | `reconciler.py:202, 209` | **P1** |
| D-5 | **Outcome dedupe set is truncated to 500.** `self._oc_state = {"last_ts": now, "seen": sorted(seen)[-500:]}` while `last_ts` advances unconditionally. Sorting by ticket number approximates recency, so the 15-min overlap window normally covers it — but the invariant is accidental, not designed. A burst >500 deals, or non-monotonic ticket numbering, silently re-logs closes and double-counts P&L into the daily loss cap via `on_close`. | `reconciler.py:232` | **P2** |
| D-6 | **`seen_signal_ids` in v7 state grows then self-prunes on every signal** — `_mark_seen` rewrites the whole dict each call (`bot.py:294-298`) and `save_state()` rewrites `state.json` atomically. Correct, but O(n) per signal and the file is committed to git with live trade counters in it (`total_trades: 170`). Runtime state should not be in version control; it makes every deploy a potential state rollback. | `bot.py:294-298`, `state.json` | **P2** |
| D-7 | **No immutability guarantee on history.** `decisions.jsonl` is append-only by convention (`_LOCK` + `"a"` mode, `decision_journal.py:180-184`) — good. But `state.json`, `clusters.json`, `weights.json` and `session_calls.json` are all **rewritten in place**, and `session_calls.json` is additionally truncated to the last 40 entries (`session_caller_v2.py:230`). Historical calls are destroyed, not archived. | multiple | **P1** |
| D-8 | **Symbol normalisation is duplicated in four places** with different mappings: `bot.py:140-148` (`SYMBOL_MAP`), `position_check.py:19-25`, `market_vision.py:10`, `compute_sltp.py:48-53` (`_ALIASES`). `compute_sltp` has **no US100/USTEC/US30 entry at all** (see E-1). A symbol that normalises correctly in one module can fall through to a default in another. | 4 files | **P1** |

---

## E. STRATEGY LOGIC PROBLEMS

Separated from bugs, per the brief. These are places where the *strategy* may be wrong — or may be
fine and merely undermeasurable. I am not recommending strategy changes; §L is explicit that data
integrity comes first.

### E-1 — US100/US30 get a default stop floor 2-3× wider than intended *(software bug with strategy consequences)*
**File** `brain/src/compute_sltp.py:40-53`

```python
_SYMBOL_FLOORS = { "xauusd", "silver", "ethusd", "btcusd", "usdjpy", "eurusd" }   # ← no indices
_ALIASES       = { "gold", "xau", "xagusd", "xag", "silver", "eth", "btc", "xbtusd", "bitcoin" }
_DEFAULT_FLOOR = {"min_stop_pct": 0.0020, "atr_mult": 1.5}
```

`US100` / `USTEC` / `US30` are in neither map, so `_canonical("US100")` → `"us100"` → **default
floor**. At a USTEC price around 29,676 (the example in the brief), `min_stop_pct = 0.0020` is a
**59.4-point minimum stop**. Pine's 15-minute structural stops on an index are routinely tighter.

Consequence chain, all in `pine_trust`:
1. `compute_sltp` widens the stop to ≥59.4 points (`compute_sltp.py:113-121`).
2. `preserve_rr` is `False`, so **TP is left where Pine put it** (line 128).
3. R:R collapses. `compute_sltp.py:135-137` even detects this and writes
   `notes = "R:R fell to {rr} after widening -- entry too close to TP, weak trade"`.
4. **Nothing acts on the note.** `PINETRUST_MIN_RR` defaults to `"0.0"` (`pine_trust.py:38-42`) and
   `pine_trust.py:82` only rejects `if min_rr > 0.0`.

So US100 signals are systematically traded at a stop the strategy never chose and an R:R the code
itself flags as weak. This is a **bug** (missing map entries), but its effect is indistinguishable
from "the index strategy has poor expectancy" in the results — which is exactly the confusion the
brief asked to avoid. Add the index floors before drawing any conclusion about US100 performance.

### E-2 — Counter-trend penalty is applied to a score that no longer gates
The `[F8]` counter-trend multiplier (`ai_filter.py:80-87`) reduces the final score by 35 %. Against
a threshold of 5 (P1-2), a 35 % reduction changes nothing — a 76 → 49 score still passes. The
system's #1 documented loss driver is being addressed by a dial that, at the repo's threshold, has
no effect. Whether it has effect in production depends on the uncommitted `weights.json`.

### E-3 — `session_caller` ranks on trend separation, not edge
`session_caller_v2.py:187-190`: `strength = abs(e20 - e50) / atr`, then `best = max(picks, key=strength)`.
This selects the most *trending* asset, which is a reasonable prior but is never validated against
outcome. There is no historical-edge term, no per-asset calibration, and — because of the grading
bugs in §F — no clean sample to build one from. Also note `room < 0.4 * a → strength *= 0.3` is a
soft demotion, not a filter, so a call can still be issued with price sitting on the level.

### E-4 — One call per session, from a 7-asset scan
`session_caller_v2.py:216`: `best = max(picks, ...)` — **6 of 7 valid candidates are discarded and
never recorded.** The brief's Phase 8 concern ("we explicitly do NOT want 'maximum 2 candidates' as
a hidden production limitation… the database must retain all valid candidates") applies here in its
strongest form: the limit is 1, and the other candidates leave no trace. Persisting all 7 with a
`selected: bool` flag would cost nothing and would immediately create the missed-opportunity dataset
the brief asks for in Phase 13.

---

## F. HIDDEN GATES — complete inventory

Every condition capable of preventing a trade, in execution order. "Silent" = produces no journal
row and no dashboard-countable artefact.

### v7 (`bot.py::handle_signal`)

| # | Gate | Line | Condition | Hard/Soft | Silent? | Intended? |
|---|---|---|---|---|---|---|
| 1 | Secret / HMAC | 589, 595-598 | mismatch | hard | yes | ✅ |
| 2 | v17 noise filter | 613-617 | `signal ∈ INFO/WARN`, `type ∈ SCALP/MICRO/BOS…` | hard | log only | ✅ |
| 3 | v17/v18 quality | 622-630 | `type != SMART_SCALP`, `grade ∉ A/A+/B`, `v4_rr == False` | hard | log only | ✅ |
| 4 | Price-range sanity | 694-697 | entry outside per-symbol band | hard | log only | ✅ |
| 5 | Direction sanity | 699-706 | inverted SL/TP | hard | log only | ✅ |
| 6 | No-SL reject | 712-714 | `raw_sl <= 0` | hard | log only | ✅ |
| 7 | Symbol allowlist | 767 | not in `ALLOWED_SYMBOLS` | hard | yes | ✅ |
| 8 | Asset gate | 769-773 | `.env` bench list | hard | log only | ✅ off by default |
| 9 | Dedup | 777-779 | same sid within 10 min | hard | **silent** | ⚠️ see P0-2 |
| 10 | Paused / 3-loss streak | 781-783 | `state.paused` or `losses>=3` | hard | log only | ✅ |
| 11 | **Asset-class slot** | 784-789 | one open trade per metals/crypto/forex/other | hard | log only | ⚠️ **4 concurrent trades max, system-wide** |
| 12 | Margin floor | 791-799 | `balance < 500` or unreadable | hard | log only | ✅ fail-closed |
| 13 | Equity guard | 801-807 | see P0-5 — **DD tiers disabled**; <70 % peak and 3-loss still live | hard | Telegram | ❌ **P0-5** |
| 14 | **News** | 809-813 | ±30 min any high-impact, ±45 min majors, **all symbols** | hard | Telegram | ⚠️ **P1-5** |
| 15 | **Cluster EV** | 830-839 | `expectancy < -$0.50` | hard | Telegram | ❌ **P1-3 — absorbing state** |
| 16 | AI filter | 842-852 | `score < threshold` (threshold = 5 in repo) | soft (DeepSeek can override) | Telegram | ⚠️ **P1-2** |
| 17 | Trust-mode SL sanity | 885-891 | dist outside [0.02 %, 8 %] | hard | Telegram | ✅ |
| 18 | **Widen-ratio reject** | 907-910 | `floor > 1.6 × pine_dist` | hard | Telegram | ⚠️ interacts with P0-3 (understated ATR ⇒ floor too low ⇒ *under*-rejects) |
| 19 | SL within limits | 923-925 | `sl_distance > MAX_SL_PCT` | hard | Telegram | ⚠️ evaluated pre-rounding — **P0-6** |
| 20 | R:R validation | 944-948 | `rr < MIN_RR (1.0)` | hard | Telegram | ✅ |

### Brain (`main.py::_run_v18_council`)

| # | Gate | Line | Hard/Soft | Notes |
|---|---|---|---|---|
| 21 | Body secret | 205-218 | hard | permissive by default (`BRAIN_REQUIRE_SECRET=false`) |
| 22 | Dedupe window | 222-229 | hard | **in-memory, lost on restart — P0-2** |
| 23 | BSv11 early return | 234-240 | hard | Telegram-only by design ✅ |
| 24 | Slot busy (AI off) | 280-291 | hard | fail-closed ✅ |
| 25 | Executor unreachable | 298-309 | hard | fail-closed ✅ |
| 26 | Manage cost gate | 312-324 | hard | cooldown / per-ticket cap |
| 27 | Margin unreachable | 331-354 | hard | one retry, then fail-closed ✅ |
| 28 | Margin floor | 355-369 | hard | `max(10 % balance, 100)` |
| 29 | **Grade gate** | 379-390 | routing | **`random.random()` — P1-6** |
| 30 | Council vetoes | `council.py:176-261` | hard | Scout / Quant PASS / Devil veto / Risk / Prep / PrepValidation |
| 31 | Fail-soft budget | 403-436 | hard after 2/day | ✅ well designed |
| 32 | `pine_trust` grade | `pine_trust.py:64-66` | hard | grade ∉ A/A+/B |
| 33 | `PINETRUST_MIN_RR` | `pine_trust.py:82` | hard | **defaults 0.0 = disabled — E-1** |

### Executor (`executor_ic_markets/src/main.py`)

| # | Gate | Line | Notes |
|---|---|---|---|
| 34 | Bearer / signature / target / age / nonce | 271-301 | ✅ solid |
| 35 | Kill switch | 305-313 | MT5-failure kill always blocks; cap-kill bypassable via `GUARDS_DISABLED` |
| 36 | Duplicate `signal_id` | 325-327 | **keys on the minted id — cannot catch Pine duplicates (P0-2)**; also consumes the id *before* the cap checks, so a cap-rejected signal cannot be retried |
| 37 | Daily trade cap | 328-332 | `MAX_TRADES_PER_DAY=6` |
| 38 | Daily loss cap | 333-340 | `MAX_DAILY_LOSS_PCT=2.0` |
| 39 | Risk clamp | 343 | `min(risk_pct, MAX_RISK)` |

**Total: 39 gates.** Of these, **11 are silent or log-only** (no journal row, no dashboard artefact),
including the two most likely to be suppressing volume (news, cluster EV). This is the direct
answer to the brief's Phase 15/28: *the funnel cannot be built today because two-thirds of the
gate chain does not emit countable events.*

---

## G. LANE INDEPENDENCE VERDICT

There are **two** lanes, not three, and they are not independent in the way the brief assumes.

| Claim | Verdict | Evidence |
|---|---|---|
| Pine lane independence | **N/A** | Pine is the *source*, not a lane. It is upstream of both consumers. Its source is not in version control (`pinev18.6` is empty) — it cannot be audited or diffed at all. |
| v18 brain (council) independence | **PASS, with caveat** | Own account (52901228), own gate chain, own executor. Caveat: it consumes Pine's grade as a routing input (`main.py:381`) and, for non-A/A+ grades, delegates the decision back to Pine's own gate chain via `approve_from_pine`. On those signals the brain is not an independent judge — it is a relay. |
| v7 (mechanical) independence | **PASS** | Own account (52834417), own filters, own SL engine, own executor. Genuinely a second opinion. |
| "Autonomous Bot" independence | **FAIL — does not exist** | The nearest thing, `session_caller`, is paper-only, 3×/day, one call, never dispatches. See §H. |
| AI independence | **PASS** | Council output cannot reach v7. `platform_mirror.py` is genuinely one-way and correctly flagged off by default — this module is well built and its stated law is enforced by its code. |
| Snapshot equality | **FAIL** | No shared snapshot exists. v7 computes ATR from its own bridge (`bot.py:61`), the brain computes vision from a *different* bridge (`market_vision.py`), `session_caller` polls a third time. Three market reads, three timestamps, no fingerprint. Two lanes deciding on the "same signal" are demonstrably not looking at the same market state. |
| Outcome equality | **FAIL** | v7 outcomes come from `learning/trade_memory` (gitignored); v18 outcomes from `outcomes.jsonl`; `session_caller` from its own `grade_pending`. **Three different definitions of a win.** `session_caller` has NO_FILL and same-bar-SL rules that the other two lack entirely. |
| Source attribution | **PARTIAL** | The dashboard h2h joins on `alert_name` startswith `"SS-"` (`main.py:1051-1057`) — an exact string match on Pine's id, which is sound. But it silently excludes every non-`SS-` signal from the comparison, and `v18_net` is always null (P0-1), so the panel structurally cannot compare. |

---

## H. DUPLICATION VERDICT

**Confirmed.** One Pine signal can become two research/journal records. Full mechanism in **P0-2**.

Summary of the causal chain:
1. Pine emits a stable `signal_id`.
2. `main.py:244` discards it and calls `new_signal_id()`, which appends `secrets.token_hex(2)`.
3. The only defence is a 300-second **in-memory** dict (`main.py:128`) keyed on
   `symbol|side|entry|sl|origin` — no signal_id, no persistence, float-format sensitive.
4. Any brain restart, any TV/nginx retry beyond 300 s, or any float-formatting difference produces
   a second journal row with a *different* primary key.
5. The executor's idempotency store keys on the **minted** id (`main.py:455`), so it is
   structurally blind to this class of duplicate.

Separately and legitimately, nginx mirrors each alert to both the brain and v7. That is **by design**
(two accounts, the A/B experiment) and is not duplication — but note that the two systems assign
**different identities** to the same event (brain: minted id; v7: `_make_sid`, `bot.py:284-286`,
which prefers Pine's `signal_id` — v7 gets this *right*). Any cross-system join must therefore go
through `alert_name`, which is exactly what the dashboard does and exactly why it is fragile.

**Fix is at the data model, not the UI**, as the brief requires: adopt `canonical_opportunity_id`
per P0-2 and make it the join key in the journal, the executor guard, and the dashboard.

---

## I. AUTONOMOUS BOT VERDICT

**Question: can the Autonomous Bot genuinely find trades without Pine/BSv18?**

**There is no Autonomous Bot.** No file in any repo generates trade candidates from market data and
routes them toward an executor. Every executable path into MT5 begins with a Pine webhook.

The closest component is `session_caller_v2.py`, and it deserves credit: it is **genuinely
independent of Pine** — it pulls its own candles from the v7 bridge, computes its own H1 EMA trend,
its own 24-bar swing structure, its own ATR-based entry/SL/TP, and it **can and does produce a BUY
LIMIT when Pine is silent**. That is precisely the experiment the brief wants to run.

But it is not a bot:

| Property | Status |
|---|---|
| Reaches an executor | **No.** `telegram()` only. Header: *"HARD RULES: never sends anything to any bot."* |
| Frequency | 3× daily, systemd timer |
| Candidates retained | **1 of 7.** `best = max(picks, ...)`, line 216 — the other 6 vanish (E-4) |
| Pending-order semantics | Yes — fill-before-outcome, NO_FILL, same-bar conservative SL. **The only component in the system with these.** |
| Outcome grading | Yes, but broken three ways — see §J |
| Uses news / macro / correlation / exposure | **No.** None of them. |
| Uses historical edge | **No.** Pure current-structure math. |
| Dependencies on Pine/BSv18 | **Zero.** Confirmed — it imports nothing from either. |

**Recommendation.** This script is the right seed for the third lane. Promoting it means: persist all
7 candidates, fix the three grading bugs (§J), give it the canonical id, and run it against the same
snapshot as the other lanes. It should *not* be given executor access until its outcome engine is
trustworthy.

---

## J. OUTCOME ENGINE VERDICT

**Question: can we trust the reported +R/−R results?**

**No.** Three separate engines, each with defects.

### Engine 1 — v18 reconciler (`reconciler.py::_track_closes`)
The most solid of the three. Reads MT5 deal history, filters by magic and `DEAL_ENTRY_OUT`, records
`exit_reason` from the broker's own reason code — that is real truth, not inference. Defects: partial
closes overwrite (D-3), mixed timezones (D-4), 500-entry dedupe truncation (D-5). And its output is
**never joined back into the journal** (P0-1), so it cannot answer "which conditions carried edge"
without a live network call.

### Engine 2 — v7 trade memory
`learning/` is **gitignored**. I cannot audit it. That alone is a finding: the v7 half of the A/B
experiment's results live in code and data that are not in version control.

### Engine 3 — `session_caller::grade_pending` — **the pending-order logic the brief asks about**

This is the only place in the system that models pending orders, and the brief's specific question
is: *can a pending order be incorrectly counted as a loss before it triggers?*

**The core logic is correct.** Lines 149-156 find the fill bar first; only then does the SL/TP scan
begin, and it begins at `rows[filled_i:]`. A BUY LIMIT at 29676 whose price went below SL *before*
the entry was touched is **not** counted as a loss — the fill search is a separate, prior loop.
Same-bar ambiguity is handled deterministically and conservatively (`hit_sl` checked before `hit_tp`,
line 161-166). NO_FILL is explicit with a 12-hour window. This is better than most production systems.

**But three bugs make its output untrustworthy:**

**J-1 (P0) — Look-back contamination.** Line 147, `rows = [r for r in rows if r["t"] > c["ts"]]`
compares a broker-time epoch against a UTC epoch (P0-4). Bars from 2-3 hours *before* the call was
created pass the filter. A call can be graded filled — and then HIT or SL — on price action that
predates its own existence. **This inflates the fill rate and corrupts every outcome.**

**J-2 (P0) — Calls silently vanish after ~50 hours.** Line 145 fetches `candles(symbol, "15", 200)`
= 50 hours of lookback, and the fill scan always restarts from `c["ts"]`, never from the fill bar.
Once a call is older than 50 hours the filter at line 147 returns empty, line 148 `continue`s — and
because that `continue` sits **before** the NO_FILL check at 157-160, the 12-hour expiry can never
fire either. Any call not resolved inside 50 hours is **stuck in PENDING permanently**. Note the
same trap catches filled-but-running calls: line 168 sets `c["filled"] = True` but leaves
`result = "PENDING"`, so they re-enter the same broken path forever.

This is survivorship bias in the only outcome measure the system has: **slow trades are deleted from
the sample, fast ones are kept.** Slow-resolving trades are disproportionately the losers.

**J-3 (P1) — History is truncated.** Line 230, `calls[-MAX_KEEP:]` with `MAX_KEEP = 40`. At 3 calls
per day that is ~13 days of history, hard-deleted with no archive. Combined with J-2, the record of
what this strategy actually did is both censored and short.

**Also missing across all three engines:** MFE/MAE (v7 tracks it live at `bot.py:451-466` but only
for open positions), time-to-trigger, time-to-outcome, R-multiples, expectancy, max drawdown, and
any confidence interval. The brief's Phase 12 metric table cannot be produced from current data.

---

## K. TEST COVERAGE

**72 tests, all passing** (45 v7 + 27 brain — verified by execution, not by reading a badge).
Not 149. The brain suite needs `cffi` + `loguru` installed to collect at all.

What they actually prove: `_validate_prep_payload` is well covered (12 cases, real edge cases —
this is the best-tested module in the repo). Envelope crypto round-trip, tampering, replay and
staleness are properly covered. `strategy_dna`, `nightly_edge` and `telemetry` have honest unit
tests. `platform_mirror` correctly tests that the flag defaults off and that a disabled mirror is a
no-op.

What they do not touch:

| Important behaviour | Tested? | Missing test |
|---|---|---|
| `handle_signal` end-to-end (20 gates) | **No** | Golden-payload tests: one per gate, asserting the exact status/reason |
| Brain webhook routing (`_run_v18_council`) | **No** | Route table test: AI on/off × slot free/busy/unreachable × grade |
| Duplicate signal handling | **No** | Same payload twice, with a simulated restart between |
| Stale data rejection | **No** | Frozen feed ⇒ `fetch_atr` returns `None` (**currently fails** — P0-4) |
| Same-bar outcome resolution | **No** | Bar touching entry+SL+TP; assert deterministic and identical across lanes |
| Pending-order no-fill | **No** | Price crosses SL before entry ⇒ NO_FILL, not LOSS |
| Long-running call grading | **No** | Call older than 50 h ⇒ must not be stuck PENDING (**currently fails** — J-2) |
| Timezone / DST | **No** | Broker-offset normalisation; `_get_session` across a DST boundary |
| SL precision by symbol | **No** | Per-symbol digits preserved (**currently fails** — P0-6) |
| Score blend normalisation | **No** | Pine score 0-9 ⇒ monotonic, full-range effect (**currently fails** — P1-1) |
| Cluster EV gate recovery | **No** | Blocked cluster must still emit exploration signals |
| News gate windows | **No** | Event at T, assert block/allow at T±29/31/44/46 min, per symbol |
| Equity guard thresholds | Partial | Streak + normal covered; **DD tiers untested — which is why P0-5 survived** |
| Journal ↔ outcome join | **No** | Backfill idempotency; decision fields immutable |
| Partial-close accounting | **No** | Two OUT deals, one position ⇒ one aggregated outcome |

**Regression tests to add first** (each pins a P0): P0-3 closed-bar assertion, P0-4 broker-offset
normalisation, P0-6 SL precision, P0-2 duplicate collapse, P0-1 backfill, J-2 old-call grading.

---

## L. PRIORITY FIX LIST

Strictly no strategy work until P0 is clear. The brief's rule is right and I am holding to it.

### P0 — must fix immediately (measurement is invalid until these land)
1. **Canonical opportunity id** — adopt Pine's `signal_id`; persist the dedupe set; rekey the
   executor guard. *(P0-2, D-1, H)*
2. **Journal outcome backfill** — join `outcomes.jsonl` → `decisions.jsonl` by ticket; idempotent;
   decision fields immutable. *(P0-1, D-2)*
3. **Closed bars only** — `copy_rates_from_pos(..., 1, n)` in both bridges; return `bar_closed`. *(P0-3)*
4. **Normalise broker time to UTC** at both bridges; re-verify v7's stale guard fires. *(P0-4, J-1)*
5. **Fix `session_caller` grading** — scan from the fill bar, move the NO_FILL check before the
   empty-rows `continue`, stop truncating history. *(J-2, J-3)*
6. **`round_px` in the SL engine**; recompute `sl_distance` and `within_limits` post-rounding. *(P0-6)*
7. **Restore or explicitly document `EquityGuard` limits**; derive messages from constants. *(P0-5)*

### P1 — before trusting any performance number
8. Fix the Pine-score blend normalisation, then **re-derive the "scores are anti-predictive"
   finding** — it may be an artefact. *(P1-1, E-2)*
9. Re-denominate the cluster EV gate in R; add an exploration allowance so blocked clusters recover. *(P1-3)*
10. Commit `weights.default.json`; log the effective threshold; delete dead `regime.score_threshold`. *(P1-2)*
11. Make the grade gate deterministic (hash, not `random`) and journal the routing reason. *(P1-6)*
12. Add index floors to `compute_sltp`; unify symbol normalisation into one shared module. *(E-1, D-8)*
13. Aggregate partial closes by `position_id` before writing an outcome. *(D-3)*
14. Timezone-aware outcome timestamps. *(D-4)*
15. Emit a journal row for **every** silent gate (11 of 39 today) — this is what makes a funnel possible. *(§F)*
16. Add the P0 regression tests from §K.

### P2 — before real money
17. Persist all `session_caller` candidates, not just the winner; add a `selected` flag. *(E-4)*
18. Scope the news gate by symbol; make the window asymmetric; measure blocked-minutes/day first. *(P1-5)*
19. Fail loudly when `BRAIN_DISPATCH_MODE` is unset; surface it on the dashboard. *(P1-7)*
20. Remove `state.json` from version control; add outcome-store bounds and rotation. *(D-6, D-5)*
21. ~~**Put the Pine source in `pinev18.6`.**~~ **CORRECTED 2026-08-13:** the Pine source *is*
    versioned — in `Sniper-System`, branch `claude/brother-bot-trading-platform-58o7gr`, under
    `pine/` (includes the ATR zero-division fix, commit `f0f2808`). It is not unversioned; it simply
    does not live in `pinev18.6`. Residual action is smaller: **`pinev18.6` is an empty repo with no
    commits and no purpose** — either delete it or make it a pointer, so nobody audits the wrong
    place again (as this report initially did).
22. Reconcile Iron Rule 1 with `approve_from_pine`, in writing. *(P1-6)*

### P3 — improvements
23. Build the funnel endpoint once §F rows exist; reconcile counts against the journal.
24. Add MFE/MAE, time-to-trigger, time-to-outcome, R-multiples and confidence intervals.
25. Add a shared snapshot object so lanes provably decide on identical market state.
26. Index the journal (it is a growing JSONL scanned in full by several endpoints).

---

## M. THE TEN QUESTIONS

Answered directly, with file, line and evidence. Where the premise does not hold in this codebase, I
say so rather than answering a question about a system that does not exist.

**1. Can one market snapshot produce three independent decisions?**
**NO — there is no snapshot, and there are two lanes, not three.**
`bot.py:61-90` (v7 reads its own bridge), `brain/src/market_vision.py:17-36` (brain reads a
different bridge), `session_caller_v2.py:176-178` (third independent poll). Three separate market
reads at three different times, no shared object, no fingerprint. Lanes deciding on "the same
signal" are not looking at the same market state.

**2. Can the Autonomous Bot produce a valid trade while Pine says WAIT?**
**YES in principle, NO in production.** `session_caller_v2.py:174-207` generates candidates from its
own structure math with zero Pine dependency — the experiment is possible. But line 216 keeps 1 of 7,
the header at line 20 states *"never sends anything to any bot"*, and the outcome grading is broken
(§J). So the capability exists and the evidence it produces is not currently usable.

**3. Can AI say WAIT without blocking production?**
**YES.** `platform_mirror.py:1-14` and `mirror_decision:101-116` — genuinely one-way, feature-flagged
off by default, fail-silent, returns nothing the trading path reads. Council output reaches only the
v18 executor, never v7. This module is correctly built and its stated law is enforced by its code.

**4. Can one Pine signal accidentally become two opportunities?**
**YES — confirmed.** `decision_journal.py:48` (`secrets.token_hex(2)`), `main.py:244` (Pine's id
discarded), `main.py:128` (in-memory dedupe lost on restart), `main.py:455` (executor guard keyed on
the minted id, so it cannot catch it). Four independent triggers listed in P0-2.

**5. Can a pending order be incorrectly counted as a loss before it triggers?**
**NO — the fill-first logic is correct.** `session_caller_v2.py:149-156` searches for the fill bar
first; the SL/TP scan starts only at `rows[filled_i:]` (line 161). Same-bar ambiguity resolves
conservatively to SL (line 162-164), deterministically.
**But outcomes are wrong for two other reasons:** look-back contamination (J-1, line 147) and
permanent PENDING after ~50 h (J-2, lines 145-148). Nowhere else in the system models pending orders
at all — v7 and v18 both send `MARKET` orders.

**6. Can stale data create a candidate?**
**YES.** `bot.py:75-79` — the stale-candle guard compares a broker-time epoch to `time.time()`;
with the server ahead of UTC the difference is negative and the guard **can never fire** (P0-4).
Compounding it, `sniper_executor.py:330` and `executor_ic_markets/src/main.py:262` both return the
live unclosed bar (P0-3), so even "fresh" data is a partial candle.

**7. Can historical performance silently become a trading gate?**
**YES — and it is an absorbing state.** `governance/discipline.py:12, 68-70` +
`learning/cluster_engine.py:32-35` + `bot.py:830-839`. Once a cluster's dollar expectancy falls
below −$0.50 the signal is dropped before execution, so no new trade is recorded for that cluster,
so the expectancy never updates — **the cluster is blocked forever**. No decay, no exploration, no
dashboard visibility. Full analysis in P1-3.

**8. Can news permanently or incorrectly suppress trading?**
**Incorrectly: YES. Permanently: NO.** `bot.py:354-368` — `abs()` makes the window symmetric
(blocks 30/45 min *after* an event, contrary to the "News in Nmin" message), currency is read but
never matched to the traded symbol, and the returned `mins` is the first match, not the nearest.
Not permanent: timezone parsing is correct, and a fetch failure fails **open** on a stale cache
whose events are all past-dated. I could not quantify blocked-minutes/day — that needs the live
calendar and `logs/bot.log`, neither of which is in the repo. **Measure before tuning.**

**9. Can the UI show a trade that does not exist in backend truth?**
**YES, in the inverse direction — it shows a comparison the backend cannot support.**
`dashboard/backend/main.py:1066`, `"v18_net": d.get("pnl_net")` — that field is hardcoded `None` at
write time (`decision_journal.py:172`) and never backfilled, so the v18 column of the head-to-head
panel is **structurally always empty** while v7's shows real money. Related:
`dispatcher.py:18, 37-40` — with `BRAIN_DISPATCH_MODE` unset the brain journals a decision as
dispatched and posts an "approved" Telegram message while sending nothing to MT5.

**10. Is the system currently capable of collecting clean evidence comparing the lanes?**
**NO.** Six independent reasons, each sufficient on its own:
- decision↔outcome join does not exist (`decision_journal.py:170-174`);
- duplicates inflate every count (`main.py:244`);
- no shared snapshot, so lanes decide on different market states (§G);
- three incompatible definitions of an outcome (§J);
- the only pending-order engine censors slow trades and grades on pre-signal candles (J-1, J-2);
- 11 of 39 gates emit nothing countable, so no funnel can reconcile (§F).

Fix the seven P0 items and the answer becomes **yes** — the architecture is capable of it; the
plumbing is not yet.

---

## N. CLOSING NOTE

The trading-safety engineering here is better than the measurement engineering by a wide margin.
Signed envelopes, nonce stores, clock guards, fail-closed margin checks, an LLM-output validator
that refuses hallucinated prices, a reconciler that trips on a naked stop — that is careful work by
someone who has been hurt before, and the dated `[F#]` comments throughout show real forensic
discipline.

The failures cluster in one place: **the system records what it decided, but not what happened.**
Every P0 in this report is a variant of that. `CLAUDE.md` says "this system's history is measured,
not remembered" — today it is neither, because the journal's outcome fields have never been written.

That is a good problem to have. It is seven bounded fixes, not a rewrite, and none of them touch
strategy.

**Next step, per the brief's own sequencing:** this report is the diagnosis. Fixes, test plan and
implementation should follow as separate reviewable changes — P0 first, one organ per change, as
Iron Rule 5 requires. Nothing in this audit modified any code.
