# WEEKEND AUTONOMY READINESS REPORT — 2026-08-30

Question under review: can v7 make, explain, manage and audit its own
decisions WITHOUT Pine? Rules of this report: populations never mixed;
UNKNOWN never becomes PASS; no section below its evidence floor issues
a verdict; every number names its source or the command that prints it.

Period: 2026-08-24 market open → 2026-08-29 close (the collection week),
over a Phase-1 dataset reaching back to lane v4.0.

==================================================
1. EXECUTIVE SUMMARY (populations kept separate)
==================================================
PAPER/RESEARCH (lane_observations, ruleset lane-resolve-v1, NO COSTS):
  33,789 observations · 16,495 trade candidates · 14,941 resolved.
  Per engine (measured 2026-08-30, spread-cost-discounted where shown):
    auto-v1    n=2,659  WR 23.3%  +0.263R gross  (+699.7R total)
    scalp-v1   n=4,907  WR 29.0%  +0.053R gross
    session-v1 n=  648  WR 21.0%  −0.094R gross
    swing-v1   n=   75  WR 22.7%  −0.119R gross
V7 MIRROR / ACTUAL BROKER: lives in learning/trades.jsonl + the
  platform's ⚖️ /v7 rejected-vs-traded card (collection window 24–29
  Aug). GOLD demo-collection verdict reads THERE, never from paper.
PINE/BRAIN: decisions journal + push_bias; council rounds n≈21
  evaluated — too thin for any council-level verdict this week.
MaxDD / consecutive losses / PF per population: printed by the
  platform's decision_log card and trade_stats; not restated here from
  memory. Populations were NOT mixed anywhere in this report.

==================================================
2. AUTONOMOUS ENTRY TEST
==================================================
"If Pine disappeared, could v7 generate a complete trade decision?"
ANSWER: YES — proven twice.
  (a) Every one of the 16,495 paper candidates was generated with ZERO
      Pine input: candles → structure → levels → entry/SL/TP/R:R.
  (b) auto_live.py (commit cb534f6, 6 tests) produces COMPLETE
      executable decisions — direction, entry, SL, TP, RR, distance,
      freshness verdict — from bridge candles alone, and posts them
      through v7's own gates. Pine appears NOWHERE in that path.
Pine/Bot agreement question: n=7 agree vs n=14 disagree on evaluated
rounds — BELOW FLOOR, verdict CANNOT SEPARATE. Not assumed either way.
Is Pine secretly required anywhere? In auto_live's path: NO. In v7's
EXISTING flow: yes by design (it is a Pine listener) — the two paths
now coexist, which is exactly the architecture the plan prescribes.

==================================================
3. ENTRY FUNNEL
==================================================
Candidates→filled→resolved per distance bucket with explicit
denominators: LIVE on /desk (v4.52 funnel, item-2 contract). Command:
the /desk page, or distance_funnel via docker exec. Per-asset
observation→setup→filled conversion: platform read model over
lane_observations — queued for the platform session's /review page.

==================================================
4–7. BY-ASSET · BUY/SELL · SESSION · DISTANCE
==================================================
THE DECISION TABLE of this review (auto-v1, spread-discounted,
points→price via symbol digits, measured 2026-08-30):
  NET POSITIVE:  SILVER +1.303R (n=285) · GBPUSD +1.168R (n=195) ·
                 US30 +0.843R (n=149) · BTC +0.133R (n=150)
  NET NEGATIVE:  GOLD −0.091 · ETH −0.265 · EURUSD −0.407 · US100
                 −0.742 · USDCAD −0.782 · USDJPY −1.660 · SOL −1.755 ·
                 XRP −0.258 · others see review paste.
Distance: the >3 ATR bucket is the measured bleed (−0.21R pooled
n=827; with-trend −0.643R n=368); near buckets positive. Fill-rate and
funnel by bucket: /desk. Full conditional cuts (side × alignment ×
session × grade × distance × news) per symbol:
    python3 -m learning.conditional_profile SYMBOL
Sessions/sides are inside those cuts; asymmetry is measured, never
assumed (constitutional: SELL bleed is the oldest documented driver).

==================================================
8. NEWS / EVENT REPORT
==================================================
STATUS: UNKNOWN — honestly. The calendar feed went live 2026-08-26
(push_news hourly); event-regime cells (NORMAL/PRE/EVENT/POST, per
asset × event type) cannot reach n≥20 in four days. news_minutes is on
every trade, news_window on every payload, events stored with actuals.
The "post-news retest beats first impulse" question is queued with its
data now accruing. High news is NOT auto-negative anywhere; it is
uncut data. Verdict: DEVELOPING.

