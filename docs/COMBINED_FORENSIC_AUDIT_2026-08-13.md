# COMBINED FORENSIC AUDIT — Brother Bot / SignalMesh
**One report, both codebases.** 2026-08-13 · read-only · **no code was modified.**

| System | Repo · branch | HEAD | Tests |
|---|---|---|---|
| **Platform** | `sabuj14eu/Sniper-System` · `claude/brother-bot-trading-platform-58o7gr` | `41e59f2` (v3.1 Three-Lane honesty pass) | **163 passed** ✅ |
| **Bot box — brain** | `sabuj14eu/brother-brain-v2` · `main` | `bcea0f9` | 27 passed |
| **Bot box — v7** | `sabuj14eu/brother_sniper_v7` · `main` | `1920be6` | 45 passed |
| **Bot box — session_caller** | `sabuj14eu/session_caller` · `main` | `a699c17` | none |
| Pine | `Sniper-System/pine/` (2 files) — **not** `pinev18.6`, which is empty | — | — |

Everything claimed about the platform was verified on disk: `decision_snapshot.py`,
`opportunity.py`, `planner.build_plan` / `build_session_call`, `autonomous.py` (auto-v1),
SQLAlchemy models, Postgres in compose, 163 test functions, the Pine source. All present.
The earlier "does not exist" finding was a scope error — two systems, similar vocabulary,
separate hardware. It is corrected here and in the bot-side report.

---

## A. EXECUTIVE VERDICT

### Platform — **SAFE WITH FIXES**
The architecture is sound and, in several places, better than what it claims. Three defences are
real and I confirmed them by reading the code paths, not the comments:

- **Closed-candle enforcement at two layers.** `webhooks.upsert_candles:292-293` refuses a bar whose
  `ts + tf` has not passed, *and* `scanner.build_snapshot:157` calls `closed_only()` on read. The
  forming-candle class of bug cannot enter the canonical store or the research view.
- **Future-dated candles refused at ingest** (`webhooks.py:290-291`), with a comment naming the exact
  broker-server-time cause. This is the platform being immune to bot-box bug P0-4 by design.
- **One outcome function for all three lanes.** `ai_analyst._resolve:295-328` — trigger-first, then
  conservative same-bar SL, `NO-FILL`, `TIMEOUT` with mark-to-market, R units, no costs. Called
  identically for bot, AI and auto lanes. This is the correct pending-order engine and the bot box
  has nothing comparable.
- **A genuine missed-opportunity engine.** `gate_audit.py:74-110` shadow-resolves *rejected*
  opportunities to answer "was the gate right?". That is Phase 13/14 of the original brief, built.

Four defects hold it back — one of them contradicts the module's own central claim, and one is a
cross-tenant correctness bug.

### Bot box — **NOT READY** (unchanged)
Seven P0s, three reproduced by execution. Good dispatch safety, unsound evidence layer.

### Combined system — **the interface is the weakest link**
The platform's canonical-identity design is correct but **starved of its key**: `pine_signal_id` is
sent only by an unmerged bot branch, and the arm label it depends on is broken on arrival. See §D.

---

## B. PLATFORM FINDINGS

### PLAT-P0-1 — Every signal is labelled as the v7 arm; the two-arm comparison is structurally dead
**Files** `app/services/opportunity.py:31-32` · `app/services/fingerprint.py:44-46` ·
`app/routers/webhooks.py:105`

```python
# opportunity.py:31-32
def _arm(sig) -> str:
    return "v18" if (sig.system or "").lower() == "v18" else "v7"
# fingerprint.py:44-46
def lane(sig) -> str:
    return "BSv18" if (sig.system or "").lower() == "v18" else "BSv7"
```

Both do an **exact equality** test against `"v18"`. The brain's mirror sends Pine's `system` label —
`"BSv18"` — and `webhooks.py:105` stores it **raw**:

```python
sig.system = str(payload.get("system", sig.system or "v18"))   # ← no normalize_system()
```

