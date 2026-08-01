#!/usr/bin/env bash
# Nightly Postgres backup with 14-day retention.
# Cron (on the host):  0 3 * * *  /srv/brotherbot/scripts/backup.sh >> /var/log/brotherbot-backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."
STAMP=$(date -u +%Y%m%d-%H%M%S)
mkdir -p backups

docker compose exec -T db pg_dump -U brotherbot -Fc brotherbot > "backups/brotherbot-${STAMP}.dump"
find backups -name 'brotherbot-*.dump' -mtime +14 -delete

echo "[$(date -u)] backup done: backups/brotherbot-${STAMP}.dump ($(du -h "backups/brotherbot-${STAMP}.dump" | cut -f1))"

# Restore procedure (deploy ceremony: backup -> restore -> restart -> verify):
#   docker compose exec -T db pg_restore -U brotherbot -d brotherbot --clean < backups/brotherbot-YYYYMMDD-HHMMSS.dump