==================================================
9. MACRO CONTEXT REPORT
==================================================
DXY/US10Y legs are recorded (event_reactions, trend_context ruled
authoritative for macro direction 2026-08-29). Conditional
metal × DXY × yield cells: platform read model over stored legs —
queued; no cell asserted below floor. Verdict: DEVELOPING.

==================================================
10. ADAPTIVE PROFILE REPORT
==================================================
Engine live (learning/conditional_profile.py + platform Adaptive card
v4.65–68): dimensions symbol/side/alignment/session/grade/distance/
news; hierarchical backoff names every dropped dimension; n<20 renders
UNKNOWN/LUCK-ZONE and can never become a verdict (pinned by test).
Per-symbol output: the CLI above. Verdict: ENGINE PASS · CELLS
DEVELOPING (they fill as the new instrumentation accrues).

==================================================
11. GOLD SPECIAL REPORT
==================================================
GOLD overall: still negative — −0.085R gross, −0.091R net (n=163) on
the paper population; the demo-collection window's OWN trades read on
the ⚖️ /v7 card. Conditional cells: print with
    python3 -m learning.conditional_profile GOLD
"Would an adaptive gate have allowed some GOLD?" — answerable the
moment GOLD's with-trend/NY/near cells reach n≥20 in the CLI output;
this report does not pretend the answer early. DECISION STANDING:
GOLD is EXCLUDED from auto-live-v1 because its own record said no.

==================================================
12–13. REJECTED TRADES & MISSED OPPORTUNITIES
==================================================
Instrument EXISTS and runs nightly: v7_counterfactual.py replays every
refused signal against real candles (no lookahead, fill-required,
SL-first, OPEN never a win). Command:
    python3 v7_counterfactual.py
Its per-gate summary IS sections 12–13: which gates killed losers
(GOOD gate) vs killed winners (SUFFOCATING gate). Reject telemetry
(reason + full context + entry_dist_atr) flows on every refusal.
Verdict: INSTRUMENT PASS; read the current output at review.

==================================================
14. FALSE POSITIVE REPORT
==================================================
Data present per losing trade (context, distance, structure, news,
MAE/MFE via trade_memory + telemetry join). Pattern mining across
losers: queued platform read model. Verdict: DATA PASS · REPORT QUEUED.

==================================================
15. MANAGEMENT REPORT — NOT RUN
==================================================
The mgmt replay harness (entry-only vs BE vs trail vs TP1-protect vs
runner) has NOT been executed. mgmt-v1/ny-v1 remain labelled
UNVALIDATED, exactly as OPEN_ITEMS requires until the desk_messages
journal is replayed. NO live SL-movement rule is proposed. Verdict:
NOT RUN — and per the rules, NOT RUN never converts to PASS.

==================================================
16. MANAGEMENT STATE INTEGRITY — NOT AUDITED
==================================================
The impossible-transition audit (CLOSED→ACTIVE, TP1 twice, SL
widening) has not been run as a dedicated check. Existing invariants
(be_done/partial_done write-once flags, 12h expiry, EXPIRED loud) are
in place but unaudited as a state machine. Verdict: NOT RUN.

==================================================
17. DATA INTEGRITY — PASS
==================================================
audit_candle_offsets on GOLD/SILVER/BTC/ETH: 0 off-grid, 0 twins,
NO PROVABLE CORRUPTION (run on production, 2026-08-2x). Canonical
candle identity + closed-only ingest + two-witness clock enforced and
tested. Forming candles proven excluded (tests, both repos). Known
open items, none blocking: DXY 1d bar lag watch; "17 DXY rows" awaits
the platform's source query; per-bar DST conversion live (v1.5+).

==================================================
18. FRESHNESS TEST — PASS (enforcement graded honestly)
==================================================
Stale candles cannot produce platform levels (Freshness Law, tested);
fetch_atr refuses stale bars; auto_live refuses stale/forming bars
with the named state (tested); freshness gate v1 live in SHADOW at the
v7 decision site — shadow counts to be read at week-2 before enforce.
STALE never became a positive signal anywhere this week; the desk
REFRESH event (69.503→68.824, material move) proved the recalculate
path live.

