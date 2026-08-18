# V7 DESK — PHASE 1 REPOSITORY AUDIT & ARCHITECTURE PROPOSAL
Date: 2026-08-18 · Branch: `claude/trade-desk-architecture-review-hp9xnb` · Status: AUDIT ONLY — no code changed

This document is the Phase 1 deliverable required by the Trade Desk directive
(Developer Instruction #1, §44/§48): a map of the CURRENT architecture across all
four repos, the answers to the two open questions (altcoins for v7; the v7 data
feed for the platform's `/v7` page), and the smallest-safe-change plan for the
new Desk State layer. v18 is left exactly as it works today, per instruction.

---

## 1. WHAT EXISTS TODAY — CURRENT DATA FLOW

```
                      TradingView (BrotherSniperULTIMATE, Pine v6)
                                       │  one alert
                                       ▼
                     nginx @ brain.signalmesh.dev (TLS, IP allowlist)
                          │                            │ mirror
                          ▼                            ▼
        V18 BRAIN (FastAPI :8443)            V7 BOT (Flask/gunicorn :5000)
        brain/src/main.py                    bot.py handle_signal()
        gate chain: GradeGate →              27-step gate cascade (secret,
        SlotGate → MarginGate →              grade, price sanity, dedup,
        grade-tiered 6-agent council         slot, margin, EquityGuard,
        (Anthropic) or $0 pine_trust         news, EV, AI-filter, SL/RR)
                          │                            │
                          ▼                            ▼
        Ed25519-signed dispatch              plain-HTTP shared-secret POST
                          │                            │
                          ▼                            ▼
        Win executor :8080 (NSSM             Win bridge :5001 (NSSM
        SniperExecutorV18, MT5 52901228)     SniperExecutorV7, MT5 52834417)
                          │                            │
                          ▼                            ▼
        logs/decisions.jsonl (journal)       learning/trades.jsonl,
        + platform_mirror → app.signalmesh   telemetry.jsonl, state.json
                                             (LOCAL DISK ONLY — no push)

        DASHBOARD status.signalmesh.dev (:9090, stateless FastAPI)
        pulls files + probes /health endpoints; serves /api/v7/page

        session_caller (paper, 3×/day, $0 AI) → session_calls.json + Telegram
        push_bias.py (cron */30) → platform /webhooks/brain/bias (8-sym CORE)
```

Per-repo state:

| Repo | Role | Key facts |
|---|---|---|
| `brother_sniper_v7` | mechanical arm | 8.2k LoC. 27-gate cascade in `bot.py:582-1144`. Emits NOTHING outward (Telegram + local JSONL only). Symbols hard-coded in ~10 dicts across 4 files. |
| `brother-brain-v2` | v18 brain + dashboard | **No database anywhere** — everything is append-only JSONL + JSON state. No Trade Desk page, no Desk State, no DecisionEvent model. Dashboard is stateless pull. `platform_mirror.py` and `push_bias.py` are the only outbound pushes. |
| `session_caller` | paper session caller | 3×/day, pure math, $0 AI, reads bridge candles, writes `session_calls.json`. The proven template for deterministic session logic. |
| `pinev18.6` | **EMPTY — a trap** | Zero commits, locally and on origin. The name looks right; there is nothing in it. |

**Where Pine actually lives** (corrected 2026-08-18): repo
`sabuj14eu/sniper-system`, `pine/BrotherSniperULTIMATE_v18_FINAL_v6.pine` —
Pine v6, `pine_ver "18.12"`, ~2,898 lines, 5 `alert()` calls (PULLBACK
BUY/SELL, SMART_SCALP BUY/SELL, opt-in MANUAL_GATE). Companion
`BrotherSniper_AssetPulse_v1.pine` is display-only by design (no alerts, no
webhook). Second trap: `brother-brain-v2/brain/src/agents/
BrotherSniperULTIMATE_v18_FINAL (5).pine` is a STALE v18.7-era snapshot —
never read it as current; it predates the v18.9→18.12 arc. The live-version
check (from the brain box) proves what is actually running, because alerts
freeze the script at creation:
`grep -o '"pine_ver":"[^"]*"' /home/shyam/brain-v2/brain/logs/decisions.jsonl | sort | uniq -c`
— anything other than `18.12` (or `session_caller`) means frozen alerts and
the alert ceremony is due, not a re-paste.

The **Brother Bot Platform** (`app.signalmesh.dev`, `/srv/brotherbot`) is the
same `sniper-system` repo (FastAPI + Jinja + SQLAlchemy, Anthropic via a
single `ai_ledger` door, `BB_AI_WEEKLY_BUDGET_USD` rolling 7-day cap in
`app/services/ai_ledger.py`). Crucially, **its v7 ingest contract already
exists**: `POST {PLATFORM_URL}/webhooks/brain/decision` with header
`X-Brain-Secret` (platform `docs/INTEGRATION_V7.md`), heartbeat-shaped
artifacts to `/webhooks/brain/artifact`, and `docs/HANDOVER_V7_DESK.md`
defines the /v7 page contract: "no new rules or code — only take data",
missing field ⇒ UNKNOWN, ship a payload contract not a pull request. The
`BB_AI_WEEKLY_BUDGET_USD` env one-liner must still be run on that box by the
operator.

---

## 2. STRUCTURAL FACTS THAT CONSTRAIN THE DESIGN

These decide where the Desk can and cannot be attached. Sources are exact.

1. **v7 emits nothing.** Complete outbound surface: Telegram, the MT5 bridge,
   ForexFactory calendar, LLM APIs (`filters/deepseek_vote.py`,
   `analyst_eye.py`). No heartbeat, no dashboard push, no DB. Any `/v7` page
   feed is greenfield on the emit side.
2. **Every rejection is already captured with its gate.** The `/webhook` hook
   at `bot.py:1157-1166` writes a `_type:"reject"` row to
   `learning/telemetry.jsonl` for every blocked/filtered/skipped/paused/rejected
   signal. "Which gate stopped it" — the platform's most-wanted field —
   **already exists on disk**; it only needs transport.
3. **Symbols are code, not config.** Adding one instrument touches ~10
   hard-coded dicts across `bot.py` (SYMBOL_MAP :140, digits :154, SAFE_SPECS
   :159, price bands :677), `core/sl_engine.py` (:7,:9,:10,:43),
   `core/ic_markets.py` (:5, :72, :102 24/7 list, :120 lot caps), and the
   Windows `sniper_executor.py` (:41) — two deploy ceremonies (Linux + Windows).
4. **One crypto slot.** `ASSET_SLOTS = (metals, crypto, forex, other)`
   (`bot.py:224-232`). All altcoins contend for a single concurrent crypto
   position. The slot model, not the symbol tables, is the real cap on a
   multi-altcoin desk. XRP is already fully wired as `RIPPLE`; LTC likewise
   as `LITECOIN`. `SOL`/`ADA` appear only in `asset_class()`; LINK nowhere.
5. **No spread gate, no DXY/US10Y gate, no per-symbol sessions** in v7 —
   spread is telemetry-only (audit doc `V7_AUDIT_2026-08-01.md:60-63`),
   flow vector is log-only (`bot.py:731-733`).
6. **The join keys already exist.** v7's `signal_id` == the brain's
   `alert_name` (Pine `SS-…` id) — the dashboard's `/api/v7/h2h` already joins
   the two lanes on it. The platform joins on `pine_signal_id`.
7. **Idempotency exists but has a known flaw**: v7 dedups `signal_id` for only
   10 min (`bot.py:288-298`), and the bridge rewrites the MT5 comment to
   `BS_ + md5(sid)[:8]` (`sniper_executor.py:223`) while v7's exception-path
   RECONCILE searches for the *unhashed* `BS_<sid>` (`bot.py:1103`) — the match
   can never succeed there. Must be fixed before any Desk→bot dispatch path.
8. **Precedents to reuse, not reinvent:**
   - the dashboard `/api/v7/page` (`dashboard/backend/main.py:1077-1224`) is
     the existing v7-view UI;
   - `push_bias.py` (`:303-333`) is the existing outbound heartbeat pattern,
     including `council_paused` — the exact shape the v7 heartbeat should copy;
   - `platform_mirror.py` (`:64-99`) is the existing decision-mirror pattern
     (display-only, one-way, fire-and-forget daemon thread, feature-flagged);
   - `truth_layer.py` / `nightly_edge.py` / `cluster_engine.py` already compute
     most of the "Signal Edge / Session Edge / Gate Effectiveness" analytics
     the Desk wants — deterministically, at $0.
9. **Known contradictions (pre-existing, listed for the record, NOT fixed in
   this phase — Evidence Law applies to each):**
   - grade gate `bot.py:625` requires A/A+/B while `CLAUDE.md` records grades
     as ANTI-predictive;
   - `INTENT_v5.md` mandates 0.5% risk / 12% max DD; `risk/equity_guard.py:7-9`
     ships 1.0% base / 0.99 (99%) DD limits (audit finding H-4);
   - two session definitions (DST-aware `ai_filter._get_session` vs static UTC
     `signal_memory`); two spec tables; two `analyst_eye.py` copies;
   - `.gitignore` hazard: `learning/` is ignored as a directory — any NEW file
     under it silently doesn't commit (H-1);
   - shared plaintext secret on the v7 leg, known-leaked, rotation pending.

---

## 3. ANSWER 1 — ALTCOINS FOR V7 (SOL, XRP, ADA, LINK/LTC)

**Broker confirmation first, as requested.** This sandbox cannot reach the
bridge (:5001 timed out), so the operator runs, on any box that can:

```bash
B=http://164.68.126.105:5001
for s in SOLUSD XRPUSD ADAUSD LINKUSD LTCUSD; do
  echo "== $s"; curl -s "$B/candles?symbol=$s&tf=60&n=2" | head -c 200; echo
done
```

A symbol that returns rows is offered; one that errors needs its IC Markets
instrument name checked in the MT5 Market Watch (typical IC names: `SOLUSD`,
`XRPUSD`, `ADAUSD`, `LINKUSD`/`LNKUSD`, `LTCUSD`). Tick size and typical spread
come from the same terminal (the bridge's `/execute` response already reports
live spread per fill; `fetch_symbol_spec` is a hard-coded dict, NOT a live
query — `core/ic_markets.py:72-90` — so specs must be read off the terminal
once and entered into config). **XRP needs no wiring** (fully present as
`RIPPLE`); **LTC likewise** (`LITECOIN`) if LINK is absent.

**How to ship them — a symbol registry, not 10 more dict entries.**
Today's per-symbol knowledge is scattered (fact #3). Instead of hand-editing
ten dicts per coin, Phase A introduces `config/symbols.json` — one file, one
entry per instrument:

```json
{ "SOLANA": {
    "aliases": ["SOLUSD", "SOL"], "mt5": "SOLUSD", "asset_class": "crypto",
    "digits": 2, "price_range": [5, 2000], "always_open": true,
    "fakeout_pad": 0.0, "min_sl_pct": 1.5, "max_sl_pct": 10.0,
    "atr_est_pct": 2.0, "demo_max_lot": 1.0,
    "spec": {"tickSize": 0.01, "tickValue": 0.01, "lotMin": 0.1,
             "lotMax": 100, "lotStep": 0.1} } }
```

The existing dicts become the loader's **fallback defaults** — the registry
overlays them, so with an empty/missing file behavior is byte-identical to
today (that is the rollback path: delete the file). The bridge keeps its own
map; its 4 new lines ship in one Windows deploy ceremony. New symbols start
**bench-listed via the existing `utils/asset_gate.py`** (`ASSET_GATE_DISABLE`)
until candles/bias/telemetry are confirmed flowing, then are enabled one at a
time. Per the hand-off: candles on all TFs, bias heartbeat with spread,
decisions and candidates ship identically to existing symbols; the platform
measures STRUCTURE_MIXED and fill rates per symbol for two weeks and drops
losers on evidence.

Three cautions, agreed and encoded in the plan:
- **The crypto slot is not widened.** Four new coins still share one concurrent
  crypto position (fact #4). More opportunities, not more exposure — the risk
  engine remains authoritative. Any slot-model change is a separate,
  human-approved decision (Iron Rule 7).
- **Never pool new-symbol stats with GOLD's history** — per-symbol n counts,
  `[PROVISIONAL]` below n=20, per the Evidence Law and truth_layer convention.
- **AI spend**: adding symbols to the platform's CORE universe raises AI cost;
  the platform-side budget cap (`BB_AI_WEEKLY_BUDGET_USD`) must be set before
  expansion. On the brain side the equivalent is `BRAIN_AI_WEEKLY_BUDGET_USD`
  (already enforced in `agents/base.py`). v7 itself spends $0 per signal.

---

## 4. ANSWER 2 — THE V7 DATA FEED FOR THE PLATFORM'S `/v7` PAGE

Contract confirmed: **v7 ships data, the platform displays it. No repo access
in either direction. If v7 doesn't send a field, the page says UNKNOWN.**
Everything below already exists on v7's disk (fact #2) — this is transport,
not new computation, and it touches no execution path.

### 4.1 Per-symbol stance + gate verdicts — from telemetry/state, per event

One JSON object per Pine signal v7 finishes processing (accepted OR rejected),
mirroring `platform_mirror.py`'s fire-and-forget pattern:

```json
{ "kind": "v7_decision",
  "ts": "2026-08-18T14:05:31Z",
  "signal_id": "SS-GOLD-20260818-1405",
  "symbol": "GOLD", "direction": "BUY", "session": "london",
  "stance": "WAIT",
  "gate": "GATE-SLOT",
  "gate_detail": "metals slot held by SILVER ticket 8812345",
  "entry": 4412.7, "sl": 4404.3, "tp": 4428.0, "rr": 1.42,
  "grade": "A", "pine_score": 8, "ai_score": 6.4, "ai_threshold": 5,
  "regime": "TREND", "regime_conf": 0.72,
  "ev": 0.18, "cluster": "GOLD|BUY|london|TREND", "cluster_n": 34,
  "atr": 6.1, "spread": 0.35,
  "executed": false, "order_id": null, "lot": null,
  "bot_version": "v7", "pine_ver": "18.12" }
```

`stance` values: `TRADE` (executed) / `WAIT` (blocked, retryable condition:
slot, news, pause, EV, filter) / `REJECT` (structural: price sanity, SL
missing, RR, SL limits) / `ERROR`. `gate` is the exact tag v7 already logs
(`GATE-SLOT`, `GATE-MARGIN`, `EQUITY-GUARD`, `NEWS`, `EV-GATE`, `AI-FILTER`,
`SL-FLOOR`, `SL-LIMITS`, `RR`, `DEDUP`, `GRADE`, …) — this is the field the
platform said is most valuable, and it can reuse its v18 DecisionEvent gate
renderer for it. Every field is optional-by-contract: absent ⇒ UNKNOWN.

### 4.2 Heartbeat + risk state — every 60s from the existing monitor loop

```json
{ "kind": "v7_heartbeat",
  "ts": "2026-08-18T14:06:00Z",
  "paused": false, "hard_stopped": false,
  "consecutive_losses": 1,
  "equity": 6712.40, "balance": 6698.20, "peak_balance": 6749.72,
  "day_pnl": 12.1, "week_pnl": -3.4,
  "open_slots": { "metals": {"symbol": "SILVER", "ticket": 8812345,
                              "side": "BUY", "mae": 1.2, "mfe": 3.4},
                  "crypto": null, "forex": null, "other": null },
  "bridge_ok": true, "last_signal_ts": "2026-08-18T14:05:31Z",
  "symbols_enabled": ["GOLD","SILVER","BITCOIN","..."],
  "bot_version": "v7" }
```

This makes "v7 said nothing for an hour" distinguishable from "no setups"
(same rationale as the brain's `council_paused` heartbeat), and carries the
risk state: open positions, exposure, EquityGuard/kill-switch flags.

### 4.3 Transport — two options, platform's choice

- **Push (preferred, mirrors `push_bias.py`):** POST to
  `{PLATFORM_WEBHOOK_URL}/webhooks/v7/...` with an `X-V7-Secret` header, from
  a daemon thread, feature-flagged `V7_MIRROR_ENABLED` (default **false**),
  failures swallowed after one retry — the mirror must never block or crash
  the trading path (directive §30).
- **Pull fallback:** v7 atomically maintains `learning/v7_status.json`
  (heartbeat + last N decisions) and the existing stateless dashboard serves
  it — zero new network surface.

What v7 **cannot** send today (so the page shows UNKNOWN, honestly): a stance
for symbols with no recent signal (v7 is reactive — it has no standing
per-symbol view between Pine alerts; "the entry/SL/TP it would use" exists
only at signal time), and spread outside trade moments (bench symbols).

---

## 5. WHERE THE DESK STATE LAYER FITS — SMALLEST SAFE CHANGE

The directive's target (AI at session level → persistent Desk State →
deterministic per-signal decisions) maps onto what already exists:

| Directive concept | Existing seed | Gap |
|---|---|---|
| News/macro layer | `push_bias.py` DXY/US10Y/8-sym bias; FF calendar in v7 | no persisted event state; brain's `news.jsonl` has no writer |
| Session desk (deterministic) | `session_caller` (3×/day, $0) | writes only its own calls; no shared Desk State object |
| AI session analysis | 6-agent council (per-signal today) | no session-cadence invocation; **v18 stays as-is, so this lands later and only for v7's desk context** |
| Desk State store | — (greenfield, confirmed twice) | new JSON/JSONL store, `valid_until`, staleness |
| Deterministic per-signal decision | v7's 27-gate cascade; brain's gate chain | v7 gates don't consult any desk context (fine for Phase 1) |
| Decision Lab / audit | `decisions.jsonl` + `telemetry.jsonl` + truth_layer | v7 side needs transport only |
| Desk UI | dashboard `/api/v7/page` + platform | needs the §4 feed |

**Smallest safe first change (Phase 1):** the §4 emit layer + the §3 symbol
registry. Both are read-only with respect to trading logic: no gate changes,
no risk changes, no new execution path, no AI calls, v18 untouched. Rollback
is `V7_MIRROR_ENABLED=false` / delete `config/symbols.json`.

**Desk State itself (Phase 2)** starts as a *file*, not a database — matching
the platform's JSONL-everywhere architecture: `desk_state.json` with
`{session, regime, per-symbol bias/confidence, risk_mode, news_risk,
preferred_direction, avoid, volatility, created_at, valid_until, source,
version}`, written first by **deterministic** producers (session_caller's math
generalized to all symbols + push_bias's EMA/ATR regime), consumed initially
by NOTHING (observe-only, journaled, two weeks of evidence), then — only with
journal evidence per the Evidence Law — optionally consulted by v7's cascade
as one more gate. AI session analysis (Phase 3) *interprets into* that same
file on session boundaries only, structured-output, budget-capped, and its
absence degrades to `AI_CONTEXT_UNAVAILABLE` + the deterministic content.
Stale `valid_until` ⇒ the state reads STALE and deterministic fallback rules
apply — same honesty pattern `push_bias.py` already uses for stale bias rows.

### Phased plan (each phase = separate commits, separate evidence gate)

| Phase | Content | Execution impact |
|---|---|---|
| **1a** | v7 emit layer: `v7_heartbeat` + `v7_decision` mirror (§4), feature-flagged OFF | none |
| **1b** | `config/symbols.json` registry + loader with dict fallbacks; tests | none (empty file = today) |
| **1c** | Wire SOL/ADA/LINK (XRP/LTC exist) after broker confirmation; bench-listed via asset_gate; bridge map update (Windows ceremony) | none until un-benched, one at a time |
| **2** | `desk_state.json` — deterministic producers only, observe-only, expiry | none |
| **3** | Session-cadence AI interpretation into Desk State (budget-capped, fallback-safe) | none |
| **4** | Desk-aware gate in v7 cascade — only if 2 weeks of observe-only journal evidence supports it (n≥20 per rule) | gated, evidence-first |
| **5+** | Candidate→Approved-Order records, then (much later, with idempotency fixed per fact #7, full audit trail, kill-switch) any Desk→bot dispatch | explicitly deferred |

Prerequisite fix worth its own tiny commit before any dispatch work:
the comment-hash mismatch (fact #7) and the 10-minute dedup window.

### What this project will NOT do
No v18 changes. No strategy changes (thresholds, ATR multipliers, SL/TP, session
rules, grades) — architecture and strategy are separate projects (directive
§24). No slot-model widening. No AI in the per-signal path. No database
migration — the JSONL-everywhere design is deliberate and stays. No secrets in
git. No live testing — demo lane first, always.

---

## 6. DEVELOPMENT CHANGELOG

| Date | Change | Files | Reason | Tests | Result | Rollback |
|---|---|---|---|---|---|---|
| 2026-08-18 | Phase 1 audit + this proposal | `docs/V7_DESK_AUDIT_2026-08-18.md` | Directive §48 steps 1–10 | n/a (doc only) | audit complete | `git revert` |
| 2026-08-18 | **1a** v7 status emitter | `core/v7_status.py`, `tests/test_v7_status.py` | v7 emitted nothing; desk needs stance+gate per signal and a heartbeat | 9 new, suite 54✓ | shipped | revert commit |
| 2026-08-18 | **1a** wiring (no behavior change) | `bot.py` (+24 lines, guarded hooks) | record verdicts at the /webhook choke point; heartbeat each monitor cycle | suite 54✓, compile✓ | shipped | revert commit |
| 2026-08-18 | **1a** align push with platform contract | `core/v7_status.py` | platform INTEGRATION_V7.md already defines the wire: /webhooks/brain/decision, X-Brain-Secret, PLATFORM_URL/SECRET; system stamped "v7" (normalize_system trap), Pine system → pine_system | 9✓ | shipped | unset PLATFORM_URL/SECRET (inert) or revert |
| 2026-08-18 | **1b** symbol registry | `core/symbol_registry.py`, `config/symbols.json` ({}), hoists in `core/sl_engine.py` + `core/ic_markets.py`, `bot.py` overlay, `tests/test_symbol_registry.py` | symbols were code in ~10 dicts across 4 files | 6 new, suite 60✓; end-to-end enable proven (alias→GATE-PRICE) | shipped; {} = byte-identical | delete config/symbols.json |
| 2026-08-18 | **1c** altcoin candidates | `config/symbols.json` (SOLANA/CARDANO/CHAINLINK, enabled:false), `config/README.md` (enable ceremony), `sniper_executor.py` aliases | SOL/ADA/LINK requested; XRP/LTC already wired; specs must be broker-verified first | suite 60✓; test enforces all entries benched | shipped, zero behavior change | entries stay false / revert |
| 2026-08-18 | V7 Desk page (dashboard repo) | `brother-brain-v2/dashboard/backend/v7_desk.py`, `main.py` (+guarded 3-line register), `tests/test_v7_desk.py` | desk view over v7's own feed: freshness, per-symbol stance+gate, why-not-trade, edge tables (n<20 PROVISIONAL) | 8 new✓; Chromium render, no JS errors | shipped, display-only | revert commit (register is guarded) |

**Deploy ceremony still owed by the operator** (nothing is live until then):
v7 box: backup → `git pull` → restart `sniper-bot.service` → verify
`[V7-STATUS]`/`[SYMBOLS]` lines in logs/bot.log and that
`learning/v7_status.json` appears. Dashboard box: same for
`brother-dashboard.service`, then open `/api/v7/desk/page?t=<token>`.
Optional platform push: set `PLATFORM_URL` + `PLATFORM_SECRET` in v7's .env
(values per platform INTEGRATION_V7.md; secret = platform
`BB_BRAIN_WEBHOOK_SECRET`) — leave unset and the mirror stays inert.
