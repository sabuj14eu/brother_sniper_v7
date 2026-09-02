
## WORK ORDER 2026-09-01 — STATUS (steps 0-2 + safe parts of 3/5/6)

META 0.1: FALSE ALARM — commit 6063676 EXISTS and main.py:247 adopts
  Pine's signal_id with signal_id_source stamped. The auditor diffed the
  DEFAULT branch (main); all live work deploys from
  claude/evidence-integrity-audit-35rlfa. Neither never-pushed nor
  regressed: wrong branch compared. (Also: the referenced
  docs/AUDIT_2026-09-01_BOT_SIDE.md exists on NO branch of either repo —
  the audit session has not pushed it; item codes taken from the order.)
A1: DONE (previous commit) — patch_truth_guards.py (shape guard +
  10-cycle unverified-close guard; no journal write, no loss count, slot
  held) + patch_executor_positions.py (503 on MT5 down). Note: the order
  wants "retry forever"; the shipped guard retries 10 cycles then closes
  LOUDLY as unverified — an orphan-slot forever is its own risk; say the
  word to make it infinite.
A2: PARTIAL, BY DESIGN — XFF now trusted only from loopback (shipped).
  Deleting the secret auto-injection outright would cut off every Pine
  signal mirrored by nginx (they carry no secret — that is WHY the
  injection exists). Deletion requires the nginx mirror to inject the
  secret first: one config change on the box, then V7 flips to
  mandatory. Blocked on that coordination, not forgotten.
C1: REFUTED, NOT IMPLEMENTED — v7's dedup key is
  sha256(symbol-direction-entry) (bot.py:286): symbol is already in it,
  the claimed GOLD/SILVER collision cannot occur, and switching to
  symbol+signal_id would WEAKEN dedup (same-entry refires under new ids
  would pass). Changing dedup semantics is a trading-behavior change on
  a false premise; auditor asked to re-verify against bot.py:286.
C2: DONE — Pine emits htf_align (verified in v18.13 source; htf_agree
  appears nowhere in Pine). core/signal_memory.py now reads htf_align
  with htf_agree fallback. Tests: test_signal_memory_htf.py (RED->GREEN).
  Every historical htf_agree=False is untrustworthy — analytics beware.
B7: DONE (previous commit) — push_bias reads both nesting levels;
  rehearsed on both shapes. Watch DXY/US10Y/OIL return after deploy.
B3: DONE — /webhook/polymarket: v18 body-secret scheme + header gate +
  bad-JSON 400.
C3: DONE — mirror forwards pine_ver, payload_schema, fired_at, session,
  tf, score (append-only). PLATFORM SESSION: ship your normalizer.
C4: RECORDED — PULLBACK stays v18-only on purpose (comment at the bot.py
  gate; auto_live is the pullback engine, in shadow). Friday revisit.
A6: DONE — block message now prints the real limit; loud startup line
  "DD guard effectively OFF (99%) — demo decision". No numbers changed;
  Shyam's plain-words sentence ships real limits when he says it.
B4: platform session, but the CODE LIVES IN brother-brain-v2/dashboard/
  backend/main.py — they must commit into brother-brain-v2.
QUEUED (next rounds, one organ at a time): B5 /candles two-witness,
  B2 backfill race + schedule, then STEP 7 P1s in order.
