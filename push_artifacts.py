#!/usr/bin/env python3
"""Nightly artifact push: scorecard + edge report -> platform Research page.

Runs the two analytics scripts, captures their text output, and POSTs each
as an artifact to the platform (/webhooks/brain/artifact, X-Brain-Secret).
Read-only mirror of analytics the bot already produces — never touches
trading. Any failure exits 0 with a log line; a broken platform never
breaks the cron chain.

Cron (after the nightly analytics window):
    15 3 * * * cd /home/shyam/brother_sniper_v7 && /usr/bin/python3 push_artifacts.py >> logs/artifact_push.log 2>&1
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

_DIR = os.path.dirname(os.path.abspath(__file__))

ARTIFACTS = [
    {"kind": "scorecard", "title": "v7 scorecard",
     "cmd": [sys.executable, os.path.join(_DIR, "scorecard.py")]},
    {"kind": "edge_report", "title": "v7 nightly edge (unified)",
     "cmd": [sys.executable, os.path.join(_DIR, "nightly_edge.py"), "--unified"]},
]


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


def main():
    url = _env("PLATFORM_WEBHOOK_URL")
    secret = _env("PLATFORM_WEBHOOK_SECRET")
    if not url or not secret:
        print("[artifact] PLATFORM_WEBHOOK_URL/SECRET not set — nothing pushed")
        return
    for a in ARTIFACTS:
        try:
            out = subprocess.run(a["cmd"], capture_output=True, text=True,
                                 timeout=600, cwd=_DIR)
            content = (out.stdout or "") + (("\n[stderr]\n" + out.stderr) if out.returncode else "")
            if not content.strip():
                print(f"[artifact] {a['kind']}: empty output — skipped")
                continue
            body = {
                "system": "BSv7",
                "kind": a["kind"],
                "title": a["title"],
                "ts": datetime.now(timezone.utc).isoformat(),
                "content": content[-120000:],   # keep the tail if enormous
            }
            req = urllib.request.Request(
                f"{url.rstrip('/')}/webhooks/brain/artifact",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Brain-Secret": secret})
            with urllib.request.urlopen(req, timeout=20) as r:
                print(f"[artifact] {a['kind']}: HTTP {r.status}")
        except Exception as e:
            print(f"[artifact] {a['kind']}: FAILED {type(e).__name__}: {e} (non-fatal)")


if __name__ == "__main__":
    main()