`normalize_system()` exists two functions above and correctly collapses `BSv18 → v18`. It is applied
to `DecisionEvent` (line 158) but **never to `Signal.system`**.

**Executed:**

| `Signal.system` stored | `opportunity._arm` | `fingerprint.lane` |
|---|---|---|
| `'BSv18'` | **v7** ❌ | **BSv7** ❌ |
| `'BSv18ULTIMATE'` | **v7** ❌ | **BSv7** ❌ |
| `'v18'` | v18 ✅ | BSv18 ✅ |
| `'None'` / `''` | v7 | BSv7 |

**Impact.** `Signal` rows are the *only* input to `group_signals`. With every row labelled `v7`:
- `o["lanes"]` only ever holds the key `"v7"`.
- `o["disagreement"]` requires `len(o["arms"]) > 1` — so it is **always `False`**. The platform can
  never report that the two arms disagreed.
- `o["arms"]` renders as `{"v7": ...}` on every opportunity, including pure-v18 council decisions.
- `o["canonical"]` picks `lanes["v18"]` first, which is always `None`, so it silently falls through
  to the v7 slot. It works by accident, not by design.
- `gate_audit.py:88-91` surfaces `arms` and `disagreement` directly into the funnel view.

**Compounding it:** the only production writer of `Signal` rows is `webhooks.brain_signal` (verified —
`grep "Signal("` across `app/`, `scripts/`, `agents/` returns exactly `webhooks.py:101` plus
`scripts/seed.py`), and **only `brother-brain-v2` posts there**. `brother_sniper_v7` contains no
platform-posting code on any branch. So even with the label fixed, **there is no v7 `Signal` feed at
all** — v7 data arrives only as `DecisionEvent` rows via `/webhooks/brain/decision`, which
`group_signals` never reads.

**Fix.** (a) `sig.system = normalize_system(str(payload.get("system", ...)))` at ingest — one line,
and every downstream `_arm`/`lane` call becomes correct. (b) Make `_arm`/`lane` substring-based as a
belt-and-braces (`"v7" in s` / `"18" in s`), matching `normalize_system`'s own logic. (c) Decide
whether the v7 arm should produce `Signal` rows; until it does, label the two-arm UI honestly as
"v18 only" rather than showing an empty second column.

**Test.** Parametrise `_arm`/`lane` over `{"BSv18","BSv18ULTIMATE","v18","BSv7","v7","",None}`, and
assert an ingested `BSv18` payload yields `Signal.system == "v18"`.

---

### PLAT-P0-2 — The "unified snapshot" is built from **two** independent market reads
**Files** `app/services/decision_snapshot.py:51,53` · `app/routers/session_center.py:34` ·
`app/routers/planner.py:89` · `app/services/scanner.py:162,165`

The module's stated guarantee (`decision_snapshot.py:4-8`):

> *"This module COMPOSES the existing truth layer; it never recomputes a number that already has a
> home… One build = one consistent instant: Snapshot A (research), Snapshot B (bot) and every
> explanation derive from the same facts, so they can never disagree about last_close again."*

What it does:

```python
view = build_session_view(db, symbol)   # → session_center.py:34 → scanner.build_snapshot(...)  ← read #1
snap = view["snap"]
plan = build_plan(db, symbol, now)      # → planner.py:89      → scanner.build_snapshot(...)  ← read #2
```

Two calls. And `build_snapshot` is **time-dependent** — it does not take the caller's `now`:

```python
# scanner.py:162-167
candle_age_min = int((utcnow() - _aware(candles[-1].ts)).total_seconds() // 60)
ref = market_reference_time(symbol)
effective_age = int((ref - _aware(candles[-1].ts)).total_seconds() // 60)
candle_fresh = effective_age <= TF_MINUTES.get(tf, 60) * STALE_BARS
```

`build_plan` receives `now` as a parameter and then ignores it for the snapshot, calling `utcnow()`
again inside. So the two reads are taken at different instants, against a database that the ingest
and sweeper are concurrently writing, with no declared transaction isolation.