BRANCH NOTE: all fixes are committed to claude/evidence-integrity-audit-
  35rlfa, not per-item agent/* branches — this session's box deploy flow
  (single-file checkouts Shyam pastes) all fetch from this one branch;
  splitting it would break his pastes and cost him tokens. Same tests,
  same ceremony, one branch.

## ROUND 2 STATUS (2026-09-02 follow-up order)

1. C1: THE AUDITOR WAS RIGHT — my refutation read a truncated view and
   missed bot.py:285 (raw Pine id as dedup key when present; Pine ids
   carry no symbol). Fixed test-first: key is now symbol:signal_id
   (patch_dedup_symbol.py; test_round2_guards.py::test_c1_* — two symbols
   same id both trade, same-symbol duplicate still refused, fallback
   unchanged). Lesson recorded: never refute from a partial read.
2. A2: repo bot.py now carries the XFF guard IN THE FILE — every patch
   family (truth guards v1+v2, pine_structure, dedup, freshness, mirror
   close) is applied to the repo copy, so the pushed branch shows what
   the box runs. Box deploy stays via the idempotent patch scripts.
3. WINDOWS: ceremony paste issued this round (below in chat) for
   patch_executor_positions.py (A1 503) on SniperExecutorV7 and the B5
   two-witness main.py on SniperExecutorV18. Git green != live until run.
4. A1 CONFIRMED: test_round2_guards.py::
   test_a1_unverified_close_increments_no_loss drives the patched
   accounting verbatim — deal=None: consecutive_losses and total_losses
   UNCHANGED, tag UNVERIFIED; real loss still counts; win still resets.
5. B5 DONE (brain repo): two fresh 24/7 witnesses must agree or /candles
   refuses 503, utc_normalized never false-claimed
   (executor_ic_markets/tests/test_clock_offset.py, 4 tests).
   B2 DONE (brain repo): shared fcntl lock writer+backfill, importable
   run_backfill, race regression test (concurrent append survives);
   hourly cron in the deploy paste.
6. PROCESS: merging the deploy branch to main in both repos at the end of
   this round, per the order — no future audit diffs a dead branch.

## WINDOWS DEPLOY — COMPLETED 2026-09-02 (the "git green != live" gap CLOSED)

Deployed by Shyam via deploy_windows.py from the fresh C:\brother_sniper_v7
clone (the VPS now has a real git path for v7 work; V18's old remote
brother-executor-v18.git is DEAD — repository not found — and its four
locally-modified files were snapshot-committed as 1baa72a BEFORE anything
was touched, so the box's unique work is protected and rollbackable).

  A1  C:\Users\Administrator\sniper_executor.py  PATCHED (backup .bak.20260901191923)
  B5  C:\brother_v18\executor_ic_markets\src\main.py PATCHED + clock_witness.py written
  Services SniperExecutorV7 and SniperExecutorV18 restarted clean.

Acceptance evidence arrives on its own: next MT5 hiccup -> v7 log shows
"positions UNKNOWN (HTTP 503)" instead of fake $0 closes; /candles under
clock doubt refuses with a witness message instead of assuming offset 0.
Friday round verifies both in live logs.

STILL OPEN on V18: the box repo's remote is dead and its snapshot lives
only on the box. Decide later (Shyam): create a real GitHub repo for the
v18 executor and push 1baa72a, or fold it into brother-brain-v2 — until
then that snapshot has no off-box copy.

## ROUND 3 STATUS (2026-09-02, bot boss session — this window owns the bot side)

Branch note: work lands on claude/session-44nji4 first; Shyam fast-forwards
claude/evidence-integrity-audit-35rlfa and main from it (commands in chat).
The 2026-09-01 audit file (docs/AUDIT_2026-09-01_BOT_SIDE.md) and its
"STEP 7 P1" list were never pushed to any branch — that list must be
re-issued before it can be worked. The 2026-07-31 audit's P1-1..P1-5 are
all present on this branch (verified file:line, brain OPEN_ITEMS ROUND 3).

1. A2 — SHIPPED DARK: /webhook fills a MISSING payload secret from the
   X-Webhook-Secret header (patch_webhook_header_secret.py, applied to the
   repo bot.py). Header never overrides a body secret; handle_signal stays
   the single check; auto-injection untouched until the log proves the
   mirror carries the header. Tests: tests/test_round3_a2_incident.py::
   test_a2_* (3). Box steps: docs/A2_NGINX_MIRROR_SECRET.md. Acceptance
   log line: "[A2] secret from header (system=BSv18)".
2. Incident posting — post_incident.py now sends BOTH incident_id and
   public_id (append-only; works on platform <5.04 and >=5.04). Test:
   test_incident_poster_sends_both_id_keys. POSTED from the box
   2026-09-02: "posted INC-0001 -> 200", "posted INC-0002 -> 200" (Shyam's
   terminal, quoted). The archive in brain OPEN_ITEMS is now on the board.
   CORRECTION (platform contract v5.04, quoted): an agent may report only
   INVESTIGATING / PATCH_PROPOSED; RESOLVED is refused with a reason while
   the fields still save. So "posted INC-0001 -> 200 (--status resolved)"
   SAVED the closing evidence but did NOT resolve it — the board holds
   INC-0001 at INVESTIGATING until Shyam presses APPROVE/RESOLVE. The
   poster now normalizes to the contract, refuses "resolved" at argparse,
   and prints the board's status + any refusal (a bare 200 hid it once).
   Tests: test_incident_status_matches_platform_contract,
   test_incident_reply_never_hides_a_refusal.
3. INC-0001 + INC-0003 are one process — see brain OPEN_ITEMS ROUND 3:
   the reporter (Sniper-System/agents/mt5_reporter, v1.6.0) is BOTH the
   US10Y 15m feeder and the ONLY writer of /api/v1/heartbeat/vps. The
   discriminating query and the Windows commands are recorded there.
4. Readiness push (platform ask #7) — post_readiness.py exists with its
   cron line in the docstring (45 21 * * 0). Verify on the box with
   `crontab -l | grep post_readiness`; add the line if absent. Not
   verifiable from here.
5. Not changed, deliberately: no trading logic, no risk number, no Pine,
   no bias push list (naming contract waits on the platform, 5.03).
6. BRANCH DIVERGENCE (found 2026-09-02): claude/brain-platform-mirror-fcacwl
   carries 41 commits the deploy branch lacks (bridge front-contract
   resolver fc5bd6f, /symbolspec + probe_symbol_specs.py, BRIDGE_KEY gate,
   v7_evidence_report, v7_counterfactual, ...) and the deploy branch has 34
   it lacks (A1/A2/C1/C2/B7 patches, round 2-3). probe_symbol_specs.py is
   therefore missing on the box ("No such file", Shyam 2026-09-02). Until
   the two are merged: single-file checkouts from the mirror branch, and
   the deploy branch's sniper_executor.py is NEVER copied over the box's.
   Merge is a deliberate round of its own (69 files; both bridge copies
   changed the same file). MEASURED 2026-09-02: the Windows bridge
   (C:\Users\Administrator\sniper_executor.py) matches _macro_front 2x —
   it is the mirror-branch bridge + the A1 patch. The deploy branch's copy
   is a landmine until converged.

## QUEUED ORGAN — NVDA (NVDA.NAS-24, "NVIDIA Corp 24/5 CFD"), asked by Shyam 2026-09-02

Decision recorded: a single-stock CFD is NOT gold, not an index, not crypto,
and gets its OWN engine — but the engine is written from NVDA's evidence,
not from assumptions about it. Phases, none skippable (V7 plan; Evidence
Law; "probe end to end before enabling", platform OPEN_ITEMS 08-17):
0. PROBE (no logic, no risk): symbol_info on the v7 terminal — digits,
   volume_min/step, contract size, trade_mode, sessions, spread now vs
   overnight. A name that resolves is not a name that fills.
   MEASURED 2026-09-02 (terminal 52834417, quoted):
     NVDA.NAS-24 | NVIDIA Corp 24/5 CFD | digits 2 | vol min/step/max
     0.1 0.1 1000.0 | contract 1.0 | trade_mode 4 (FULL) | bid/ask 0.0 0.0
     | spread pts 0 | currency USD
   Read: 1 lot = 1 share, 0.1-share granularity, cents pricing, fully
   tradable by mode. bid/ask 0.0 right after symbol_select = no tick
   received yet, NOT "no market" — re-probe after the symbol has sat in
   Market Watch for a minute, and once in the US session, once overnight,
   so the two spreads are measured, never assumed.
1. COLLECT (config only): BB_CANDLE_SYMBOLS += NVDA.NAS-24 on the reporter;
   platform alias NVDA.NAS-24 -> NVDA (append-only, platform session);
   TradingView alert on NASDAQ:NVDA with the FROZEN Pine (alert ceremony,
   no Pine edit). Signals land in the mirror as symbol NVDA, judged and
   journaled by both arms, NOT tradable: v7 gate keeps NVDA out of
   auto_live's hunt list; council marks it shadow.
2. ANALYZE (>=100 shadow signals or 4 weeks, whichever later): session
   cut (regular 13:30-20:00 UTC vs 24/5 extended), earnings-window cut,
   gap-open behaviour, spread cost per ATR, with-trend vs counter. What
   "different logic" means is the OUTPUT of this step.
3. ENGINE nvda-v1 as a NEW versioned engine, dark flag, shadow -> paper ->
   controlled size, each gate with n and the validate column deciding.
Known facts that shape the design (to be confirmed by phase 0/2, not
assumed): earnings gaps make overnight holds a different risk class;
overnight CFD spread is a multiple of the regular-session spread; the
platform's MAJOR_EARNINGS playbook already names Nvidia as a US100
driver, so NVDA and US100 signals will be correlated — position them as
ONE exposure, never two.
