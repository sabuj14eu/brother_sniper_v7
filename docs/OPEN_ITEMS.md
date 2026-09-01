
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