**Impact — the failure the docstring says is impossible:**
- `ds["freshness"]["candles"]` is derived from **read #1** (`candle_status(snap)`), while the hard
  gate that actually decides the plan — `planner.py:114`, `if not snap.get("candle_fresh")` — uses
  **read #2**. Straddle the `STALE_BARS` boundary and the snapshot displays **LIVE** while the plan
  returns **NO TRADE — stale market data**, or the reverse.
- `ds["market"]` (read #1) feeds `research_view` → the **AI lane**. `ds["decision"]` (read #2) feeds
  the **bot lane**. The two lanes are therefore not guaranteed to share `last_close`, `atr` or
  `structure` — which is the exact guarantee `run_round` is built on.
- A candle arriving between the reads changes `last_close` for one lane and not the other.

This does **not** invalidate the three-lane design — `run_round:279-283` correctly builds one `ds`
and hands the same object to all three lanes. The defect is one level down, *inside* `ds`.

**Fix.** Thread a single snapshot through: `build_decision_snapshot` computes `snap` once and passes
it into both `build_session_view(db, symbol, snap=snap)` and `build_plan(db, symbol, now, snap=snap)`;
`build_snapshot` accepts `now` instead of calling `utcnow()`. Then assert
`ds["freshness"]["candles"]["state"] == "LIVE"` implies the plan did not block on `DATA`.

**Test.** Monkeypatch `utcnow` to advance across the staleness boundary between the two calls and
assert the snapshot's freshness and the plan's gate agree.

---

### PLAT-P0-3 — Plan lifecycle is matched across **all users** and all manual trades
**File** `app/routers/planner.py:161-170`

```python
mt5 = (db.query(Trade).join(MT5Account, Trade.account_id == MT5Account.id)
       .filter(Trade.symbol == symbol, Trade.direction == sig.direction,
               Trade.status.in_(("pending", "open")))
       .order_by(Trade.open_time.desc()).first())
if mt5 is not None:
    plan["lifecycle"] = "TRIGGERED (position open)" if mt5.status == "open" else "PENDING in MT5 ✓"
```

The query **joins** `MT5Account` and then never filters on it. `build_plan(db, symbol, now)` takes no
`user` argument, so it cannot. Matching is on **symbol + direction + status only** — no account, no
user, no signal linkage, no entry-price check.

**Impact.**
1. **Cross-tenant.** On a multi-tenant platform (`auth.py`, `billing.py`, per-user `MT5Account`),
   user A's plan shows **"PENDING in MT5 ✓"** because *user B* holds a matching open trade. It leaks
   only a boolean, not another tenant's numbers — but it leaks it onto the one screen whose entire
   purpose is deciding whether to place that order.
2. **Single-tenant, still wrong.** Any manual GOLD BUY marks every GOLD BUY plan as already placed.
   This is precisely the "UI incorrectly associates a manual MT5 order with a bot candidate" concern.
3. `/planner` and `/ai-trading` both render it; the trade *lists* on those pages are correctly scoped
   (`planner.py:302`, `Trade.account_id == acc.id`) — which makes the mismatch harder to notice, not
   easier.

**Fix.** Pass `user` into `build_plan` and filter `MT5Account.user_id == user.id`; better, link the
`Trade` to the `Signal` that produced it and match on that identity rather than symbol+direction.

**Test.** Two users, one matching open trade on user B; assert user A's plan reads
`"READY — not yet placed"`.

---

### PLAT-P1-1 — The snapshot fingerprint omits inputs that change decisions
**File** `app/services/decision_snapshot.py:131-133`

```python
ds["fingerprint"] = hashlib.sha256(
    json.dumps({k: ds[k] for k in ("market", "news", "freshness")}, ...)).hexdigest()[:16]
```

Three of seven sections. **Excluded: `macro`, `history`, `meta`, `decision`.**

The original brief asks precisely this: *"Find fields that affect decisions but are NOT represented
in the fingerprint."* Two qualify:
- **`meta.session`** — `current_session(now)`. It is recorded on every `DecisionRecord`
  (`run_round:285`) and is a grouping key in `intel._norm_session` and `history`. Two snapshots in
  different sessions can share a fingerprint.
- **`macro`** — gated DXY/US10Y/VIX biases, built at lines 63-68 and surfaced to consumers.

`decision` is arguably correct to exclude (it is the *output*), and excluding `history`/`exposure`
keeps the fingerprint market-only — but that intent is nowhere stated, so the omission reads as an
oversight rather than a decision. `autonomous_candidate` stamps `snapshot_fingerprint` on every
candidate, so anything the fingerprint misses is a reproducibility gap in the auto lane's audit
trail.

**Fix.** Either include `macro` + `meta.session`, or document the exclusion set in the docstring and
name the fingerprint `market_fingerprint` so it cannot be mistaken for full decision state.

---

### PLAT-P1-2 — Fallback opportunity join can merge genuinely different signals
**File** `app/services/opportunity.py:35-38, 52-63`

```python
def _entries_match(a, b) -> bool:
    if a is None or b is None:
        return True          # a levels-less arm still belongs to its twin
    return abs(a - b) <= max(abs(b) * ENTRY_TOL, 1e-9)
```

`ENTRY_TOL = 1e-5` relative is appropriately tight — good. The hole is the `None` short-circuit
combined with the fallback key (`symbol + direction + 30-min window`):

- A signal with **no entry** merges into *any* opportunity on the same symbol+direction within 30
  minutes, regardless of price.
- A signal with **no `pine_signal_id`** can be absorbed into an opportunity that *has* one
  (line 59 only rejects when *both* ids are present and differ).

Two distinct Pine signals on GOLD BUY, 20 minutes apart, one lacking levels → **one opportunity**.
That is under-counting: the mirror image of the bot box's over-counting, and it lands in the same
statistics. Given PLAT-P0-1 and §D below, the fallback path is likely the *dominant* path in
production today, not the exception.

**Fix.** Require a non-`None` entry match for the fallback join, or mark `None`-entry merges as
`id_kind = "WEAK_FALLBACK"` and exclude them from headline statistics.

---

### PLAT-P2-1 — Records with no candles stay PENDING forever, with no give-up marker
**File** `app/services/ai_analyst.py:348-349`

```python
if not candles:
    continue  # no data yet — stays PENDING, never guessed
```

Honest, and better than guessing. But there is no `GIVE_UP_AFTER` and no `no_data` status — so a
record for a symbol whose feed dies is retried on every sweep forever and is silently absent from
every lane statistic. `outcomes.py` solves exactly this problem correctly (`GIVE_UP_AFTER =
timedelta(days=5)`, `outcome_status = "no_data"`, lines 26, 85-87, 102-104). The two engines
disagree about the same question.

**Fix.** Port `GIVE_UP_AFTER` / `no_data` from `outcomes.py` into `evaluate_records`, and surface the
`no_data` count next to lane stats so censoring is visible.

---

### Platform — what is right, and worth not breaking
| Guarantee | Where | Verdict |
|---|---|---|
| Closed candles only, at ingest **and** read | `webhooks.py:292-293`, `scanner.py:157` | **PASS** — defence in depth |
| Future-dated (broker-time) candles refused | `webhooks.py:290-291` | **PASS** |
| Bias staleness from decision time, not post time | `webhooks.py:342-346` (`as_of`) | **PASS** |
| Blind AI protocol | `ai_analyst.py:46-53`, `decision_snapshot.research_view:142-175` | **PASS** — strips `decision`, `exposure`, `history`, `macro`; AI receives only `meta`/`freshness`/`market`/`news` |
| AI cannot manufacture levels | `ai_analyst.py:150-167` — non-allowed levels force `decision → WAIT` | **PASS** |
| AI cannot execute | no code path from `ai_call` to orders | **PASS** |
| One outcome rule, all lanes | `_resolve` called 3× identically, `evaluate_records:350-354` | **PASS** |
| Pending-order trigger before SL | `_resolve:308-323` | **PASS** |
| Same-bar ambiguity deterministic | `_resolve:314-323`, SL checked before TP | **PASS** |
| NO-FILL is not a loss | `_resolve:324-325` | **PASS** |
| Planner never invents an entry | `planner.py:127` requires `status=="approved"` + entry/sl/tp1 | **PASS** |
| Session Call never invented | `build_session_call:220-228` — no READY ⇒ WAIT | **PASS** |
| Autonomous bot independent of Pine | `autonomous.py` — pure function of `ds`, no Signal read | **PASS** |
| No hidden candidate caps in auto lane | `autonomous.py` — no max-candidates, no daily limit, no score threshold | **PASS** |
| Rejected opportunities shadow-resolved | `gate_audit.py:74-110` | **PASS** — the bot box has no equivalent |
| Evidence Law labelling | `outcomes.py:25,151`, `stats.sample_verdict`, `wilson_ci` | **PASS** |
| News mapping auditable | `webhooks.py:404-417` + `news_map.map_event`, `mapping_note` stored | **PASS** |

---

## C. BOT-BOX FINDINGS (carried forward — full detail in `docs/FORENSIC_AUDIT_2026-08-13.md`)

| # | Finding | File · line | Reproduced |
|---|---|---|---|
| **BOT-P0-1** | Journal `outcome`/`pnl_net`/`exit_reason`/`closed_at` written `None`, never backfilled by anything in any repo | `brain/src/utils/decision_journal.py:170-174` | grep |
| **BOT-P0-2** | Brain discards Pine's `signal_id`, mints `secrets.token_hex(2)`; 300 s dedupe is in-memory and float-format sensitive; executor guard keyed on the minted id so it cannot catch Pine duplicates | `decision_journal.py:48`, `main.py:128,244,455` | code |
| **BOT-P0-3** | Both bridges return the live unclosed bar → ATR, structure, swings, session-call entries repaint | `sniper_executor.py:330`, `executor_ic_markets/src/main.py:262` | code |
| **BOT-P0-4** | Candle epochs are broker time compared to UTC → v7 stale-guard **can never fire**; `session_caller` grades against pre-signal candles | `bot.py:75-79`, `session_caller_v2.py:147` | code |
| **BOT-P0-5** | `EquityGuard` DD limits are `0.99` while the block message says `"Total DD 20pct hit"` | `risk/equity_guard.py:7-9,58` | code |
| **BOT-P0-6** | SL engine rounds to 2 dp; `within_limits` checked pre-rounding | `core/sl_engine.py:38` | **executed** — EURUSD `1.08350` → `1.08`, actual 0.005 vs reported 0.00272 |
| **BOT-P0-7** | `session_caller` calls unresolved after ~50 h stick in PENDING forever (the `continue` precedes the NO_FILL check) | `session_caller_v2.py:145-160` | code |
| BOT-P1-1 | Pine-score blend never normalised: 0-9 clamped into a 0-100 scale | `filters/ai_filter.py:72-74` | **executed** — scores 0→53, 9→56 |
| BOT-P1-3 | Cluster EV gate is an absorbing state, denominated in dollars | `governance/discipline.py:12`, `learning/cluster_engine.py:32-35` | code |
| BOT-P1-6 | Council routing uses `random.random()` — irreproducible, unjournaled | `brain/src/main.py:379-390` | code |
| BOT-P1-7 | `BRAIN_DISPATCH_MODE` defaults to `print` — journals "dispatched", sends nothing | `signals/dispatcher.py:18,37-40` | code |
| BOT-E1 | `compute_sltp` has no US100/USTEC/US30 floor → default `0.0020` ⇒ ~59-point minimum stop on USTEC; `PINETRUST_MIN_RR` defaults to `0.0` so the collapsed-R:R note is never acted on | `brain/src/compute_sltp.py:40-53`, `pine_trust.py:38-42,82` | code |

**39 gates** documented on the bot box; **11 emit nothing countable**.

---

## D. THE INTERFACE — where the two systems fail each other

This is the part neither audit could see alone.

### D-1 — The canonical join key is sent by an unmerged branch, and only by one arm
`opportunity.pine_id()` reads `raw_payload["pine_signal_id"]`. Verified across every remote branch of
both bot repos:

- `pine_signal_id` appears **once**: `brain/src/platform_mirror.py:84`, on
  `origin/claude/brain-platform-mirror-fcacwl`. **Not merged** — `origin/main` is `bcea0f9` and
  contains no such field.
- `brother_sniper_v7` has **no** `pine_signal_id` and **no platform-posting code at all** on any
  branch. (My earlier claim that I had checked "every branch of both repos" was wrong — the shell had
  not changed directory and I checked the brain twice. Re-verified properly here.)

So the platform's `PINE_ID` path depends entirely on the deployed brain running an unmerged branch.
If the box runs `main`, `pine_id()` returns `None` for every row and **100 % of opportunities take
the `FALLBACK_ID` path** — which is where PLAT-P1-2's merge hole lives.

**The saving grace:** for a *duplicated* Pine alert (bot BOT-P0-2), symbol, direction and entry are
identical and the timestamps are seconds apart, so the fallback join **does** collapse them. Your
externally-observed ~2× inflation is genuinely fixed either way. The exposure is the opposite error —
distinct signals merged — not the one you were chasing.

### D-2 — Fixing the bot's identity does not, by itself, fix the platform's arm labels
Even with `pine_signal_id` merged and flowing, PLAT-P0-1 means every row still lands in the `v7`
lane. The two-arm join would have a correct key and still produce one-armed opportunities. **Both
fixes are required, and the platform-side one is a single line.**

### D-3 — The platform is already immune to three bot bugs; the bot is not
`upsert_candles` refuses forming and future-dated bars, so BOT-P0-3 and BOT-P0-4 cannot corrupt
platform research. But the bot **trades on** that data. The platform's protection is a filter on
what it stores, not a fix for what the bot decides. BOT-P0-3/P0-4 must still be fixed at source.

### D-4 — Two outcome universes that will never reconcile
The platform resolves `DecisionRecord`s on a fixed 24 h horizon from stored 15m candles. The bot box
resolves from MT5 deal history (`reconciler.py`) with real fills, spread and commission. Same trade,
two answers, by construction — the platform's is idealised (`no costs — symmetric by construction`,
`_resolve:297`), the bot's is realised. Neither is wrong; **nothing states which is authoritative for
a given question**, and no document maps one to the other. Decide it explicitly before comparing
lane P&L to account P&L.

