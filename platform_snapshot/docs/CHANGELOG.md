# Changelog

## 1.2.0 — Email-first verification & account recovery

Registration no longer depends on SMS. Email is the primary identity and
verification channel; phone is optional and SMS activates only when a
provider (Twilio) is configured.

- New mailer service (`app/services/mailer.py`): providers `console` (dev),
  `smtp` (any relay), `brevo` (HTTP API, free tier ~300 mails/day).
- Registration: email required, verification code sent by email; phone-only
  registration still possible and verifies by SMS when configured.
- Login accepts **email or phone** in one field; unverified users are routed
  back through verification automatically.
- Account recovery (`/forgot`): emailed code → new password; completing an
  email recovery also marks the address verified.
- Changing the profile email resets verification and re-sends a code;
  duplicate emails rejected.
- Seed users now have emails: `admin@example.com`, `demo@example.com`
  (log in with email or phone).

Schema changes vs 1.1.0 (SQL for existing DBs; fresh deploys need nothing):
```sql
ALTER TABLE otp_codes RENAME COLUMN phone TO destination;
ALTER TABLE otp_codes ALTER COLUMN destination TYPE VARCHAR(255);
ALTER TABLE users ALTER COLUMN phone DROP NOT NULL;
CREATE UNIQUE INDEX ix_users_email ON users (email);
```

## 1.1.0 — Hardening & enterprise pass

Security
- Sliding-window rate limits + 15-min lockout on login, OTP send, register,
  forgot-password (`app/services/ratelimit.py`; Redis-ready interface).
- CSRF origin-check middleware for browser form posts; security headers
  (HSTS in production, nosniff, frame-deny).
- Secret rotation: `BB_OLD_SECRET_KEYS` fallback for sessions and encrypted
  MT5 credentials.

Features
- **Broker Executor Monitor**: MT5/EA versions, trade latency, execution
  queue length, symbol sync, auto-reconnect, last ok/failed order (+reason)
  on the VPS page; reported via `POST /api/v1/heartbeat/vps` and
  `/heartbeat/trade`.
- **AI Decision Replay**: per-signal timeline (original alert verbatim →
  council decision incl. macro/truth-layer → status changes → MT5 execution
  with latency → Telegram fan-out → outcome) on the signal detail page.
- **Background sweeper** (every 60s): bot-offline notifications on stale
  heartbeats, automatic emergency stop on daily-loss/consecutive-loss
  breaches, subscription expiry reminders + wallet auto-renew with downgrade.
- **Finance**: VAT-aware invoices with printable page (browser → PDF),
  payment-provider slots (Stripe/PayPal/Przelewy24 appear when configured),
  provider-aware deposits.
- **Monitoring**: `/metrics` (Prometheus), `/readyz` (DB probe), optional
  Sentry via `BB_SENTRY_DSN`.

Ops
- Dockerfile, docker-compose (app+Postgres+Redis+Caddy auto-HTTPS),
  nightly backup script with retention, GitHub Actions CI,
  `docs/DEPLOYMENT.md` runbook.

Schema changes vs 1.0.0 (SQL for existing DBs; fresh deploys need nothing):
```sql
ALTER TABLE mt5_accounts ADD COLUMN offline_notified BOOLEAN DEFAULT FALSE;
ALTER TABLE vps_status ADD COLUMN mt5_version VARCHAR(32) DEFAULT '';
ALTER TABLE vps_status ADD COLUMN ea_version VARCHAR(32) DEFAULT '';
ALTER TABLE vps_status ADD COLUMN trade_latency_ms FLOAT DEFAULT 0;
ALTER TABLE vps_status ADD COLUMN queue_length INTEGER DEFAULT 0;
ALTER TABLE vps_status ADD COLUMN symbols_synced BOOLEAN DEFAULT FALSE;
ALTER TABLE vps_status ADD COLUMN auto_reconnect BOOLEAN DEFAULT TRUE;
ALTER TABLE vps_status ADD COLUMN last_order_ok_at TIMESTAMPTZ;
ALTER TABLE vps_status ADD COLUMN last_order_fail_at TIMESTAMPTZ;
ALTER TABLE vps_status ADD COLUMN last_order_fail_reason VARCHAR(255) DEFAULT '';
ALTER TABLE invoices ADD COLUMN vat_rate FLOAT DEFAULT 0;
-- new table: signal_events (created automatically by create_all)
```

## 1.0.0 — Initial platform

Full multi-tenant SaaS: public site, phone+OTP auth with TOTP 2FA, one-page
dashboard, MT5/Telegram/SMS management, bot settings, symbols, risk manager
with emergency stop, copier, VPS monitor, signals/journal/analytics,
subscriptions/wallet/affiliate, support, downloads, API keys, audit logs,
admin + super-admin panels, REST API v1, read-only brain signal mirror.
