# CLAUDE.md — Brother Sniper System Constitution
Read this before touching anything. These rules were paid for in real losses.

## WHAT THIS IS
Algorithmic trading system, ALL DEMO accounts. One TradingView Pine script
(BrotherSniperULTIMATE, Pine v6) fires alerts to brain.signalmesh.dev/webhook/v18;
nginx mirrors a copy to the v7 bot.
- v18 brain (this Contabo box, /home/shyam/brain-v2/brain): 6-agent AI council
  judges every signal -> Ed25519-signed dispatch -> Windows executor :8080
  (NSSM service SniperExecutorV18, MT5 52901228).
- v7 bot (/home/shyam/brother_sniper_v7): mechanical arm, own filters ->
  bridge :5001 (NSSM SniperExecutorV7, MT5 52834417).
- Dashboard: status.signalmesh.dev (/home/shyam/brain-v2/dashboard/backend).
- Analytics live in brain dir: truth_layer, scorecard, pullback_backtest,
  council_calibration, weekly_source_report, session_caller (paper, 3x daily).

## IRON RULES — NEVER VIOLATE
1. NOTHING bypasses the council. No signal path may go direct to an executor.
   (The last bypass, an MT5 scanner, lost 60R. It is retired.)
2. Payload contract is APPEND-ONLY. Never rename/remove fields Pine sends or
   bots read (system, signal, direction, signal_id, symbol, tf, entry, sl, tp,
   tp1, tp2, rr, grade). The brain listener passes unknown keys through.
3. Every Pine save requires the ALERT CEREMONY: delete + recreate ALL
   TradingView alerts ("Any alert() function call"). Alerts freeze the script
   version at creation. The filename never changes.
4. Deploy ceremony for any service code: backup -> compile -> restart ->
   verify in logs/journal. Anchor-safe edits only; abort on ambiguous anchors.
5. EVIDENCE LAW: no live logic changes without data. New rules must pass the
   backtest harness (train/validate split; the VALIDATE column decides) or
   accumulate journal evidence (n>=20 minimum; n<20 is luck). Judge nothing
   before ~100 trades. One organ changed per week.
6. Health endpoints lie; only TICKETS tell the truth. The dashboard bot-guards
   exist because an executor served 200s for 6 days while placing nothing.
7. Never widen risk silently. Sizing/risk changes are explicit human decisions,
   logged with their rationale.
8. Secrets (.env, tokens, passwords, account registry) are never committed,
   never printed in logs or chat.

## CURRENT EVIDENCE (change only with new data)
- PULLBACK trigger validated: n=640 backtest, out-of-sample PF 1.30-1.45,
  stop 1.5xATR (0.8 FAILED validation). Asia is its BEST session (73.6% WR).
- Fixed 2R take-profits FAILED validation on structural levels. The
  high-win-rate small-R ladder (session TP 1.0/1.8 ATR) is the validated design.
- SMART_SCALP grades/scores are ANTI-predictive (score<=6 beat 9+; grade B
  beat A+). Do not hand-reweight; the engine itself is on trial by journal.
- Counter-trend entries are the #1 documented loss driver (SELL bleed -406).
- GOLD is the weakest asset (macro-driven; technicals bleed there); SILVER and
  US100 are the strongest.
- FIB-retracement levels: promising challenger (validate PF 1.82, n=62) —
  watch-list, builds only at PF~1.5+ with n>=100 validate.

## QUEUED WORK (specs in repo /docs or /mnt outputs)
- CMS Phase 1 per CMS_MASTERPLAN.md (login, account registry, per-account
  health + ON/OFF). CMS manages accounts/routing, NEVER signals.
- usd_lag_backtest.py (DXY_U6 vs gold lag rule) — harness first, as always.
- v18.9 dark flags await harness validation: SB_PENDING, BIAS_INFO,
  ASSET_PULSE, BREAKOUT.

## HOW TO WORK HERE
Findings first, then code. Small verified diffs over rewrites. When a claim
matters, grep the journal (logs/decisions.jsonl) — this system's history is
measured, not remembered. If something looks broken, check what the TICKETS
say before believing any green light.
