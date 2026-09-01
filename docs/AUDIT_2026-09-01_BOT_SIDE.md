# BOT-SIDE ENGINEERING AUDIT — 2026-09-01

Full-code audit of `brother_sniper_v7`, `brother-brain-v2`, and the Pine →
brain / v7 / platform signal contract (`pinev18.6`). Every item carries
file:line evidence and is labeled FACT (verified code path) or HYPOTHESIS
(depends on runtime data). This list is FOR THE BOT-SIDE AGENT. The
platform-side agent has its own list in
`Sniper-System/docs/audits/AUDIT_2026-09-01_PLATFORM_SIDE.md`.

Severity: P0 = money-risk / signal-flow broken · P1 = wrong behavior ·
P2 = minor but real.

Iron rules apply to every fix: findings first, smallest safe diff, deploy
ceremony, no silent risk widening, evidence law for anything touching
strategy.

---

## SECTION 0 — META FINDING (fix before anything else)

**0.1 (P0, FACT) The GitHub copy of brother-brain-v2 is BEHIND the deployed
box.** OPEN_ITEMS says BOT-P0-2 (canonical signal_id) shipped as brain commit
`6063676` with `signal_id_source` stamped — but that commit does not exist in
the GitHub repo (`git log` head `48796e1`), the string `signal_id_source`
appears nowhere in the tree, and `brain/src/main.py:244` still mints
`new_signal_id(...)` unconditionally. Either the fix lives only on the
Contabo box (never pushed) or it regressed.
**Action:** push the box's real deployed state to GitHub, or re-apply the
adoption fix (`signal_id = body.get("signal_id") or new_signal_id(...)`,
journal both ids + `signal_id_source`). An engineering agent can only repair
code it can see — from now on, the box must run what git has (`git pull`
deploys), never hand-edits.

---

## SECTION A — brother_sniper_v7 (v7 bot + Windows executor)

### P0

**A1 (FACT) MT5 failure is reported as "zero open positions", and the bot
then fabricates $0 losses and pauses itself.**
- `sniper_executor.py:96-106` — `/positions` ignores `ensure_mt5()`'s return;
  `mt5.positions_get()` returns `None` on terminal error (falsy) → responds
  HTTP 200 `{"count":0,"positions":[]}`. A structural instance of Iron Rule 6
  ("health endpoints lie").
- `bot.py:505-531` — the monitor trusts that empty list: tracked tickets not
  in it are treated as closed; when the deal is missing from `/history` it
  logs a fallback and proceeds with `profit=0.0` → `won=False` →
  `consecutive_losses += 1`, slot cleared, fake $0 loss written to
  trades.jsonl. Three cycles of a flapping MT5 = pause (`bot.py:546-548`)
  while real positions stay open UNMANAGED at the broker.
- **Fix:** `/positions` must return 503 when `positions_get() is None`; the
  monitor must never journal a close whose deal it cannot find — retry next
  cycle, and never count unknown outcome as a loss.

**A2 (FACT) Webhook authentication is self-defeating.**
- `bot.py:584-589` — if `secret` is absent but the payload merely claims
  `system` ∈ BSv16/17/18/11 (or `version` v9*, `bot` BS_*), the bot INJECTS
  its own `WEBHOOK_SECRET` into the payload and then compares it to itself.
- `bot.py:577` — the IP check trusts the spoofable `X-Forwarded-For` header;
  `bot.py:181-182` allowlists ALL TradingView egress ranges (i.e. every
  TradingView user); `TV_HMAC_SECRET` is optional (`bot.py:131`);
  `bot.py:1347` binds `0.0.0.0:5000` when run directly.
- **Fix:** delete the auto-injection; make HMAC (or the secret) mandatory;
  take the client IP from the socket / trusted-proxy config only.

### P1

**A3 (FACT) Timeout-reconcile can never match its own order.**
`sniper_executor.py:223` writes MT5 comment `"BS_"+md5(sid)[:8]` but recovery
matches `comment == f"BS_{sid}"` (`bot.py:1101-1103`) → RECONCILE adoption
(`bot.py:1104-1135`) is dead code; SLOT-RECON later adopts with
`signal_id=f"ADOPTED_{ticket}"` (`bot.py:412`), severing the trades.jsonl
open/close join.

