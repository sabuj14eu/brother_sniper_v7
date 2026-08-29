#!/usr/bin/env python3
"""Weekly readiness report -> platform artifact webhook (2026-08-30).

The platform's Autonomy Readiness page renders the newest doc whose path
contains AUTONOMY_READINESS, verbatim — it authors nothing and arms
nothing. This script is the one POST that feeds it: read the newest
docs/AUTONOMY_READINESS_*.md and send it as kind:"doc" on the same
artifact webhook the brain already uses (push_bias.post_brain_status).

POST {PLATFORM_WEBHOOK_URL}/webhooks/brain/artifact, X-Brain-Secret.
Payload carries the markdown under BOTH "content" and "markdown" so
either reader key works; the listener passes unknown keys through
(payload contract is append-only on both sides).

Cron (after the Sunday report lands in the repo):
    45 21 * * 0 cd /home/shyam/brother_sniper_v7 && /usr/bin/python3 post_readiness.py >> logs/post_readiness.log 2>&1

--dry-run prints the payload head and posts nothing.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

DIR = os.path.dirname(os.path.abspath(__file__))


def _env(key, default=""):
    v = os.getenv(key, "").strip()
    if v:
        return v
    try:
        with open(os.path.join(DIR, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return default


def newest_report():
    """Newest AUTONOMY_READINESS_*.md by the date in its filename."""
    paths = sorted(glob.glob(os.path.join(DIR, "docs", "AUTONOMY_READINESS_*.md")))
    return paths[-1] if paths else None


def build_payload(path):
    with open(path, encoding="utf-8") as f:
        md = f.read()
    rel = os.path.relpath(path, DIR)
    return {
        "kind": "doc",
        "path": rel,                       # match key: contains AUTONOMY_READINESS
        "title": os.path.basename(rel),
        "content": md,
        "markdown": md,
        "source": "bot box weekly readiness",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    path = newest_report()
    if not path:
        print("REFUSED: no docs/AUTONOMY_READINESS_*.md found — an absent report is a fact, not a blank")
        return 1
    payload = build_payload(path)
    if "--dry-run" in sys.argv:
        head = payload["content"].splitlines()[:6]
        print(f"DRY RUN — would post {payload['path']} ({len(payload['content'])} chars):")
        for line in head:
            print(f"  {line}")
        return 0
    url = _env("PLATFORM_WEBHOOK_URL")
    secret = _env("PLATFORM_WEBHOOK_SECRET")
    if not url or not secret:
        print("REFUSED: PLATFORM_WEBHOOK_URL/PLATFORM_WEBHOOK_SECRET not set")
        return 1
    req = urllib.request.Request(
        f"{url.rstrip('/')}/webhooks/brain/artifact",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Brain-Secret": secret})
    with urllib.request.urlopen(req, timeout=20) as r:
        print(f"posted {payload['path']} -> {r.status} {r.read().decode()[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
