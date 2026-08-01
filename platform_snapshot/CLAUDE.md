# CLAUDE.md — Brother Bot Platform Constitution

Read this before touching anything. This repository is the multi-tenant SaaS
platform (public site, user dashboard, admin) for the Brother Sniper trading
system. The trading brain (v18 council) and the v7 bot live elsewhere; this
platform observes and manages — it never trades.

## IRON RULES — NEVER VIOLATE
1. NOTHING here dispatches signals. The platform receives a **read-only
   mirror** of signals/decisions from the v18 brain for display, journaling
   and analytics. No code path in this repo may send an order, a dispatch, or
   any instruction to an executor. The CMS manages accounts/routing metadata,
   NEVER signals.
2. Payload contract is APPEND-ONLY. The signal mirror stores the raw payload
   verbatim (`Signal.raw_payload`) and never renames/removes fields the brain
   sends (system, signal, direction, signal_id, symbol, tf, entry, sl, tp,
   tp1, tp2, rr, grade). Unknown keys pass through.
3. Never widen risk silently. Risk limits, lot sizes and emergency-stop state
   are explicit user/admin decisions, and every change is written to the
   audit log with its actor.
4. Secrets (.env, tokens, MT5 passwords, API keys) are never committed and
   never printed in logs, templates, or chat. Stored credentials are
   encrypted at rest; API keys and OTPs are stored hashed.
5. Health endpoints lie; only tickets/journal tell the truth. Status displays
   must be driven by reported heartbeats with staleness windows, never by
   "the endpoint returned 200".
6. Every schema change ships with a migration note in docs/CHANGELOG.md.
   Deploys follow: backup -> migrate -> restart -> verify logs.

## LAYOUT
- `app/main.py` — FastAPI app factory; all routers mounted here.
- `app/models/` — SQLAlchemy models (user, trading, billing, platform).
- `app/services/` — business logic (otp, analytics, notify, audit, billing).
- `app/routers/` — public site, auth, user dashboard modules, admin, API v1,
  and the brain mirror ingest (`webhooks.py`).
- `app/templates/` — Jinja2: `public/`, `dash/`, `admin/` on shared bases.
- `scripts/seed.py` — seed plans, symbols, demo admin + demo data.
- `tests/` — smoke tests over the full route surface.

## HOW TO WORK HERE
Findings first, then code. Small verified diffs over rewrites. Run
`pytest -q` before every commit. All user-visible money/risk numbers come
from the database, never hardcoded in templates.