**A4 (FACT) Cluster/EV learning is structurally inert.**
`learning/cluster_engine.py:45` rebuilds clusters from `t.get("atr_vs_avg")`,
a field `TradeRecord` (`learning/trade_memory.py:10-36`) and `mem_open`
(`bot.py:1004-1023`) NEVER write. Rebuilt clusters all get
`vol_state="unknown"` while live lookups key on real vol (`bot.py:826`), so
EV is always 0.0, `trusted` always False, `_cluster_scale` pinned at 0.25
(`bot.py:951-952`). Either journal `atr_vs_avg` or key clusters on the
recorded fields only.

**A5 (FACT) "Fail-closed" margin gate cannot fail closed.**
`core/ic_markets.py:58-66` — `get_balance()` swallows all errors and returns
the `ACCOUNT_BALANCE` env fallback (default 6000.0), so `bot.py:792-799`'s
None branch is unreachable and sizing (`bot.py:802-803,960`) can use a
fantasy balance. If the real balance is below the fallback, risk is silently
widened (Iron Rule 7).

**A6 (FACT) Drawdown guard is set to 99% while messages claim 20%.**
`risk/equity_guard.py:7-9` — daily/weekly/total DD limits all `0.99`; the
hard-stop message still says "Total DD 20pct hit" (`:58`). If 99% is an
explicit demo decision it must be documented; otherwise restore real limits.

**A7 (FACT) AI filter fails open and its threshold is frozen.**
`learning/weight_engine.py:6` `DEFAULT_THRESHOLD=5` (on a 0-100 score) is
used whenever weights.json is missing/corrupt (`:15-18`,
`filters/ai_filter.py:22-23`), and `recalibrate` pins `new_thresh=old_thresh`
(`weight_engine.py:51`). A fresh deploy locks the Priority-5 gate at 5/100
forever.

**A8 (FACT) `SECRET` is captured at import time, before `load_dotenv()`.**
`core/ic_markets.py:12` runs when `bot.py:37` imports it; `load_dotenv()`
only runs at `bot.py:100`. Under plain `python bot.py` with only a `.env`,
every `/execute`/`/close`/`/modify` is 403'd by the executor
(`sniper_executor.py:165-166`). Same pattern in `sniper_executor.py:38`.

**A9 (FACT) Failed startup login still serves webhooks with NO monitor.**
`bot.py:1270-1272` returns from `startup()` before the monitor thread starts
(`:1274-1276`); Flask serves anyway and `handle_signal` still trades
(`ensure_connected` swallows errors, `ic_markets.py:40-45`). Positions can be
opened that nothing tracks, moves to BE, or journals.

**A10 (FACT code / timing-dependent occurrence) Dedup and state are racy
under the 4-thread gthread worker** (`gunicorn.conf.py`).
`bot.py:777-779` `_is_dup` → `_mark_seen` is a TOCTOU with no lock: two
concurrent deliveries (nginx mirror + TV retry) can both trade; the second
`set_open_trade` orphans order #1. `_state_lock` (`bot.py:209`) guards only
the file write, not the `state` dict mutations (`:239-244, 294-298,
523-526`).

**A11 (FACT) `sl_engine` still rounds SL to 2 decimals.**
`core/sl_engine.py:38` `round(sl_raw,2)`; the F3 `round_px` fix covered
bot.py's own paths (`:151-158, 911, 919`) but the non-trust path takes
`sl_result.sl_price` directly (`bot.py:921`) — 5-digit FX stops get
quantized to pip-cents (e.g. 1.16234 → 1.16).

**A12 (FACT) Dead outcome layer in signal memory.**
`core/signal_memory.py` — `mark_traded` (:267), `mark_trade_outcome` (:279),
`update_future_prices` (:171), `load_from_disk` (:369) have ZERO callers.
Every row keeps `traded:false, trade_win:null, future_*:null` forever and
the RAM store is never restored after restart. Wire them or delete them.

### P2

- **A13 (FACT)** `/close` clears the slot even when the broker close FAILED —
  `bot.py:1249-1253` never checks `resp["status"]`.
- **A14 (FACT)** WEBHOOK_SECRET leaks into gunicorn access logs —
  query-string auth on `/clusters` `/stats` `/status` (`bot.py:1190, 1196,
  1211`) + `access_log_format` with `%(r)s` (`gunicorn.conf.py:15`). Iron
  Rule 8.
- **A15 (FACT)** Signals recorded to memory BEFORE HMAC verification
  (`bot.py:591-598`) — forged payloads pollute analytics even with HMAC on.