---

## E. UNIFIED PRIORITY LIST

Ordered across both systems. Data integrity before strategy, per Iron Rule 5.

### P0 — measurement is not trustworthy until these land
| # | Fix | System | Effort |
|---|---|---|---|
| 1 | `normalize_system()` on `Signal.system` at ingest + substring `_arm`/`lane` | Platform | **1 line + 2** |
| 2 | Thread one snapshot through `build_decision_snapshot` (pass `snap` and `now` down) | Platform | small |
| 3 | Scope plan lifecycle by user; match by signal linkage, not symbol+direction | Platform | small |
| 4 | Adopt Pine's `signal_id` as canonical id; persist dedupe; rekey executor guard | Bot | medium |
| 5 | Backfill journal outcomes from `outcomes.jsonl` by ticket, idempotent, decision fields immutable | Bot | medium |
| 6 | `copy_rates_from_pos(..., 1, n)` in both bridges; return `bar_closed` | Bot | **1 line ×2** |
| 7 | Normalise broker time → UTC at both bridges; re-verify v7's stale guard fires | Bot | small |
| 8 | `round_px` in the SL engine; recompute `sl_distance`/`within_limits` after rounding | Bot | small |
| 9 | Restore or explicitly document `EquityGuard` limits; derive messages from constants | Bot | **1 line** |
| 10 | Fix `session_caller` grading: scan from fill bar, NO_FILL check before the `continue`, stop truncating | Bot | small |
| 11 | **Merge `claude/brain-platform-mirror-fcacwl`** so `pine_signal_id` reaches `main` | Bot | merge |

