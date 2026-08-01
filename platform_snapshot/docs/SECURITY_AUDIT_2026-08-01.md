# Brother Bot Platform — Security Audit & Fixes, 2026-08-01

FastAPI SaaS at app.signalmesh.dev: accounts, subscriptions, wallet, MT5 account
management, trade copier, admin CMS, and the read-only brain webhook mirror.

**Headline:** the *code* is clean — ownership checks are consistent, every query
uses the ORM (no SQLi found), Jinja autoescape is on with no `|safe` on user
content (no XSS found), passwords are scrypt, OTP/API-keys are hashed, the brain
webhook secret is compared constant-time. The real risk was in **config defaults
and one wallet bug**, not the design. This PR fixes the verifiable ones.

## Scores (this repo)

| Axis | Before | After PR |
|---|---|---|
| Security | 4/10 | **7/10** |
| Maintainability | 7/10 | 7/10 |
| Scalability | 5/10 | 5/10 |
| Production readiness | 3/10 | **6/10** (blockers below closed; payments still stubbed) |

## Fixed in this PR (27 tests pass, incl. 5 new)

| # | Sev | Fix | File |
|---|---|---|---|
| C1 | 🔴 CRITICAL | **Default `secret_key` in prod** → forgeable JWT admin sessions + decrypts all stored MT5 creds. Added `assert_secure_for_production()` that refuses to boot prod on the shipped default secret_key/brain_webhook_secret; wired at app startup. | `config.py`, `main.py` |
| C1b | 🔴 CRITICAL | **Session/token not bound** — `_resolve_user` trusted the token's `sub` and only matched the session by `sid`, so a forged token amplified into full impersonation. Now `sess.user_id` is authoritative and must equal `sub`. | `deps.py` |
| C2 | 🔴 CRITICAL | **Wallet self-credit** — `POST /wallet/deposit` auto-completed a client-supplied amount in any non-production env (default `development`) → free unlimited balance. Now completes ONLY under an explicit `BB_WALLET_AUTOCREDIT_DEV` sandbox flag (default off); production always `pending`. | `billing.py`, `config.py` |
| H1 | 🟠 HIGH | **Default `brain_webhook_secret`** (gates the public webhook + all-user Telegram fan-out) — covered by the same prod secret-guard. | `config.py`, `main.py` |
| H4 | 🟡 MED→HIGH | **Admin-on-admin takeover** — only super-admin targets were protected; one admin could reset_password/ban a peer admin. Now only a super-admin may act on any admin-level account. | `admin.py` |
| — | 🟡 MED | **Withdrawal double-approve** — admin approval didn't re-check the balance; two pending withdrawals could both approve into a negative balance. Re-verifies current balance at approval. | `admin.py` |
| — | 🟡 MED | **Open redirect** on login `?next=` — now only local paths (single leading slash, no `//host`, no scheme) are honored. | `auth.py` |

## Reported — NOT fixed here (needs your decision / bigger change)

- **H2 — payments are entirely stubbed** (`services/payments.py` raises for
  stripe/paypal/p24; no `/webhooks/payments/*` route exists, so no provider
  signature verification and no money-in path in production). This is a *build*
  task, not a bug-fix — real subscriptions can't be paid for until a provider is
  integrated. **Prioritize before charging real users.**
- **H5 — seeded known-password superadmin** (`scripts/seed.py`: `admin1234`).
  Fine for demo; **rotate/guard so `seed.main()` can't create it in production.**
- **Home-grown credential cipher** sharing the JWT key (`security.py:122-149`) —
  works and is MAC-verified, but swap for Fernet/KMS so a key compromise isn't
  total. Left alone (crypto change needs its own careful review).
- **Referral bonus instantly withdrawable** (`billing.py:97-100`) — consider
  holding it `pending` until the referred subscription clears a refund window.
- **Public `/metrics`** leaks business counts — uncomment the Caddy IP guard
  (`Caddyfile:13-14`) rather than a code change, so monitoring still scrapes it.
- **No Alembic/migrations** (`create_all` only) — column changes won't apply to a
  live Postgres DB; add a migration baseline.
- **Unpinned deps + CI runs tests only** — pin a lockfile; add a dep/secret scan
  to `ci.yml`.
- **In-process rate limiter** — fine on the single-worker Dockerfile today; move
  to Redis before scaling to multiple workers.
- **Admin temp password in redirect URL** (`admin.py`) — lands in history/logs;
  show it once in the page body instead. LOW.

## Deploy note (when you restart the platform)

Two env vars must be set for production, or the app now **refuses to start** (by
design): `BB_SECRET_KEY` and `BB_BRAIN_WEBHOOK_SECRET` (each `openssl rand -hex
32`). You already set `BB_BRAIN_WEBHOOK_SECRET` during the mirror deploy — make
sure `BB_SECRET_KEY` is a strong value too, and `BB_ENV=production`. Do NOT set
`BB_WALLET_AUTOCREDIT_DEV` anywhere near production. Everything else is
backward-compatible; the 27-test suite passes.

## Not changed: the read-only-mirror law holds
Per this repo's CLAUDE.md Rule 1, nothing here dispatches trades. The webhook
ingest stores and displays; none of these fixes touch that boundary.
