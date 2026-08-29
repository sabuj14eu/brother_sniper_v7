# PINE UPDATE NOTE — 2026-08-31 (Shyam is editing Pine tonight)

## THE FINDING: the calculation error IS very likely the dead-alert cause

SILVER went silent 3 days, US100 5 days (Market Radar, this week). Shyam
now reports SILVER / US100 / GOLD show a CALCULATION ERROR on the chart.
A Pine script that throws a runtime error STOPS EXECUTING on that symbol
— and a script that is not executing never reaches alert(). Same three
symbols, same window. This explains the silence without any TradingView
alert-log check, and it means the bias push was never broken on the bot
side: nothing was ever sent.

Fix the error first. Every other Pine change is secondary.

## WHAT V7 ALREADY RECEIVES (do not touch — Rule 2 is append-only)

system, signal, direction, signal_id, symbol, tf, entry, sl, tp, tp1,
tp2, rr, grade, type, time, atr, trend/htf_trend, entry_dist_atr.
v7 reads: time (signal age), trend, atr, entry_dist_atr, type.
NEVER rename these, never remove one, and never change the MEANING of an
existing field (a silent semantic change is worse than a rename — it
corrupts history that is already measured).

## THE ONLY TWO FIELDS WORTH ADDING (both cheap, both append-only)

1. pine_version  — e.g. "v18.13". Alerts freeze the script version at
   creation (Rule 3), so after a save we currently CANNOT prove which
   version produced a given signal. One string ends that blindness.
2. structure     — SHIPPED in v18.13. v7 now has a pine_structure column
   and captures it on both the open and reject paths.
   auto-v1 emits the same three words. Having both lets the agreement
   cut (does Pine do better when the bot agrees?) be measured directly
   instead of inferred. This week's agreement test was CANNOT SEPARATE
   at n=7/14; this field is what makes it separable.

Nothing else is requested. More fields = more Pine surface = more
calculation errors. The bot's own engine covers the rest.

## AFTER ANY SAVE — THE CEREMONY IS NOT OPTIONAL (Rule 3)

Delete and recreate ALL TradingView alerts ("Any alert() function call").
The filename never changes. An un-recreated alert keeps running the OLD
broken version — which is exactly how a symbol goes quiet for days.

## CORRECTION ACCEPTED (2026-08-31, from the Pine session)

The version key is `pine_ver`, present since v18.8 — NOT a missing
`pine_version`. My ask came from grepping v7's reader, not the payload;
v7 line ~1034 has been storing `payload.get("pine_ver")` into the
telemetry column `pine_version` all along. Refusing a second version key
was right: two version keys eventually disagree, and then neither can be
trusted. Analytics group by `pine_ver`; only pre-v18.8 signals are
genuinely UNSTAMPED.

Root cause credit also to the Pine session: three
`request.security_lower_tf` calls (v18.12 F3 DXY squelch) blowing the
per-study memory limit on the heaviest 24h symbols — which is why SILVER
and US100 died and why the panels vanished mid-position. One event, three
symptoms.

## BOT-SIDE WORK THIS CAUSED (both shipped)

1. `pine_structure` telemetry column (append-only) — WITHOUT IT v18.13's
   new `structure` field would arrive and be discarded, leaving the
   agreement cut unmeasurable forever. Captured verbatim on the open path
   (patch_pine_structure.py) and the reject path (telemetry.py).
2. Rejected signals were UNSTAMPED: capture_reject never recorded
   `pine_version`. After the ceremony, half of any version comparison
   would have been blind. Now stamped.

## THE PANEL LAW (from Friday's fear: exit or hold?)

A blank panel means the CHART DISPLAY died, not the trade. Position truth
lives in the journal and the broker tickets — never on the panel. Same
law as Iron Rule 6: health endpoints lie, tickets tell the truth. Read
the journal, then decide. Never close a live position because a drawing
disappeared.