### P1 — before trusting any performance number
12. Require non-`None` entry for the fallback opportunity join, or tag `WEAK_FALLBACK` *(Platform)*
13. Include `macro` + `meta.session` in the fingerprint, or rename it `market_fingerprint` *(Platform)*
14. Port `GIVE_UP_AFTER` / `no_data` from `outcomes.py` into `evaluate_records` *(Platform)*
15. Decide and document which outcome universe is authoritative for which question *(Both)*
16. Fix the Pine-score blend, then **re-derive** the "scores are anti-predictive" finding — it may be an artefact of the bug *(Bot)*
17. Re-denominate the cluster EV gate in R; add an exploration allowance so blocked clusters recover *(Bot)*
18. Deterministic grade-gate routing (hash, not `random`); journal the routing reason *(Bot)*
19. Add index floors to `compute_sltp`; unify the four symbol maps *(Bot)*
20. Emit a journal row for every silent gate — 11 of 39 today *(Bot)*
21. Decide whether v7 should produce `Signal` rows; until then label the two-arm UI "v18 only" *(Both)*

### P2 — before real money
22. Aggregate partial closes by `position_id`; timezone-aware outcome timestamps *(Bot)*
23. Scope the news gate by symbol; measure blocked-minutes/day before tuning *(Bot)*
24. Fail loudly when `BRAIN_DISPATCH_MODE` is unset *(Bot)*
25. Remove `state.json` from version control *(Bot)*
26. Delete `pinev18.6` or make it a pointer to `Sniper-System/pine/` — an empty repo is how this audit went to the wrong building *(Both)*

