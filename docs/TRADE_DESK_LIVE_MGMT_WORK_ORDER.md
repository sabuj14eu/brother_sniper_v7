# TRADE DESK — NY column + live position management (rev 2, 2026-08-19)

Origin: the owner's 13-point spec, written after a real incident — long GOLD
from 4330, up strongly in the fast NY move, exited at 4400 purely from
uncertainty. The information that was missing was never a prediction. It was
two numbers and a rule: **where the trade becomes wrong, and what the next
level is.**

Bot-side verdict: build it. Everything below preserves the split — the desk
MAPS, the human DECIDES, and only much later (validated, dark-first) does v7
act on any of it.

Ownership: the page, the level engine, the chart and the state machines are
**platform-session work**. Bot side supplies feeds and the two corrections in
"Verified findings" — one of which was a live-chart blocker, now fixed.

Rev 2 changes: feed table re-verified against the actual code (three claims
were wrong), `?live=1` candle mode built, the management-message contract and
state machines specified concretely, and the GOLD incident written out as a
worked example.

---

## 1. Verified findings (checked in code 08-19, not assumed)

**F1 — the live chart was blocked, now unblocked.** The deployed v7 bridge
served **closed bars only** (`copy_rates_from_pos(..., start=1)`, the
BOT-P0-3 anti-repaint fix). Correct for analytics, fatal for a live chart:
the last candle would always be up to a full bar stale — worst exactly during
the fast NY moves this feature exists for. `/candles?live=1` now opts into the
forming bar, flagged `forming:true` on the row and `forming_last:true` /
`closed_only:false` on the payload. **Default is unchanged**, so every
analytics caller keeps closed bars and no repainting bar can leak into a
statistic by accident.
→ Chart calls `live=1`. Analytics never do.

**F2 — the heartbeat is far too slow to manage a position.** v7 pushes its
heartbeat every ~5 minutes (`_MON_HEARTBEAT_EVERY=5` at 60s/cycle). Position
entry/SL/TP/MAE/MFE therefore refresh at that cadence — useless for a panel
that must react to a breakout failure. **The management panel must NOT read
position state from the heartbeat.** Poll the executor `/positions` directly
(both executors serve it; that is broker truth) and use the heartbeat only for
v7's own slow-moving state (paused, streak, day/week PnL). If a faster v7
heartbeat is wanted later, that is a separate bot-side change with a deploy
ceremony.

