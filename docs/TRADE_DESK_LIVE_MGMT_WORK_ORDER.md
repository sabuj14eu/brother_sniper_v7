# TRADE DESK — NY column + live position management (2026-08-19)

Origin: the owner's 13-point spec, written after a real incident: long GOLD
from a bot signal, up strongly in the fast NY move, exited early purely from
uncertainty — no map of "where is the trade wrong, what is the next level".
The spec asks the Trade Desk to answer exactly that, live.

Bot-side verdict: **the idea is right, and it is right for a measurable
reason** — the missing information was never a prediction, it was an
invalidation level and a next target. Everything below preserves the split:
the desk MAPS, the human (and only later, v7 under validation) DECIDES.

Ownership: the Trade Desk page, the level engine, the chart and the state
machines are **platform-session work** (their app, their UI). The bot side's
part is feeds — most of which already flow — plus the corrections listed at
the bottom.

---

## What the spec asks, grouped

**A. NY / Special Conditions column (points 1–2).** Fifth horizon column,
active only during NY. States (WAIT / WATCH / BREAKOUT DEVELOPING /
CONFIRMED / FAILED / RETEST / CONTINUATION / REVERSAL / HIGH NEWS RISK /
NO TRADE), each with timestamp + source + expiry. Same freshness law as
everything else on the platform: an expired state must actually expire —
yesterday's breakout can never render as today's.

**B. Live position chart (point 3).** Candles with selectable timeframe,
horizontal lines for current price / entry / SL / TP1 / TP2(/TP3). Purpose:
make "where price is relative to the trade" visual instead of mental.

**C. Position Management engine (points 4–9, 11).** Deterministic, separate
from entry logic. Emits ACTION + WHY + INVALIDATION + NEXT LEVEL, a
position state machine (ENTRY → PROFIT → BE → TP1 → TRAIL → …, or
ENTRY → WARNING → FAILURE → EXIT), and a "WHAT CHANGED?" diff on every
update. The Command Center header when a position is open.

**D. AI's role (point 10).** AI may WRITE THE SENTENCE, never THE NUMBER.
Every level (4470, 4448) comes from the deterministic level engine; AI
explains, on a schedule, under the same spend ledger + cap discipline as the
brain council. An AI call per candle is forbidden by construction.

**E. Safety (point 12).** First version: Desk → message → human decides.
NEVER Desk → MT5. Suggested SL moves are suggestions; a human moving a stop
is a human decision (Iron Rule 7). Any later automation runs
Desk → recommendation → v7 validation → v7 executor, dark first, under the
Evidence Law — and "AI → MT5" does not exist in any phase.

## Feed inventory (bot side — what already flows)

| Need | Status | Where |
|---|---|---|
| Live candles for the chart | EXISTS (check TFs) | Windows candle reporter service already posts candles; bridge/executor `/candles` serve M1+ closed bars, UTC-normalized. If the reporter doesn't ship 1m yet, that is a config widening, not new code |
| Open positions incl. entry/SL/TP | EXISTS | v7 heartbeat carries open positions; executors serve `/positions` |
| MANUAL positions (the GOLD trade was hand-managed) | EXISTS via reconciliation | Broker-truth reconciliation already labels broker positions with no v7 signal as ORPHAN — those rows ARE the manual trades. The management panel must treat ORPHAN as first-class, since the incident trade would have been one |
| Current price / spread | EXISTS | `/spread` + candle feed |
| News risk | EXISTS | hourly news push (impact, forecast/previous/actual) |
| Regime / trend / volatility / DXY / oil | EXISTS | bias push market engine, source + as_of on every item |
| Session/symbol/setup edge for the context strip | EXISTS | evidence.json (nightly) |
| NY opening range, London high/low, structure levels | MISSING | The platform's level engine derives these from the candle feed it already receives. Bot side does NOT duplicate this — one level engine, one truth |

## Hard lines (unchanged from the V7 Desk order, extended)

1. Deterministic engine computes every number; AI never invents a level.
2. Every state and every management message carries created_at, source,
   valid_until — and expiry is enforced, not decorative.
3. Entry logic and management logic are separate engines with separate
   vocabularies. They never share a verdict field.
4. No path from the Desk to MT5, in any phase of this spec. Iron Rule 1's
   council doctrine and Rule 7's human-risk doctrine both apply.
5. "HOLD" without WHY + INVALIDATION is a spec violation (point 5 is law).
6. No V18 changes. The Trade Desk reads feeds; it touches neither brain,
   council, Pine, nor executors.

## Honesty notes for the builder

- The management engine's rules ("move SL to 4455 at TP1") start life as
  UNVALIDATED heuristics. Render them as suggestions with their rule name,
  and journal every emitted message with the position id — that journal is
  how the rules themselves get judged later (n>=20, validate column), the
  same way every other organ in this system earns trust.
- The chart shows the map; it must not paint targets as promises. TP lines
  are levels, not forecasts — label them like it.

## Correction attached to this order

**BOT-P0-1 is CLOSED and the platform's copy of that fact is stale.** The
v7 close backfill ran 2026-08-19: 202 closed trades posted to
`/webhooks/brain/signal` (system BSv7, status "closed", `backfill:true`,
ids `v7-<signal_id>`), every post answered 2xx — the sender stops and holds
its cursor on any non-2xx, and the cursor stands at 202. If the V7 Desk
still renders "no closed trades", the gap is platform-side ingestion of
status="closed" posts (accepted-but-not-stored), not missing bot data.