---

## F. THE TEN QUESTIONS — answered for the whole system

**1. Can one market snapshot produce three independent decisions?**
**YES on the platform, with one caveat.** `ai_analyst.run_round:279-283` builds one `ds` and passes
the same object to `ai_session_call`, `bot_snapshot` and `autonomous_candidate`. Caveat: `ds` itself
is assembled from **two** `build_snapshot` reads at different instants (PLAT-P0-2), so the AI lane's
market view and the bot lane's decision can disagree. **NO on the bot box** — no snapshot exists;
v7, the brain and `session_caller` each poll independently.

**2. Can the Autonomous Bot produce a valid trade while Pine says WAIT?**
**YES.** `app/services/autonomous.py:57-94` derives a BUY/SELL LIMIT purely from
`ds["market"]["structure"]` and stored levels; it never reads a `Signal` row. No max-candidate cap,
no daily limit, no score threshold, no Pine dependency. Paper-only by construction, exactly as
designed.

**3. Can AI say WAIT without blocking production?**
**YES.** `ai_analyst.build_context:46-53` returns only `research_view(ds)`, which strips `decision`,
`exposure`, `history` and `macro`. No code path runs from `ai_call` to a `Signal`, an order or the
planner. `ai_analyst.py:150-167` forces `WAIT` if the AI cites a level outside `allowed_levels`.

