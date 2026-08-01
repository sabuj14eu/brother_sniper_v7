# Deploying Brother Bot Platform to a server

Target: a Linux VPS (e.g. your Contabo box), Ubuntu 22.04/24.04, with a domain
you control. Recommended path is **Docker Compose** (app + Postgres + Redis +
Caddy with automatic HTTPS). A bare-metal systemd path is at the end.

---

## 0. Prerequisites

- A domain/subdomain, e.g. `app.yourdomain.com`, with an **A record** pointing
  to the VPS IP (do this first — Caddy needs it to issue the TLS certificate).
- Ports **80** and **443** open in the provider firewall.
- SSH access with sudo.

## 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # re-login afterwards
```

## 2. Get the code

```bash
sudo mkdir -p /srv && cd /srv
git clone https://github.com/sabuj14eu/Sniper-System.git brotherbot
cd brotherbot
git checkout claude/brother-bot-trading-platform-58o7gr   # or main after merge
```

## 3. Configure secrets

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # -> BB_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # -> BB_BRAIN_WEBHOOK_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # -> POSTGRES_PASSWORD
nano .env
```

Set at minimum:

| Key | Value |
|---|---|
| `BB_SECRET_KEY` | the generated 48-byte string |
| `BB_ENV` | `production` |
| `BB_BASE_URL` | `https://app.yourdomain.com` |
| `BB_BRAIN_WEBHOOK_SECRET` | generated; the v18 brain must send it as `X-Brain-Secret` |
| `BB_EMAIL_PROVIDER` | **required for registration to work**: `brevo` + `BB_BREVO_API_KEY` (free tier ~300 mails/day, sign up at brevo.com) or `smtp` + `BB_SMTP_*` (Mailjet/any relay). Verification and recovery codes are emailed. |
| `BB_EMAIL_FROM` | e.g. `Brother Bot <no-reply@yourdomain.com>` — verify this sender/domain in Brevo for deliverability |
| `BB_SMS_PROVIDER` | optional: `twilio` + SID/token/from enables the SMS channel; without it phone OTP stays off and email does everything |
| `POSTGRES_PASSWORD` | generated |
| `BB_COMPANY_*`, `BB_VAT_RATE` | your invoice identity (23% for Poland) |

Then edit `Caddyfile` and replace `app.yourdomain.com` with your domain.

`chmod 600 .env` — it never leaves this machine and is never committed.

## 4. First launch

```bash
docker compose up -d --build
docker compose logs -f app        # wait for "Uvicorn running"
```

Seed plans + the admin account (one time):

```bash
docker compose exec app python -m scripts.seed
```

**Immediately log in** at `https://app.yourdomain.com` as `+10000000000 /
admin1234`, then: change the password (Security page), enable Google
Authenticator 2FA, and delete or re-password the demo user (`+10000000001`)
from Admin → Users.

## 5. Verify (don't trust green lights — check behaviour)

```bash
curl -s https://app.yourdomain.com/healthz     # {"ok":true} = process up
curl -s https://app.yourdomain.com/readyz      # {"ok":true,"db":true} = DB answers
curl -s https://app.yourdomain.com/metrics     # prometheus counters
```

Real end-to-end checks:
1. Register a fresh account with your real email → the verification code must
   arrive in the inbox (check spam; verify your sender domain in Brevo).
   Then test **account recovery**: log out → "Forgot password" → emailed code.
2. Connect Telegram (bot token + chat ID) → "Send test message" must land.
3. Send a signed test signal from the brain box and watch it appear on
   `/signals` with a decision-replay timeline:

```bash
curl -s -X POST https://app.yourdomain.com/webhooks/brain/signal \
  -H "Content-Type: application/json" -H "X-Brain-Secret: $BB_BRAIN_WEBHOOK_SECRET" \
  -d '{"signal_id":"DEPLOY-TEST-1","system":"v18","symbol":"GOLD","direction":"BUY",
       "entry":4125.4,"sl":4118,"tp1":4132,"tp2":4138,"rr":1.4,"grade":"A",
       "council":{"approve":6,"total":6},"status":"approved","confidence":92}'
```

## 6. Wire the v18 brain and executors

- **Brain → platform** (read-only mirror; the platform never dispatches):
  after each council decision, POST the payload to
  `/webhooks/brain/signal`; market bias to `/webhooks/brain/bias`; calendar
  events to `/webhooks/brain/news`. All with header `X-Brain-Secret`.
- **Executor/VPS agent → platform**: each user creates an API key
  (Dashboard → API, "read + heartbeat write") and the agent posts:
  - `POST /api/v1/heartbeat/account` — balance/equity/margin per MT5 login
  - `POST /api/v1/heartbeat/vps` — CPU/RAM/disk/latency, MT5+EA versions,
    queue length, symbol sync (feeds the Executor Monitor)
  - `POST /api/v1/heartbeat/trade` — every fill/close, with
    `signal_id` + `execution_latency_ms` (feeds journal, analytics, replay)
- **Emergency stop / risk flags**: executors should poll `GET /api/v1/stats`
  or read the emergency flag before opening anything new. The sweeper engages
  the stop automatically on daily-loss or consecutive-loss breaches.