- **A16 (FACT, version-conditional)** `weekly_report.py:199-201` is a
  SyntaxError on Python ≤3.11 (backslashes in f-string expressions). If the
  box venv is ≤3.11 the weekly report has never run.
- **A17 (FACT)** `bot.py:1047` — fresh signal with `age==0.0` records
  `signal_time=0.0` (epoch 1970) due to `and` short-circuit.
- **A18 (FACT)** `learning/cluster_engine.py:56-57` mis-parses session names
  containing `_` ("new_york" → session "new", regime "york"; display only).
- **A19 (FACT)** Two divergent copies of analyst_eye (`analyst_eye.py` 428
  lines vs `risk/analyst_eye.py` 273 lines), neither imported by bot.py.
- **A20 (FACT)** Hardcoded `/home/shyam/...` paths
  (`core/signal_memory.py:29`, `learning/signal_bus.py:30`,
  `learning/vote_worker.py`) → silent no-op persistence on other checkouts;
  `requirements.txt` pins pandas which nothing imports.
- **A21 (HYPOTHESIS)** `payload.get("version","").startswith(...)`
  (`bot.py:586, 883`) raises AttributeError → HTTP 500 if `version` ever
  arrives as a number.

---

## SECTION B — brother-brain-v2 (brain, executor, dashboard, watchdog)

### P0

**B1 (FACT) Brain still mints its own signal_id — see META 0.1.**
`brain/src/main.py:244` (`new_signal_id`, `decision_journal.py:42-49`); the
Pine id survives only as `market_snapshot.signal_id` /
`pine_signal_id` (`platform_mirror.py:84`); the executor's ticket registry is
keyed to the MINTED id (`main.py:475`), so cross-arm joins fall back to
alert_name string hacks (dashboard `main.py:1052-1055`). This is why
FALLBACK_ID still shows on /funnel.

**B2 (FACT) Journal outcomes are only filled by a MANUAL script — and the
script has a data-loss race.**
`decision_journal.py:170-175` writes outcome/pnl_net/exit_reason/closed_at
as None; the only filler is `brain/backfill_journal_outcomes.py` (commit
`49b4ab5`) which nothing schedules (no cron/systemd timer in `deploy/`).
Race: it reads the journal (`:77`), then `os.replace()`s it (`:131`) — any
decision row the live brain appends in between is DESTROYED, and the
line-count guard (`:111`) compares against its own snapshot so it cannot
detect this.
**Fix:** run it from cron/timer BUT make it append outcome-update rows (or
take a write lock with the brain), never rewrite the live file.

### P1

**B3 (FACT)** `/webhook/polymarket` is completely unauthenticated and crashes
on bad JSON — `brain/src/main.py:501-509` (no secret, unguarded
`request.json()`). Anyone reaching the port triggers a PAID council run and,
live, a signed dispatch.

**B4 (FACT)** Dashboard can flip the brain's AI mode without auth —
`dashboard/backend/main.py:1262-1270` `POST /api/ai-toggle` writes the
`AI_ENABLED` file; `TokenMiddleware` runs OPEN when `DASHBOARD_TOKEN` unset
(`:84-86`); token also accepted as `?t=` query param (`:88`, baked into
frontend at `:1114`) → lands in nginx logs.

**B5 (FACT)** Executor `/candles` infers the broker clock from ONE witness
and silently assumes 0 — `executor_ic_markets/src/main.py:270-283`: single
BTCUSD tick; on failure/stale/≥6h it keeps `_off=0` and still returns
`"utc_normalized": true`. Direct violation of "A CLOCK NEEDS TWO WITNESSES",
and a single scalar offset across DST seasons. Port the platform reporter's
≥2-witness refusal logic.

**B6 (FACT, contract bug)** Watchdog's daily-loss alert can never fire for
the IC executor — `watchdog/src/main.py:144-147` reads
`payload["pnl_pct_today"]`; IC `/health`
(`executor_ic_markets/src/main.py:202-213`) never returns that field.

**B7 (FACT)** `push_bias.py` reads Pine fields at the WRONG NESTING → bias
output is fabricated-neutral — `brain/push_bias.py:95-104,120,143-161` read
`trend/vol_regime/dxy_dir/yield_dir/oil_spike` at top level of `signal_raw`,
but they live under `signal_raw.context.market_snapshot`
(cf. `truth_layer.py:29-34` which does it right). Journal-derived trend is
always "neutral", `risk_level` never set, macro fallback rows never emitted.
**This is the prime suspect for BOT-BIAS-1 (SILVER/US100 bias silent) —
investigate here first.**