**4. Can one Pine signal accidentally become two opportunities?**
**On the bot box, YES** — `decision_journal.py:48` mints a random id; four independent triggers.
**On the platform, NO for duplicates, but YES for the inverse error** — `group_signals` collapses
duplicates via `pine_signal_id` or the fallback, but `_entries_match`'s `None` short-circuit
(`opportunity.py:35-38`) can merge two *genuinely different* signals into one opportunity.

**5. Can a pending order be incorrectly counted as a loss before it triggers?**
**NO, on both.** Platform `_resolve:308-325` establishes `triggered` before any SL/TP test and
returns `NO-FILL` if never hit. Bot `session_caller_v2.py:149-160` finds the fill bar first. Both are
correct. The platform's is also identical across all three lanes, which the bot box's is not.

**6. Can stale data create a candidate?**
**NO on the platform** — closed-bar enforced at ingest (`webhooks.py:292-293`) and on read
(`scanner.py:157`); future-dated bars refused (`webhooks.py:290-291`); `autonomous.py:46` hard-gates
on `freshness.candles.state != "LIVE"`. **YES on the bot box** — `bot.py:75-79`, the stale guard
cannot fire.

**7. Can historical performance silently become a trading gate?**
**NO on the platform** — `decision_snapshot.py:16,86-87` marks history *"evidence, NEVER a gate"* and
`build_plan` never reads it. **YES on the bot box** — the cluster EV gate is an absorbing state
(`discipline.py:12,68-70` + `cluster_engine.py:32-35`): once blocked, no trades ⇒ no data ⇒ blocked
forever.