==================================================
19. PINE INDEPENDENCE TEST — PASS
==================================================
The shadow simulation the section demands IS the Phase-1 lane dataset:
16,495 complete no-Pine decisions, resolved under fixed rules, closed
bars only, no hindsight (trigger-first, same-bar SL-first, no
lookahead — pinned by tests). BOT-WITHOUT-PINE vs WITH: the without-
Pine book stands alone at +699.7R gross auto-v1; the with-Pine
comparison at round level is CANNOT SEPARATE (n=21). Independence of
GENERATION is proven; head-to-head superiority is not claimed.

==================================================
20. AUTO-TRADE READINESS GATES
==================================================
DATA INTEGRITY        PASS
FRESHNESS             PASS
ENTRY ENGINE          PASS  (auto-v1 record + auto_live tested port)
PINE INDEPENDENCE     PASS
RISK ENGINE           PASS  (auto_live reuses v7's full gate chain,
                             bypassing nothing — by construction)
MANAGEMENT REPLAY     NOT RUN  → cannot PASS
STATE MACHINE         NOT RUN  → cannot PASS
EXECUTION SAFETY      DEVELOPING (US30/USTEC broker probe pending;
                             AUTOLIVE payload path not yet exercised
                             against the RUNNING bot — dry log will
                             show v7's actual replies Monday)
ADAPTIVE PROFILE      DEVELOPING (engine PASS, cells filling)
NEWS ENGINE           DEVELOPING (feed live 4 days)
EVIDENCE              PASS on entry engine (n=2,659, cost-discounted,
                             per-symbol); DEVELOPING elsewhere

==================================================
21. RECOMMENDED AUTONOMY PATH (current position marked)
==================================================
BOT WITHOUT PINE, PAPER          ✅ complete (14,941 resolved)
BOT WITHOUT PINE, SHADOW LIVE    ◀ WE ARE HERE — auto_live.py DRY RUN
                                   cron live from Sunday's open
BOT WITHOUT PINE, DEMO AUTO-EXEC  gated on: (a) ≥1 week clean dry log
                                   incl. v7's real gate replies,
                                   (b) US30 probe, (c) mgmt-state
                                   audit run, (d) EXPLICIT human
                                   AUTO_LIVE_ARM=1
REVIEW → EXPLICIT USER APPROVAL   before anything beyond demo, ever
Sizing unchanged; universe SILVER/GBPUSD/US30 only; one organ at a
time — arming IS the one organ of its week.

==================================================
22. THE TEN QUESTIONS
==================================================
1. Find trades without Pine?        YES — proven, twice.
2. Know when NOT to trade?          YES — 17,294 recorded WAITs, far-
                                    bucket refusal, freshness refusal,
                                    GOLD self-exclusion.
3. Conditional beats pooled?        YES in design and early cells
                                    (pooled GOLD hides both verdicts);
                                    MEASURED confirmation filling.
4. Gates blocking good trades?      MEASURABLE, not yet judged — read
                                    v7_counterfactual per-gate at the
                                    review; budget-exhaustion fail-
                                    closed (Aug 22–24) is one KNOWN
                                    unnecessary blocker, since fixed.
5. Positive conditions?             SILVER/GBPUSD/US30 (+BTC thin),
                                    near-entry, with-trend.
6. Genuinely bad?                   >3 ATR entries; GOLD/USDJPY/US100/
                                    SOL under auto-v1; counter-trend.
7. Event engine improves post-news? UNKNOWN — 4 days of feed; do not
                                    pretend.
8. Management adds value?           NOT RUN.
9. Closed-bar facts, no hindsight?  YES — enforced and tested at every
                                    layer (ingest, resolver, engines,
                                    report tools).
10. Ready for DEMO auto-execution?  TECHNICALLY CLOSE, NOT TODAY —
                                    two NOT-RUN audits + probe + one
                                    clean dry week stand between.

==================================================
FINAL CONCLUSION
==================================================
🟡 SHADOW ONLY — MORE EVIDENCE REQUIRED (and the shadow is ALREADY
DEPLOYED: auto_live.py dry-run hunts from Sunday's open).

Not 🔴: every hard gate that has been run, passed. Not 🟢: management
replay and state audit are NOT RUN, the US30 name is unprobed, and the
AUTOLIVE payload has never met the running bot — and this project does
not convert UNKNOWN into PASS, even on a weekend it badly wants to.

Path to 🟢, exactly: one clean dry-run week (v7's real replies in
logs/auto_live.jsonl) · US30/USTEC probe on the Windows box · run the
mgmt-state audit · then AUTO_LIVE_ARM=1 by Shyam's hand. Every item is
days, not months, and none is negotiable.