**F3 — merge hazard, flagged for the endgame.** `sniper_executor.py` differs
by ~480 lines between this branch and the trade-desk branch. This branch's
copy is the one DEPLOYED on Windows (closed bars, `/spread`, `/symbolspec`,
the SYMBOL_MAP fix that stopped v7's XRP/LTC orders dying at the broker). A
careless merge that takes the other side reverts all of it. At convergence:
take this file from `claude/brain-platform-mirror-fcacwl`, then re-apply
anything the trade-desk session added on top.

## 2. Feed inventory — re-verified

| Need | Status | Source of truth |
|---|---|---|
| Live candles for the chart | **EXISTS (F1)** | bridge `/candles?symbol=&tf=&n=&live=1`; tf 1/5/15/30/60/240/1440, n≤5000, times UTC-normalized |
| Closed candles for the level engine | EXISTS | same route, default (`closed_only:true`) |
| Open positions: entry/SL/TP/volume/ticket | EXISTS — **poll, don't wait (F2)** | executor `/positions` (broker truth) |
| MANUAL positions | EXISTS as ORPHAN | reconciliation labels broker positions with no v7 signal. **The incident trade was one — the panel must treat ORPHAN as first-class, not an error row** |
| Current price / spread | EXISTS | `/spread`, and bid/ask on every `/candles` reply |
| v7 slow state (paused, streak, day/week PnL) | EXISTS | `v7_heartbeat` (~5 min is fine for this) |
| News risk | EXISTS | hourly news push: impact, forecast/previous/actual |
| Regime / trend / volatility / DXY / oil | EXISTS | bias push market engine; `source` + `as_of` on every item |
| Session / symbol / setup edge | EXISTS | `evidence.json` nightly (incl. the new `setup_edge`) |
| NY opening range, London H/L, structure levels | **MISSING — platform builds** | derive from the candle feed. One level engine, one truth: the bot side must NOT compute a second set |

## 3. The two engines (spec point 9 — keep them apart)

They answer different questions and must never share a verdict field.

```
ENTRY ENGINE            -> WAIT | BUY | SELL | REJECT        (does v7 own this? yes)
POSITION MGMT ENGINE    -> HOLD | PROTECT | MOVE_SL | TP1 | TRAIL | EXIT_WARNING | EXIT
```

**Position state machine** (one per open position):
```
ENTRY -> IN_PROFIT -> BREAKEVEN -> TP1 -> TRAIL -> TP2 -> CLOSED
   \-> WARNING -> BREAKOUT_FAILURE -> EXIT
```
Transitions are computed from price vs levels, never from sentiment. Every
transition is journaled with the rule that fired it.

**NY column states** (spec point 2): WAIT · WATCH · BREAKOUT_DEVELOPING ·
BREAKOUT_CONFIRMED · FAILED_BREAKOUT · RETEST · CONTINUATION · REVERSAL ·
HIGH_NEWS_RISK · NO_TRADE.

## 4. Message contract (so both sides agree before anyone builds)

Every management message, and every NY state, carries the same envelope:

```json
{
  "state": "BREAKOUT_CONFIRMED",
  "action": "HOLD",
  "why": ["15m structure intact", "price above breakout level 4448"],
  "invalidation": 4448,
  "next_level": 4470,
  "levels": {"entry": 4330, "sl": 4448, "tp1": 4470, "tp2": 4490},
  "position": {"ticket": 123456, "symbol": "GOLD", "side": "BUY",
               "origin": "V7" },
  "changed": {"from": "BREAKOUT_DEVELOPING", "price_delta": 18,
              "reason": "NY resistance broken, higher high confirmed"},
  "created_at": "2026-08-19T13:42:07Z",
  "valid_until": "2026-08-19T13:47:07Z",
  "source": "level_engine",
  "rule": "ny_breakout_v1",
  "evidence": "UNVALIDATED"
}
```

Non-negotiable fields: **`action` never ships without `why` + `invalidation`**
(spec point 5 is law), `origin` distinguishes V7 / ORPHAN(manual) / V18,
`valid_until` is enforced — an expired message renders as EXPIRED, never as
current, so yesterday's NY breakout cannot sit on today's screen. `evidence`
starts UNVALIDATED for every rule and only moves once its journal earns it.

## 5. The GOLD incident, as the panel would have shown it

The test of the whole design. Same trade, what the desk says at each moment:

| Moment | State | ACTION | WHY | Invalidation | Next |
|---|---|---|---|---|---|
| 4330 fill | ENTRY | HOLD | position opened, structure bullish | 4448 | 4470 |
| 4400 (the exit that happened) | IN_PROFIT | **HOLD** | above breakout level; nothing invalidated | **4448** | 4470 |
| 4464 | BREAKOUT_CONFIRMED | HOLD / PROTECT | higher high confirmed, SL now above entry | 4448 | 4470 |
| 4470 | TP1 | PROTECT PROFIT | first target reached | 4455 (suggested) | 4490 |
| 4451 after a failure | BREAKOUT_FAILURE | REDUCE / EXIT | breakout lost, structure broken | 4448 | — |

At 4400 the panel says **HOLD, and the reason is a number you can check
yourself**: price is above 4448. That is the whole feature. It never promises
4470 arrives — it says the bullish case is intact *until 4448 breaks*.

## 6. AI's role (spec point 10) — hard boundary

AI may write the sentence. AI may never produce a number. 4470 comes from the
level engine; the AI is handed the levels and writes the paragraph around
them. Calls are scheduled (session start, material change), never per candle,
under the same spend ledger and weekly cap as the brain council — a
per-candle LLM call is the exact cost failure that ledger exists to prevent.

## 7. Safety (spec point 12) — no exceptions

```
Phase 1 (now):    Desk -> message -> HUMAN decides -> human's hand on MT5
Phase 2 (later):  Desk -> recommendation -> v7 validation -> v7 executor -> MT5
Never, in any phase:   AI -> MT5      Desk -> MT5
```
Suggested SL moves are suggestions. A stop moving because software decided it
is a risk change, and risk changes are explicit human decisions (Iron Rule 7).
Phase 2 requires the management rules to have earned it: journaled from day
one, judged on n>=20 with a validate split, one organ at a time.

## 8. Honesty rules for the builder

- TP lines on the chart are **levels, not forecasts**. Label them so.
- A management rule ships as UNVALIDATED and says so on screen until its own
  journal proves it. "The desk told me to hold" must be auditable later.
- Journal every emitted message with the position id — that journal is the
  only way these rules ever graduate to Phase 2.
- No V18 changes. This project reads feeds; it touches neither brain,
  council, Pine, nor the executors' order paths.

## 9. Correction still outstanding for the platform

**BOT-P0-1 is CLOSED bot-side.** The v7 close backfill ran 08-19: 202 closed
trades posted to `/webhooks/brain/signal` (system BSv7, status `closed`,
`backfill:true`, ids `v7-<signal_id>`), every post answered 2xx — the sender
halts and holds its cursor on any non-2xx, and the cursor stands at 202. The
brain journal's 147 fillable outcome rows are filled. If the V7 Desk still
renders "no closed trades", the gap is platform-side ingestion of
`status="closed"` posts (accepted but not stored), not missing bot data.
Re-sending is one deleted cursor file away once their handler stores them.