**8. Can news permanently or incorrectly suppress trading?**
**Platform: no** — the gate is per-symbol via `affected_symbols`, canonicalised at ingest
(`webhooks.py:404-417`), and `UNKNOWN` stays `UNKNOWN` rather than collapsing to LOW
(`scanner.py:181-184`). **Bot: incorrectly, yes** — `bot.py:354-368` is symmetric (`abs()`) and
unscoped by symbol; not permanent (fetch failure fails open).

**9. Can the UI show a trade that does not exist in backend truth?**
**YES, on both — different mechanisms.** Platform: `planner.py:161-170` shows **"PENDING in MT5 ✓"**
for a plan the user never placed, matching any user's manual trade on the same symbol+direction.
Bot: `dashboard/backend/main.py:1066` renders `v18_net` from a field that is always `None`, so the
head-to-head panel advertises a comparison it cannot make.

**10. Is the system capable of collecting clean evidence comparing Pine vs Autonomous Bot vs AI?**
**The platform: nearly — three fixes away.** One snapshot per round ✅, one outcome rule across lanes
✅, blind AI ✅, missed-opportunity shadow resolution ✅, Evidence-Law sample labelling ✅. Blocked by
PLAT-P0-1 (every row labelled v7, so arm comparison and `disagreement` are dead), PLAT-P0-2 (the
snapshot is two reads), and PLAT-P1-2 (fallback over-merging).
**The bot box: no** — six independent reasons, unchanged.
**End to end: not yet** — and the binding constraint is the interface (§D), not either system alone.

---

## G. CLOSING

The two systems have opposite strengths, and that is worth stating plainly because it should drive
where effort goes.

The **bot box** is good at not losing money and bad at knowing what happened: signed envelopes, nonce
stores, clock guards, fail-closed margin checks, an LLM-output validator that refuses hallucinated
prices — and a journal whose outcome fields have never once been written.

The **platform** is good at knowing what happened and has no money at risk: one snapshot per round,
one outcome rule across three lanes, a blind AI protocol that is actually enforced by code, and a
shadow-resolver that asks "was the gate right?" — a question the bot box cannot ask at all.

The four platform defects share a shape: **a correct design with one line that doesn't match it.**
`normalize_system` exists and isn't called on the field that needs it. The snapshot is composed
twice instead of once. The lifecycle query joins the table it forgets to filter on. The fingerprint
covers three sections of seven. None is architectural; all four are small.

The bot box's defects are not small, but they are bounded — seven fixes, none touching strategy.

**Do not tune strategy on either side yet.** Two of the "strategy findings" you already act on are
under suspicion from confirmed bugs: "scores are anti-predictive" may be the un-normalised blend
(BOT-P1-1, executed: a perfect Pine score moves the result 3 points), and US100 performance is
measured through a 59-point default stop floor the strategy never chose (BOT-E1). Fix the
measurement, then re-derive.

**Nothing in this audit modified any code.** Diagnosis first; fixes, test plan and implementation
follow as separate reviewable changes.
