# Weekly Review — Friday 2026-08-07 (bot update day)

Inputs: `nightly_edge.py --unified` (n=165), `scorecard.py` (n=173),
`tp_geometry_study.py` rerun (~75d bridge data). All lifetime data below is
from the PRE-FIX era (18.8 alerts, dead CHoCH veto, direction-blind A+,
GOLD unbenched) — the clean-fleet baseline started 08-06/08-07.

## DECISIONS (explicit, Rule 7)

1. **GOLD: bench threshold met, USER OVERRODE the bench (08-07).**
   Evidence on record: PF 0.65 at n=33 (gate's own bench bar is PF<0.7 at
   n>=30), net −365, EV_lcb −0.50R, GOLD·SELL alone −292. The user's
   explicit decision (Rule 7): gold keeps trading — no asset is disabled.
   Offered compromise: `ASSET_GATE_SIZE=GOLD:0.5` (half size, every signal
   still taken); final .env state is the user's choice. Note for next
   review: gold's clean-era (18.12-fleet) record starts fresh — re-measure
   there before re-raising the bench.

2. **ETH: NOT benched yet** — n=17 < the n≥20 bar (WR 11.8%, PF 0.06 is
   dreadful but 17 trades is luck territory by law). Crosses n=20 soon;
   bench next review if PF still < 0.7. BITCOIN·SELL (n=29, sWR 25.7%)
   flagged — no side×symbol dial exists; the rebuilt counter-trend veto is
   the targeted fix, live since 08-06.

3. **SELL bleed reconfirmed** (SELL PF 0.75 n=109 vs BUY 1.20 n=56) — same
   #1 loss driver the constitution records. NO new blunt rule: the fix
   (18.10 CHoCH rebuild — the v1 veto fired ZERO times in the old fleet)
   deployed with the 18.12 ceremony. Judge it on the new era's trades.

4. **Stop-width finding — the user's hypothesis VALIDATED**: SL <0.3% of
   price → WR 39.2%, PF 0.80 (n=74); SL >1% → WR 69.6%, PF 1.54 (n=56).
   Tight stops bleed, survivable stops win. The 0.7-ATR Pine floor is live
   fleet-wide since the ceremony; MAE capture (61/173 so far) accumulates
   toward the A/A+ swing-lane study (wider SL + 12-24h window).

5. **Session TP stays 1.4 ATR (Ldn/NY)** — all-picks validate PASS again
   and stable (+0.09R, PF 1.23, n=213; last week +0.11/1.27). The best-of
   table flip-flopped week-over-week (0.8/2.6/3.0 pass now, 1.4 passed
   last week) on n≈39 slices — that is picker noise, already a known open
   question; weekly TP chasing on 39-sample slices is curve-fitting.
   NOTED: 2.6/3.0a passing in Ldn/NY best-of supports the swing-target
   hypothesis — evidence trickle for the swing lane, not an action.

6. **Healthy organs confirmed**: SILVER n=40 PF 1.44 (best asset, as the
   constitution says), USDJPY PF 1.17 n=27, USTEC/US30 strong but PROV.
   v7 Asia session bleeds (PF 0.46 n=37) for SMART_SCALP — contrast with
   PULLBACK/session-caller Asia strength; engine-specific, watch under the
   new fleet before any session dial.

7. **Scoring still anti-predictive** (Section 3 verdict) — unchanged stance:
   no hand-reweighting; the 18.12 engine is on trial by journal.

## Baseline reset
The 18.12 ceremony + PULLBACK unblock + gold bench = a new system. Judge it
on its own ~100 trades. Next review: bench-or-not ETH (n≥20 by then),
first clean-era scorecard slice, swing-lane MAE study if A/A+ n permits.