**B8 (FACT)** The executor's own single-MT5-worker rule is violated by three
paths — `/health` (`main.py:212`), `_on_admin_status` (`:123`), and
`_on_admin_halt` (`:113`, close-all racing the worker thread) call MT5
directly instead of via the 1-thread pool (`:48-53`).

### P2

- **B9 (FACT code / magnitude HYPOTHESIS)** Close-tracker mixes three clocks
  — `reconciler.py:175` naive local to `history_deals_get`; `:202` UTC ts;
  `:209` `fromtimestamp(d.time)` treats broker-server epoch as local;
  `executor main.py:164` then treats `close_epoch` as UTC for the daily
  loss-cap gate. EET/EEST closes near midnight book to the wrong day.
- **B10 (FACT)** Two "day" definitions in ExecutorState — `state.py:16,34`
  local `date.today()` vs `:53` UTC in `roll_if_new_day`: a restart between
  the two midnights refreshes the daily trade budget early.
- **B11 (FACT)** Dashboard reads `dispatch_outcome` but the journal key is
  `dispatch` (`dashboard/backend/main.py:509` vs `decision_journal.py:149`)
  → always null in `/api/decisions/approved`.
- **B12 (FACT)** TokenMiddleware raises HTTPException inside
  BaseHTTPMiddleware → bad tokens return 500 not 401
  (`dashboard/backend/main.py:92`).
- **B13 (FACT)** `requests` missing from `executor_ic_markets/requirements.txt`
  → `notify.py:11-13` ImportError swallowed → ALL executor Telegram alerts
  (orphans, rejections, closes) silently dead on a clean install.
- **B14 (FACT)** Idempotency key burned at CHECK time — `executor
  main.py:366-368`: if `open_position` then fails, a legitimate re-dispatch
  within 6h is rejected as `duplicate_signal_id`.
- **B15 (FACT)** A crash in the gate/council block loses the journal row
  entirely — `brain/src/main.py:411-413` catch-all returns without
  `write_decision`, breaking the one-row-per-signal invariant.
- **B16 (FACT)** `signal_raw` is NOT raw — `decision_journal.py:167-169`
  stores the normalized opportunity; original `signal`/`direction`
  casing/values never reach the journal (`main.py:95-102`).
- **B17 (FACT)** Reconciler prune-vs-open race fires false CRITICAL ORPHAN
  alerts and re-adopts without signal_id/nonce (`reconciler.py:86,133-157`).
- **B18 (FACT)** `brain/brain.out` — 7,977 lines of production log committed
  (`.gitignore` misses `*.out`). Remove + ignore.
- **B19 (FACT)** Retry API spend never recorded — `brain/src/agents/base.py:183-194`
  `_retry()` skips `_record_spend` and hardcodes `cache_control`, weakening
  the weekly budget guard.
- **B20 (FACT, low risk)** Non-constant-time bearer compare — `executor
  main.py:306` (contrast `halt_admin.py:46`).

Checked and sound: envelope signing/nonce chain, `compute_sltp` geometry,
`_validate_prep_payload` fail-closed gate, the 07-31 audit fixes (modulo
B6/B9/B10).

---

## SECTION C — Pine + cross-system contract (bot-side actions)

### P0

**C1 (FACT) Pine `signal_id` has NO symbol component → v7 cross-symbol
dedup swallowing.** Pine builds `"SS-BUY-" + bar-open-UTC`
(pine:2320-2327; PB at 1590/1599): GOLD and SILVER firing on the same bar
close emit IDENTICAL ids. v7 dedups on the raw id alone (`bot.py:284-286`,
10-min window `:134,291`) → the second symbol's trade is dropped as
"duplicate" (`bot.py:777-779`). v18.11 fixed the BUY/SELL half of this;
the per-symbol half remains.
**Immediate fix (no Pine ceremony): key v7's dedup on `symbol + signal_id`
— one line in bot.py.** At the next alert ceremony, also append the symbol
into the Pine id.

### P1

- **C2 (FACT)** `htf_agree` read but never emitted — `core/signal_memory.py:102`
  reads `htf_agree`; Pine emits `htf_align` (pine:2327/1591). Every stored
  v7 signal has `htf_agree:false` → poisons any bucketed stat. One-line fix.
