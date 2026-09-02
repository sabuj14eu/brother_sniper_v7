#!/usr/bin/env python3
"""Incident update -> platform incident ingest (2026-09-02, work-order §3).

When this side works an incident the platform opened, this posts the
finding so approval happens in the UI instead of chat:
    root_cause · fix_ref (commit/branch/file) · tests_summary

Route: env INCIDENT_INGEST_PATH, default /webhooks/brain/incident — the
platform session owns the spec; if they named it differently, one .env
line fixes it, no redeploy. Same auth as every other ingest.

    python3 post_incident.py INC-123 \
        --root-cause "executor served count:0 while MT5 was down" \
        --fix-ref "brother_sniper_v7@<commit> patch_truth_guards.py" \
        --tests "tests/test_round2_guards.py 2 passed" \
        [--status investigating|patch_proposed] [--dry-run]
"""
from __future__ import annotations

import argparse
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


# Platform contract (v5.04, quoted by the platform session 2026-09-02): an
# agent may report INVESTIGATING or PATCH_PROPOSED — nothing else. APPROVED,
# REJECTED and RESOLVED are the human's buttons: the platform refuses them
# with a reason while still saving the fields. The reply carries "status"
# (what the board now shows) and "refused" (why the ask did not apply); a
# bare "-> 200" hid exactly that refusal once, so both are printed.
STATUS_MAP = {"investigating": "INVESTIGATING",
              "patch_proposed": "PATCH_PROPOSED",
              "fix_proposed": "PATCH_PROPOSED"}   # old spelling, same meaning


def normalize_status(s):
    return STATUS_MAP[str(s).strip().lower()]


def report_reply(incident_id, http_status, body):
    try:
        d = json.loads(body or b"{}")
    except Exception:
        d = {}
    line = f"posted {incident_id} -> {http_status}; board status: {d.get('status', '?')}"
    if d.get("refused"):
        line += f"\n  REFUSED: {d['refused']}"
    return line


def build_payload(args):
    # Both id keys, always: the platform read only public_id until its 5.04
    # (2026-09-02) and only incident_id is what this side sent -> 404 "no
    # incident ''" for a round trip. Sending both is append-only and works
    # against every platform version.
    return {"kind": "incident_update", "incident_id": args.incident_id,
            "public_id": args.incident_id,
            "root_cause": args.root_cause, "fix_ref": args.fix_ref,
            "tests_summary": args.tests, "status": normalize_status(args.status),
            "source": "bot session",
            "ts": datetime.now(timezone.utc).isoformat()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("incident_id")
    ap.add_argument("--root-cause", required=True, dest="root_cause")
    ap.add_argument("--fix-ref", required=True, dest="fix_ref")
    ap.add_argument("--tests", required=True)
    ap.add_argument("--status", default="investigating",
                    choices=sorted(STATUS_MAP),
                    help="what an agent may report; approve/reject/resolve are the human's buttons on the board")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    payload = build_payload(args)
    if args.dry_run:
        print(json.dumps(payload, indent=1))
        return 0
    url, secret = _env("PLATFORM_WEBHOOK_URL"), _env("PLATFORM_WEBHOOK_SECRET")
    if not url or not secret:
        print("REFUSED: PLATFORM_WEBHOOK_URL/SECRET not set")
        return 1
    path = _env("INCIDENT_INGEST_PATH", "/webhooks/brain/incident")
    req = urllib.request.Request(
        f"{url.rstrip('/')}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Brain-Secret": secret})
    with urllib.request.urlopen(req, timeout=15) as r:
        print(report_reply(args.incident_id, r.status, r.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