## 7. Backups (nightly, 14-day retention)

```bash
chmod +x scripts/backup.sh
sudo crontab -e
# add:
0 3 * * * /srv/brotherbot/scripts/backup.sh >> /var/log/brotherbot-backup.log 2>&1
```

**Test a restore now, not during an incident:**

```bash
docker compose exec -T db pg_restore -U brotherbot -d brotherbot --clean \
  < backups/brotherbot-<stamp>.dump
```

Copy `backups/` off-box (rclone to any object storage) for real disaster
recovery.

## 8. Updates (deploy ceremony: backup → deploy → restart → verify)

```bash
cd /srv/brotherbot
./scripts/backup.sh
git pull
docker compose up -d --build
docker compose logs --tail 50 app     # verify in logs, not just exit codes
curl -s https://app.yourdomain.com/readyz
```

Schema note: `create_all` adds new tables automatically; for column changes
on an existing production DB, apply the SQL listed in docs/CHANGELOG.md for
that release before restarting (or adopt Alembic once the schema stabilises).

## 9. Monitoring

- **Sentry**: `docker compose exec app pip install sentry-sdk` is not
  persistent — instead add `sentry-sdk` to requirements.txt, set
  `BB_SENTRY_DSN` in `.env`, rebuild. Unhandled exceptions then report
  automatically.
- **Prometheus/Grafana**: scrape `https://app.yourdomain.com/metrics`
  (restrict the path in the Caddyfile if you prefer it private). Counters:
  users, active sessions, MT5 online, signals, open trades, webhook errors.
- **Uptime**: point UptimeRobot/Hetrix at `/readyz` (checks DB, not just the
  process). Remember Iron Rule 5: also alert on **stale heartbeats** — the
  sweeper already notifies users when a bot goes silent for 10+ minutes.
- **CI**: GitHub Actions runs the full test suite on every push
  (`.github/workflows/ci.yml`).

## 10. Secret rotation

1. Generate a new `BB_SECRET_KEY`.
2. Move the old value into `BB_OLD_SECRET_KEYS` (comma-separated history).
3. `docker compose up -d` — sessions stay valid and stored MT5 credentials
   still decrypt (old-key fallback). Users re-saving credentials re-encrypt
   with the new key.
4. After ~30 days, clear `BB_OLD_SECRET_KEYS`.

Rotate `BB_BRAIN_WEBHOOK_SECRET` in lock-step with the brain's sender config.

## 11. Scaling checkpoints

| Stage | Action |
|---|---|
| ~100 users | Nothing — single app container is fine |
| ~500 users | `uvicorn --workers 4` in the Dockerfile CMD; move rate limiting to Redis (interface is isolated in `app/services/ratelimit.py`) |
| ~1000+ users | Second app container + Caddy load balancing; Postgres tuning (`shared_buffers`, connection pool); move Telegram fan-out to a worker queue (Redis is already in the stack) |
| 10k+ signals | Already indexed (`signals.created_at`, `signal_id`); archive `webhook_logs` monthly |

---

## Alternative: bare-metal (no Docker)

```bash
sudo apt update && sudo apt install -y python3-venv postgresql nginx certbot python3-certbot-nginx
sudo -u postgres createuser brotherbot -P && sudo -u postgres createdb brotherbot -O brotherbot
cd /srv/brotherbot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env    # BB_DATABASE_URL=postgresql+psycopg://brotherbot:***@localhost/brotherbot
.venv/bin/python -m scripts.seed
```

`/etc/systemd/system/brotherbot.service`:

```ini
[Unit]
Description=Brother Bot Platform
After=network.target postgresql.service

[Service]
User=www-data
WorkingDirectory=/srv/brotherbot
ExecStart=/srv/brotherbot/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now brotherbot
sudo certbot --nginx -d app.yourdomain.com   # nginx: proxy_pass http://127.0.0.1:8000
```

---

## Go-live checklist

- [ ] `BB_ENV=production`, strong unique `BB_SECRET_KEY`, `.env` chmod 600
- [ ] HTTPS live (padlock on `https://app.yourdomain.com`)
- [ ] Admin password changed + 2FA enabled; demo user removed
- [ ] Email live (Brevo/SMTP): registration code + recovery code received on a real inbox
- [ ] (Optional) Twilio live: SMS OTP works for phone-based accounts
- [ ] Telegram test message delivered
- [ ] Signed test signal visible on /signals with replay timeline
- [ ] Executor heartbeats arriving (accounts show *online*, VPS page populated)
- [ ] Nightly backup cron installed **and one restore rehearsed**
- [ ] Uptime monitor on `/readyz`; Sentry DSN set
- [ ] Legal pages published in CMS (`legal-terms`, `legal-privacy`,
      `legal-risk-disclaimer`, `legal-cookies`, `legal-gdpr`)
- [ ] Plans/pricing reviewed in Admin; VAT identity set for invoices
- [ ] Emergency stop tested end-to-end (button → executor actually halts)
- [ ] All connected accounts are **demo** until the system earns live status
      (Evidence Law: n≥20 minimum, judge nothing before ~100 trades)