- **C3 (FACT)** The brain's platform mirror STRIPS `pine_ver`,
  `payload_schema`, `fired_at`, `session`, `tf`, `score` —
  `platform_mirror.py:66-102` forwards only 14 keys. The platform's
  sensor-version model then reads every v18 row as UNSTAMPED
  (`evidence_integrity.py:720-729`) and `Signal.tf=""` for the whole v18
  stream. Fix in `build_platform_payload`: forward the tail fields (append-
  only — safe). Note Pine's tf vocabulary ("15","60") ≠ platform canonical
  ("15m","1h") — the platform list covers normalization on their side.
- **C4 (FACT)** v7 drops ALL PULLBACK signals — `bot.py:622` rejects
  `type != "SMART_SCALP"` and the `v4_rr` gate (`:621,629`) would drop them
  anyway (PULLBACK carries no `v4_rr`). The validated PULLBACK engine
  (n=640, PF 1.30-1.45) is traded by the v18 arm ONLY. If intentional,
  document it as a routing decision in this repo; it is currently just a
  side effect of a noise filter.
- **C5 (FACT)** Brain has NO `type` gate — MANUAL_GATE alerts (no
  symbol/direction/entry, `dir` instead — pine:1664) become
  `symbol=None` opportunities that fall THROUGH the C/D pre-gate
  (`main.py:283-285`) into the council (real API spend + junk journal row).
  Mitigated only by `manAlertOn` defaulting false. Add a type whitelist at
  ingest.

### P2

- **C6 (FACT)** `fired_at` (epoch ms) is read by NOBODY; the platform's
  `parse_event_ts` reads `ts`/`timestamp` (keys nobody sends) and rejects
  ms-epochs anyway → every v18 DecisionEvent has `event_time=None`. Fix
  jointly: mirror forwards `fired_at`; platform parses ms (their list).
- **C7 (FACT)** Session vocabulary split — Pine `"NEW YORK"/"OFF-HRS"`
  (pine:533) vs v7 fallback `"NEW_YORK"/"ASIAN"/"OVERLAP"`
  (`signal_memory.py:51-61`) — one store, two vocabularies.
- **C8 (FACT)** Mirror sends `rejection_reason`/`rejected_by`; platform's
  indexed `reason` column reads `reason` → always "". (Either rename in the
  mirror — append-only allows ADDING `reason` — or platform reads the
  existing keys; agreed fix goes to whichever side moves first.)
- **C9 (FACT)** `tp` semantics drift: Pine `tp`≡`tp1`, `rr` is TP1-based
  (pine:2232); v7 may trade `tp2` when tp1 < 1R (`bot.py:666-672`);
  brain trades tp1 only. Three definitions of "the TP" for one payload —
  document, and journal WHICH tp was traded.
- **C10 Pine defects for the NEXT alert ceremony (batch them into one
  save):**
  - `rr2` unguarded division (pine:1591,1600 vs guarded `pbRRb` at 1590) —
    ATR==0 emits `"rr2":NaN` = INVALID JSON, killing the parse at every
    consumer.
  - `signal_id` embeds bar-OPEN time while `fired_at` is close time
    (pine:2322 vs 1576) — ids lag by one bar duration.
  - Legacy session mode uses bar-open hour (pine:524,530-532) → session
    label flips one bar late; journal's session field is two populations.
  - `vwapSide` asserts "BELOW" when VWAP is na (pine:500) — should be
    UNKNOWN (Freshness-Law class).
  - `USTEC` missing from the US100 whitelist/auto-detect (pine:449-463) →
    a USTEC chart emits NOTHING (fail-closed UNKNOWN market), while the
    platform treats USTEC as a live alias (HYPOTHESIS re: which feed name
    the box charts use).

Clean (verified, no action): all alerts fire `once_per_bar_close`
(+`barstate.isconfirmed` on PULLBACK); `request.security` uses the
non-repainting `[1]+lookahead_on` idiom throughout; pullback levels freeze
at arm; no forming-bar leak found.

---

## SUGGESTED ORDER OF WORK (bot side)

1. META 0.1 — reconcile GitHub with the box (everything else depends on it).
2. A1 (fake $0 losses / self-pause) + A2 (auth) — money-risk now.
3. B7 (push_bias nesting — likely BOT-BIAS-1 root cause) and B3/B4 (open
   endpoints).
4. C1 + C2 — two one-line fixes that stop silent signal loss / data poison.
5. B2 (schedule + de-race the outcome backfill), B1/0.1 signal_id adoption.
6. C3 (mirror forwards the tail) — unblocks platform-side M-items.
7. Then the P1 tail (A3-A12, B5-B8), then P2s.

