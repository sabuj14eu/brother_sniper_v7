#!/usr/bin/env python3
"""Live economic-calendar feed -> platform /webhooks/brain/news.

Fetches the free ForexFactory weekly calendar JSON (this week + next week)
and POSTs normalized events to the platform, whose ingest dedupes by
(title, event_time) — so running this hourly is idempotent and also picks
up late 'actual' revisions as fresh rows only when title/time changed.

Read-only side feed: never touches trading. Fail-soft: any error logs and
exits 0 so the cron chain never breaks (same discipline as push_artifacts).

Cron (hourly, next to the artifact push):
    7 * * * * cd /home/shyam/brother_sniper_v7 && /usr/bin/python3 push_news.py >> logs/news_push.log 2>&1
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

_DIR = os.path.dirname(os.path.abspath(__file__))

FEEDS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]
# currency -> symbols this system actually trades (platform maps/ignores rest)
AFFECTED = {
    "USD": ["XAUUSD", "XAGUSD", "USTEC", "US30", "EURUSD", "USDJPY", "BTCUSD", "ETHUSD"],
    "EUR": ["EURUSD"],
    "JPY": ["USDJPY"],
    "ALL": ["XAUUSD", "XAGUSD", "USTEC", "US30", "EURUSD", "USDJPY"],
}
BATCH = 200
_UA = {"User-Agent": "Mozilla/5.0 (BrotherBot news feed)"}


def _env(key):
    v = os.getenv(key, "").strip()
    if v:
        return v
    try:
        with open(os.path.join(_DIR, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def normalize(raw: list) -> list:
    """FF rows -> platform ingest shape. Drops rows without title/date."""
    out = []
    for r in raw or []:
        title = str(r.get("title") or "").strip()
        when = str(r.get("date") or "").strip()
        if not title or not when:
            continue
        try:  # validate the ISO stamp the same way the ingest will
            datetime.fromisoformat(when)
        except ValueError:
            continue
        cur = str(r.get("country") or "USD").upper()
        item = {
            "title": title,
            "event_time": when,
            "impact": str(r.get("impact") or "medium").lower(),
            "currency": cur,
            "affected_symbols": AFFECTED.get(cur, []),
        }
        # surprise dimension (append-only): forecast/previous ship pre-release;
        # 'actual' fills in the feed post-release — landing it requires the
        # platform ingest to update-on-conflict instead of skipping existing.
        for k in ("forecast", "previous", "actual"):
            v = r.get(k)
            if v not in (None, ""):
                item[k] = str(v)
        out.append(item)
    return out


def main():
    url = _env("PLATFORM_WEBHOOK_URL")
    secret = _env("PLATFORM_WEBHOOK_SECRET")
    if not url or not secret:
        print("[news] PLATFORM_WEBHOOK_URL/SECRET not set — nothing pushed")
        return

    events = []
    for feed in FEEDS:
        try:
            req = urllib.request.Request(feed, headers=_UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                events.extend(normalize(json.loads(r.read().decode("utf-8"))))
        except Exception as e:
            print(f"[news] feed failed (non-fatal): {feed}: {type(e).__name__}")

    if not events:
        print("[news] no events fetched — nothing pushed")
        return

    stored = 0
    for i in range(0, len(events), BATCH):
        chunk = events[i:i + BATCH]
        try:
            req = urllib.request.Request(
                f"{url.rstrip('/')}/webhooks/brain/news",
                data=json.dumps(chunk).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Brain-Secret": secret})
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode("utf-8"))
                stored += int(resp.get("stored", 0))
        except Exception as e:
            print(f"[news] batch {i // BATCH} failed (non-fatal): {type(e).__name__}")

    print(f"[news] {datetime.now(timezone.utc).isoformat()} fetched={len(events)} newly_stored={stored}")


if __name__ == "__main__":
    main()
