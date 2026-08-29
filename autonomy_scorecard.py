#!/usr/bin/env python3
"""Daily autonomy scorecard (Week-2, 2026-08-31).

Counts the day's AUTONOMOUS record — the bot's own words, never a
re-grade: scenario transitions (logs/auto_scenarios.jsonl), dry/armed
fires (logs/auto_live.jsonl), management events (learning/trades.jsonl),
state audit (logs/mgmt_audit_last.json — NOT RUN if absent today).

PINE-DEPENDENT DECISIONS MUST = 0: any record here missing
pine_dependency=NONE counts against autonomy, loudly.

    python3 autonomy_scorecard.py                # today (UTC)
    python3 autonomy_scorecard.py 2026-09-01     # one day
    python3 autonomy_scorecard.py --post         # today + push doc to platform

Cron:  55 23 * * * cd /home/shyam/brother_sniper_v7 && /usr/bin/python3 autonomy_scorecard.py --post >> logs/autonomy_scorecard.log 2>&1
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

from auto_live import DIR, DRY_LOG, SCEN_LOG, _env

TRADES = os.path.join(DIR, "learning", "trades.jsonl")
AUDIT = os.path.join(DIR, "logs", "mgmt_audit_last.json")


def _day(ts):
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return str(ts)[:10]                      # ISO string fallback


def _jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except Exception:
                        pass
    except FileNotFoundError:
        return


def scorecard(day):
    scen = [r for r in _jsonl(SCEN_LOG) if _day(r.get("ts")) == day]
    fires = [r for r in _jsonl(DRY_LOG) if _day(r.get("posted_at")) == day]
    ready = [r for r in scen if "READY" in str(r.get("state"))]
    dev = [r for r in scen if "DEVELOPING" in str(r.get("state"))]
    waits = [r for r in scen if str(r.get("state")).startswith(("⚪", "⛔"))]
    n_all = len(scen) + len(fires)
    pine_dep = sum(1 for r in scen + fires if r.get("pine_dependency") != "NONE")
    mgmt = sum(1 for r in _jsonl(TRADES)
               if _day(r.get("ts") or r.get("closed_at") or "") == day
               and ("won" in r or "net_profit" in r or r.get("be_done")))
    stale_viol = sum(1 for r in ready + dev if r.get("freshness") != "OK")
    try:
        with open(AUDIT, encoding="utf-8") as f:
            a = json.load(f)
        audit = str(a.get("violations")) if str(a.get("ts", ""))[:10] == day else "NOT RUN today"
    except Exception:
        audit = "NOT RUN"
    return {
        "day": day,
        "PINE-INDEPENDENT DECISIONS": n_all - pine_dep,
        "AUTONOMY FAILURES": pine_dep + stale_viol,
        "COMPLETE DECISIONS": sum(1 for r in ready if all(r.get(k) for k in ("entry", "sl", "tp", "rr"))),
        "WAIT WITH REASON": sum(1 for r in waits if r.get("missing_confirmation") or r.get("current_state")),
        "CONDITIONAL SETUPS": len(dev),
        "CONFIRMED SETUPS": len(ready),
        "MANAGEMENT DECISIONS": mgmt,
        "STATE VIOLATIONS": audit,
        "STALE-DATA VIOLATIONS": stale_viol,
        "PINE-DEPENDENT DECISIONS": pine_dep,
    }


def render(sc):
    lines = [f"# AUTONOMY SCORECARD — {sc['day']}", ""]
    for k, val in sc.items():
        if k == "day":
            continue
        flag = "  ← MUST = 0, IS NOT" if k == "PINE-DEPENDENT DECISIONS" and val else ""
        lines.append(f"{k}: {val}{flag}")
    lines.append("")
    lines.append("Source: the bot's own logs, counted verbatim. UNKNOWN stays UNKNOWN.")
    return "\n".join(lines)


def post(md, day):
    url, secret = _env("PLATFORM_WEBHOOK_URL"), _env("PLATFORM_WEBHOOK_SECRET")
    if not url or not secret:
        print("post skipped: PLATFORM_WEBHOOK_URL/SECRET not set")
        return
    body = {"kind": "doc", "path": f"docs/AUTONOMY_SCORECARD_{day}.md",
            "title": f"AUTONOMY_SCORECARD_{day}.md", "content": md,
            "markdown": md, "source": "bot box daily scorecard",
            "ts": datetime.now(timezone.utc).isoformat()}
    req = urllib.request.Request(
        f"{url.rstrip('/')}/webhooks/brain/artifact",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Brain-Secret": secret})
    with urllib.request.urlopen(req, timeout=20) as r:
        print(f"posted scorecard {day} -> {r.status}")


def main():
    args = [a for a in sys.argv[1:] if a != "--post"]
    day = args[0] if args else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sc = scorecard(day)
    md = render(sc)
    print(md)
    if "--post" in sys.argv:
        post(md, day)
    return 0


if __name__ == "__main__":
    sys.exit(main())