Each fix: own branch, regression test first where feasible, `pytest`/compile
checks, deploy ceremony, entry in docs/OPEN_ITEMS.md until verified live.

---

## VERIFICATION ROUND — 2026-09-02 (audit session, against pushed branches)

- **META 0.1 → WITHDRAWN, with a process finding.** Commit `6063676`
  (Pine id adopted via `canonical_signal_id` + `signal_id_source`) exists on
  `claude/evidence-integrity-audit-35rlfa`; the audit clone did not have
  that branch. B1 is DONE. Remaining risk: `main` in both repos is stale
  relative to the deploy branch — two truths in one repo. Recommend making
  the deploy branch the default or merging it to main after each round.
- **"Audit file never pushed" → REFUTED.** The branch
  `claude/signalmesh-autonomous-engineer-9lj1na` exists on both remotes
  (brain `0a2e377`, v7 `5be81d9`); the bot session had not fetched it.
- **C1 → STANDS, re-verified on the deploy branch.** `bot.py:285` returns
  the RAW Pine signal_id whenever present; the sha256(symbol-direction-
  entry) at `:286` is only the fallback when the payload has no id. Pine
  always sends an id on SMART_SCALP/PULLBACK, and its ids carry no symbol —
  so two symbols firing the same direction on the same bar close collide and
  the second is dropped as "duplicate". Fix: prefix the symbol
  (`f"{p.get('symbol','')}:{p['signal_id']}"`); retries/mirror duplicates
  carry the same symbol, so dedup is not weakened.
- **A2 "XFF fixed" → NOT ON THE PUSHED BRANCH.** `bot.py:577` on
  `claude/evidence-integrity-audit-35rlfa` still takes the FIRST
  X-Forwarded-For entry (attacker-controlled). Auto-injection staying until
  the nginx mirror injects the secret is ACCEPTED as a sequencing decision.
- **Spot-checks PASSED:** C2 (htf_align + red→green test), C3 (mirror
  forwards pine_ver/payload_schema/fired_at/session/tf/score), A6 (limits
  untouched, honest message + loud startup line), B3 (auth block present —
  fail-closed behavior when env unset goes to the Friday verify list).
- **A1 10-cycle policy → ACCEPTED** over infinite retry, on condition the
  unverified close is journaled as UNVERIFIED and never increments
  consecutive_losses — confirm in the Friday round.
- **Deploy gap:** no work has reached the Windows VPS yet. Every fix
  touching `sniper_executor.py` (A1 executor 503) or
  `executor_ic_markets` (B5 when built) is in git only until the Windows
  services (NSSM SniperExecutorV7/V18) are updated and restarted with the
  ceremony. Git green ≠ live.

---

## MILESTONE ACCEPTANCE + FREEZE (locked 2026-09-02, explicit user decision)

The observability milestone is COMPLETE only when BOTH chains have real,
recorded evidence — not "the page renders":

CHAIN 1 (engineering): watcher → incident auto-opened → investigation →
root cause + fix + tests written INTO the incident → visible in the
browser → human APPROVE/REJECT → real recovery → RESOLVED → audit trail
preserved. (Day-one state: 3 incidents auto-opened unattended 21:57:32;
fallback_id 0/29; 621 tests. The open half: work INC-0001/2/3 through the
UI to resolution — they ARE the acceptance test, do not stage a fake fault.)

CHAIN 2 (trading eyes): live market data → source + timestamp + freshness
→ Live Trading Brain (/brain-view) → honest state. STALE/UNKNOWN never
becomes a direction.

THEN: 🧊 FREEZE. No new indicators, no new AI council, no new autonomous
trading logic, no "one more feature". The system runs and collects
evidence; the next phase begins only after the eyes have proven honest
over time. The reds on the board are not embarrassing — they are the
product working.

Still open at lock time: brain restart + 5.01 pull; INC-0001 (does US10Y
15m ever flow? — bot side answers), INC-0002 (bias coverage USA500/
XRPUSD/USOIL — bot side), INC-0003 (expected to resolve/re-scope under
5.01 — platform side); Git↔Production MATCH after restart (two honest
exceptions recorded); first APPROVE audit rows; Friday verification list;
PLAT-HOLDOUT-1 (the ONE build item exempt from the freeze, since it
enforces an existing law).
