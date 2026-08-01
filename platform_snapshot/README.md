# Brother Bot Platform

Multi-tenant SaaS platform for the Brother Sniper trading system (v7 + v18).
Public website, phone-number registration with SMS OTP, per-user trading
dashboard, MT5 account management, Telegram/SMS notifications, analytics,
risk manager, subscriptions/wallet/affiliate, support, and a full
admin + super-admin back office — one codebase, built to scale from a
handful of users to thousands without another CMS redesign.

> **Safety invariant:** this platform NEVER dispatches trades or signals.
> It receives a read-only mirror of the v18 brain's decisions for display
> and analytics. See `CLAUDE.md` (Iron Rules).

## Stack

- **FastAPI** + **SQLAlchemy 2** (SQLite for dev, Postgres in production)
- Server-rendered **Jinja2** UI (Tailwind + Chart.js via CDN) — no build step
- **REST API v1** (`/api/v1`, API-key auth) + inbound webhook mirror
- JWT session cookies, TOTP 2FA, hashed OTPs, encrypted MT5 credentials

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit secrets
python -m scripts.seed          # plans, symbols, demo admin + demo user
uvicorn app.main:app --reload
```

- Public site: http://127.0.0.1:8000/
- Demo user: `demo@example.com` (or `+10000000001`), password `demo1234`
- Demo admin: `admin@example.com` (or `+10000000000`), password `admin1234` → `/admin`
- Registration verifies by **email**; dev codes are printed to the console
  (`BB_EMAIL_PROVIDER=console`). Configure Brevo/SMTP for real delivery —
  SMS is optional and only active with a Twilio config.

## Tests

```bash
pytest -q
```

## Production deployment

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — Docker Compose stack
(app + Postgres + Redis + Caddy auto-HTTPS), nightly backups, monitoring
(`/metrics`, `/readyz`, Sentry), secret rotation, and the go-live checklist.
Release notes and schema migrations live in [docs/CHANGELOG.md](docs/CHANGELOG.md).

## Module map

| Area | Where |
|---|---|
| Public site (home, pricing, blog, status, legal…) | `app/routers/public.py` |
| Auth: register + email/SMS code, login, 2FA, recovery | `app/routers/auth.py` |
| User dashboard (portfolio, AI panel, notifications) | `app/routers/dashboard.py` |
| MT5 accounts, Telegram, bot settings, symbols, risk | `app/routers/accounts.py`, `settings_bot.py` |
| Signals, trade journal, analytics | `app/routers/trading.py` |
| Subscription, wallet, affiliate | `app/routers/billing.py` |
| Support, downloads, API keys, security, profile | `app/routers/account_misc.py` |
| Admin + super-admin panels | `app/routers/admin.py` |
| REST API v1 | `app/routers/api_v1.py` |
| Brain signal mirror (read-only ingest) | `app/routers/webhooks.py` |
