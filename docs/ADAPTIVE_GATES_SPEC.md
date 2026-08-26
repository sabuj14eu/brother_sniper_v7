# ADAPTIVE GATES — gates protect, they do not blind (Shyam, 2026-08-24)

The principle, verbatim: teach the bot "GOLD loses under these
conditions — protect capital there; when a different, historically
validated condition appears, recognize the difference and act."
Selectively brave: not blindly brave, not permanently scared.

## The two gate families (absolute distinction)

HARD SAFETY GATES — learning can NEVER override:
  broker/execution unavailable · stale or corrupt data · impossible or
  missing price · spread beyond absolute limit · duplicate/corrupt
  candle stream · risk/position limits · emergency state · invalid SL ·
  R:R floor · dedupe. These exist in v7 today and stay absolute.

ADAPTIVE GATES — evidence-driven, conditional, four states:
  🟢 ALLOW    measured positive cell at the condition
  🟡 CAUTION  weaker evidence -> REDUCED RISK, stricter confirmation
              (mechanism already built: ASSET_GATE_SIZE multiplier and
              the cluster 0.25x/0.5x/1.0x learning scale)
  ⚪ WAIT     setup not ready (structure developing, post-news pending)
  🔴 BLOCK    hard gate, or strongly validated negative condition
UNKNOWN cells (resolved n < 20) are UNKNOWN — never proven, never
pretended, never traded as if measured.

## What already implements this (do not rebuild)

- Conditional EV per cluster + learning-phase sizing: cluster_engine
  (live in production sizing today).
- Rejected candidates as full observations: capture_reject + context +
  entry_dist_atr (live).
- Shadow-as-bridge: the freshness gate's shadow mode is THE pattern —
  every adaptive gate ships shadow-first.
- CAUTION lever: ASSET_GATE_SIZE (built, dormant, clamped <=1.0 so it
  can only ever reduce risk).
- Platform mirrors of the same idea: distance_confounders, funnel,
  setup_edge.

## The new organ: learning/conditional_profile.py (2026-08-24)

Read model over the unified feature store (telemetry + journal by
signal_id). context_of() keys every row by symbol/side/alignment/
session/grade-band/distance-bucket/news-band with honest UNKNOWNs;
profile_verdict() answers with HIERARCHICAL BACKOFF — most specific
cell first, dropping dimensions (news -> grade -> dist -> session ->
side -> aligned) until a cell reaches n>=20, reporting which level
answered; below the floor everywhere -> UNKNOWN, "do not pretend".
CLI report, read-only, safe on the box any time:
    python3 -m learning.conditional_profile GOLD

## Path to production (never skipped, per Shyam §12)

  OFFLINE REPORT (now) -> SHADOW wiring (adaptive verdict logged beside
  every decision, blocks nothing) -> EVIDENCE REVIEW (n floors, both
  populations, validate split) -> EXPLICIT HUMAN APPROVAL -> deploy via
  ceremony, CAUTION before ALLOW, one organ per week -> MEASURE.
  Never: yesterday-bad -> AI edits gate -> today-trades.

## News modes (recorded; built through the same path)

  🟢 NORMAL -> 🟡 PRE-EVENT (tighter conditions, no chasing) ->
  🟠 EVENT (a REGIME, not a dead zone — participate only where the
  measured event profile is positive) -> POST-NEWS (wait for vol
  stabilization + first structure + retest/rejection, then evaluate
  normally — potentially the best window).
  Learned per asset x event type (GOLD+CPI is not GOLD+FOMC), from
  event_reactions + news_minutes + outcomes. The current HIGH-news
  block stays until the measured profiles exist — then PRE/EVENT/POST
  become conditional, through review and approval, not by feeling.

## Build order (one organ per week, evidence names the order)

  Week now: COLLECTION — untouched. The CLI report may be run
    read-only; it changes nothing.
  Next: shadow wiring of profile_verdict at the decision site
    (anchor-safe patch, logs [ADAPTIVE SHADOW], telemetry-tagged).
  Then: first CAUTION mapping via ASSET_GATE_SIZE where a NEGATIVE
    CELL is MEASURED and both populations agree; news PRE/POST modes;
    event profiles.

## Developer verdict (Shyam, 2026-08-24): 🟢 APPROVED
Direction right. Gates do NOT loosen yet. This week builds the cells.
Week-end review dimensions: GOLD/SILVER/US100/BTC/ETH x session x side x
alignment x grade x entry distance x news regime x event type.
THE HEADLINE NUMBER of the review: how many currently blocked setups
would have become profitable if allowed — the measure of whether gates
protect or suffocate. Sources: capture_reject telemetry (v7) +
v7_counterfactual nightly (bot box) + platform mirrored rejects.
The question is no longer "should GOLD be enabled" but "WHEN should
GOLD be enabled."

## Adaptive Decision card (UI spec, approved format — platform-side)
Rendered on /chart + radar, DISPLAY ONLY, from mirrored data the
platform already stores (raw_payload carries grade/session/
entry_dist_atr; status carries approved/rejected; alignment from bias):
  BOT LIVE | asset + setup state | OVERALL ASSET PROFILE (colour + EV)
  | CURRENT CONDITIONAL PROFILE (POSITIVE/NEGATIVE CELL or UNKNOWN,
  n=, the condition named: "NY · trend aligned · A-grade · near entry")
  | CONFIDENCE (MEASURED/DEVELOPING/LUCK-ZONE) | CONFIRMATION line |
  ADAPTIVE DECISION (ALLOW/CAUTION/WAIT/BLOCK — shadow-labelled until
  approved for enforcement). News regime card same shape: NORMAL/PRE/
  EVENT/POST + per asset x event historical profile + "waiting for
  post-news confirmation" instead of a bare block.
UNKNOWN cells render as UNKNOWN with their n — never coloured as a
verdict. The card EXPLAINS; it does not gate until the ceremony says so.

## Platform delivery confirmed (2026-08-26, v4.65–v4.68)

- Outlook authorship LOUD: 🤖 AUTO badge vs 👤 human, supersession
  history visible. The auto-weekly cron can never impersonate Shyam.
- Adaptive Decision card COMPLETE platform-side: named condition,
  dropped dimensions, backoff level always stated (exact-cell answers
  no longer render silence), SHADOW label until enforcement approved.
- ⚖️ GOLD rejected-vs-traded LIVE on /v7 per the DECISION LOG spec:
  summary strip, four cuts, both populations per cell, v7's rejection
  reasons verbatim, "DECIDES NOTHING yet" under n>=20 closed. Their
  mirror-purity guard test correctly forced the computation into its
  own module (decision_log.py) — the mirror stays a mirror.
- PLAT-OUTLOOK-1 queued platform-side: verify scorecard grades KNOWN
  legs and leaves UNKNOWN legs UNKNOWN when the first envelopes lapse.

## Small bot-side follow-up queued for WEEK 2 (not this week)

- mirror_v7_close does not send mae/mfe though tracked carries them —
  the platform renders MAE/MFE as UNKNOWN honestly. Append-only fix
  (two keys in the close payload), worth doing at the week-2 review
  alongside whatever else that review decides. Not during collection.
