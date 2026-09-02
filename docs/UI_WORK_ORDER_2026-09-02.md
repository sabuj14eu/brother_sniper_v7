# UI / platform work order — 2026-09-02, from the bot side (Shyam approves)

Everything the platform session is asked to do after today's round. Each
item names the reason and the proof that closes it. Bot-side owes are
listed at the end so nobody waits on the wrong side.

## A. NVDA card (read model, no strategy)
1. Print the SIDE on breakout states: "BREAKOUT_CONFIRMED · UP (above
   218.550)" / "DOWN (below 216.050)". Never BUY/SELL — the card judges
   state, engines decide. Proof: the NY lane card shows the side.
2. Stamp every NVDA state with its liquidity tier: REGULAR 09:30-16:00 America/New_York (13:30-20:00 UTC in summer, 14:30-21:00 in winter — the platform computed it in local time, correcting this spec)
   · PRE/AFTER-MARKET · OVERNIGHT/WEEKEND. Same words in different tiers
   are different facts. Do NOT build Asia/London lanes for a single-stock
   CFD. Proof: tier visible on the card, stored on the lane row.
3. Show "earnings date UNKNOWN" on NVDA until the calendar feed carries a
   MAJOR_EARNINGS row (bot-side owe #1). Never imply clear skies.
4. Cross-asset order for NVDA: US100 first (one exposure until
   PLAT-EXPOSURE-1 is Shyam's decision), DXY second, yields via Pine's
   yield_dir only (US10Y price feed retired at the broker).
5. Overnight spread for NVDA is unmeasured: when the reporter's spread
   sampler has an after-hours reading, show it beside the regular one.

## B. Board / observability
6. INC-0001: Shyam's APPROVE/RESOLVE button (evidence attached: neither
   terminal lists a US 10Y contract). Candle freshness for US10Y must
   read "instrument ended 2026-08-27", never STALE (5.05 did this — keep).
7. git_production_match: expect GREEN measured (digest e4dcc04b…) on the
   reporter row now; if AMBER with c09a5bc2… persists past one heartbeat,
   tell the bot side.
8. Merge 7b227d2 (`.gitattributes agents/** text eol=lf`) with --no-ff.
9. Identity flapping: if a VPS row's ea_version alternates between two
   values, name it as a fault of its own ("two writers, one row").

## C. Naming contract (append-only)
10. US10Y is two inverse quantities under one name (Pine yield vs T-note
    price candles). Decide once: keep US10Y for the yield, store any
    future note-price series under its own name. Record the decision.
11. Dead rows USOIL/XRP/USA500: Shyam's call (merge/delete/keep-named).

## D. Still yours from earlier rounds
12. C3 normalizer for the mirror's new fields (pine_ver, payload_schema,
    fired_at, session, tf, score).
13. B4 dashboard work lives in brother-brain-v2/dashboard/backend — commit
    there, not in the platform repo.
14. INC-0003 is closed bot-side (one reporter, PID 5336). Close it on the
    board with the row quoted.

## Bot side OWES (do not wait on the UI for these)
1. MAJOR_EARNINGS rows in the calendar feed (new organ, harness first).
2. Branch convergence: mirror branch (resolver, probes, evidence reports)
   vs deploy branch (rounds 1-3); the box bridge = mirror + A1 patch.
3. A2 step 3 after Shyam's nginx line: remove the secret auto-injection,
   rotate WEBHOOK_SECRET.
4. DXY_U6 roll watch, mid-September (first "symbol not known" line).
5. NVDA phase 2 in ~4 weeks: three shadow populations, one key (NVDA).

## Platform reply 2026-09-02 (recorded; deploy pending Shyam)
Done: A1 (side UP/DOWN + level; BUY/SELL guarded by test; WAIT/WATCH carry
None), A2 (tiers in America/New_York — my fixed-UTC spec would have been
wrong four months a year; corrected above), A3, A4, A5 partial (spread
labelled with its tier; regular-vs-after-hours needs a spread HISTORY =
schema change, ships alone), C10 (US10Y = yield permanently). Earlier:
B8 merged 99c09d8 --no-ff; D12 shipped in v5.00.
Refused with reason, accepted: B9 — flapping cannot be measured from one
mutable row per user; needs an append-only identity journal (new table +
migration), ships alone with its own tests. Correct refusal: an inferred
fault is the thing this week was spent removing.
Shyam's buttons: RESOLVE on INC-0001 and INC-0003 (no agent may).
Still open: C11 dead rows (Shyam), D13 (brain repo, bot side).
