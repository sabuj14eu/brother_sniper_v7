#!/usr/bin/env python3
"""Publish a repo document to the platform as an artifact (read-only, $0).

The platform session cannot read this repo — different repo, different box —
so work orders and contracts had to be pasted by hand into chat, which is how
a spec gets truncated and a rule like "action never ships without why +
invalidation" quietly goes missing on day one. Documents travel the pipe
everything else already travels: POST /webhooks/brain/artifact.

Synchronous on purpose. core.v7_status._push is fire-and-forget on a daemon
thread, which is right for a heartbeat and wrong here — a CLI that exits
before its own POST lands would report success it never had. This one waits
and prints the status code.

SECRET GUARD (Iron Rule 8): a file that looks like it carries credentials is
REFUSED, not sent. Docs are written by hand and hand-written files acquire
pasted tokens; publishing is irreversible.

    python3 push_doc.py                       # the standing doc set
    python3 push_doc.py docs/FOO.md --dry-run
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
PATH = "/webhooks/brain/artifact"
TIMEOUT = 15

# Documents the platform session needs to build against.
DEFAULT_DOCS = [
    "docs/TRADE_DESK_LIVE_MGMT_WORK_ORDER.md",
    "docs/V7_DESK_WORK_ORDER.md",
    "docs/SESSION_COORDINATION.md",
]

# A line ASSIGNING something that smells like a credential.
#
# The keyword is wrapped in optional name characters rather than \b: `_` is a
# word character, so \bsecret\b never matches inside PLATFORM_SECRET=... —
# precisely the shape this project's secrets take. A test caught that.
#
# What separates a leak from ordinary prose is the ASSIGNMENT: a doc says
# "PLATFORM_SECRET must be set" (no `=`/`:` + value) a hundred times and must
# never be blocked for it. Requiring [:=] plus 8+ non-space characters draws
# that line without a list of exceptions.
_SECRET_LINE = re.compile(
    r"(?i)[A-Z0-9_.\-]*"
    r"(secret|token|password|passwd|api[_-]?key|private[_-]?key)"
    r"[A-Z0-9_.\-]*\s*[:=]\s*\S{8,}")


def _env(key: str) -> str:
    v = os.getenv(key, "").strip()
    if v:
        return v
    try:
        with open(os.path.join(BASE, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def scan_secrets(text: str) -> list:
    """Lines that look like a credential assignment. Empty list = safe to send."""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        # No exemption for comment or quote lines: a relayed message pasted
        # into a doc as "> PLATFORM_SECRET=..." is exactly how one escapes.
        if _SECRET_LINE.search(line):
            hits.append((i, line.strip()[:60]))
    return hits


def title_of(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BASE,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def build_payload(rel_path: str, text: str, sha: str) -> dict:
    name = os.path.basename(rel_path)
    return {
        "kind": "doc",
        "doc_id": name,
        "title": title_of(text, name),
        "repo": "brother_sniper_v7",
        "path": rel_path,
        "commit": sha,
        "format": "markdown",
        "markdown": text,
        "bytes": len(text.encode("utf-8")),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def post(payload: dict, url: str, secret: str) -> int:
    req = urllib.request.Request(
        url.rstrip("/") + PATH, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Brain-Secret": secret})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    dry = "--dry-run" in argv
    force = "--force" in argv
    docs = [a for a in argv if not a.startswith("-")] or DEFAULT_DOCS

    url, secret = _env("PLATFORM_URL"), _env("PLATFORM_SECRET")
    if not dry and not (url and secret):
        print("PLATFORM_URL / PLATFORM_SECRET not set — nothing sent")
        return 1

    sha, sent, failed = _sha(), 0, 0
    for rel in docs:
        full = rel if os.path.isabs(rel) else os.path.join(BASE, rel)
        try:
            with open(full, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            print(f"  SKIP {rel} — not on this branch")
            continue

        hits = scan_secrets(text)
        if hits and not force:
            print(f"  REFUSED {rel} — looks like it carries a credential:")
            for ln, preview in hits[:3]:
                print(f"      line {ln}: {preview}")
            print("      fix the file, or --force if you are certain")
            failed += 1
            continue

        payload = build_payload(rel, text, sha)
        if dry:
            print(f"  [dry] {rel} · {payload['bytes']}B · "
                  f"title={payload['title'][:48]!r}")
            sent += 1
            continue
        try:
            code = post(payload, url, secret)
            print(f"  {'OK ' if code < 300 else 'HTTP ' + str(code)} {rel} "
                  f"({payload['bytes']}B)")
            sent += code < 300
            failed += code >= 300
        except Exception as e:
            print(f"  FAIL {rel} — {type(e).__name__}: {e}")
            failed += 1

    print(f"docs sent {sent} · failed {failed}" + (" (DRY RUN)" if dry else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
