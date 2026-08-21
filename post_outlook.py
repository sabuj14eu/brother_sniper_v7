"""Post a weekly/monthly outlook to the platform — the permanent tool (2026-08-21).

The platform's Outlook board (v4.39) renders what this posts; until something
posts, the desk chips read ABSENT, which is correct — the desk never invents
an outlook. This CLI is the bot box's permanent way to send one:

    cd /home/shyam/brother_sniper_v7 && python3 post_outlook.py \
        --symbol GOLD --horizon weekly --source "Shyam" \
        --thesis "Dollar softening after the buyback doubling; gold holding the 4460 shelf." \
        --scenario "above:4600:bullish acceptance, continuation toward 4640" \
        --scenario "below:4460:shelf lost, retest of 4400"

Contract (built to the wire — app/routers/webhooks.py brain_outlook):
  POST {PLATFORM_WEBHOOK_URL}/webhooks/brain/outlook, X-Brain-Secret header.
  Fields: symbol, horizon weekly|monthly, thesis, source,
          scenarios [{when: above|below, level, reading}], valid_hours?
  (defaults: weekly 168h, monthly 720h — omit --valid-hours to use them).

TWO REFUSALS, enforced HERE as well as server-side:
  - confidence/probability/chance never leave this script. The platform
    rejects them by name; this script refuses to build them at all.
  - an outlook with no thesis, no source, or a level with no reading is
    refused locally with the reason — a blank never rides an envelope.

Append-only: a changed mind is a NEW post, not an edit. Read-only mirror law:
this sends display data; nothing here can place, modify or cancel a trade.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
BANNED = ("confidence", "probability", "chance")


def _env(key: str) -> str:
    """os.environ first (service style), then the repo .env (CLI style) —
    the same values the platform mirror reads, never retyped by hand."""
    v = (os.getenv(key) or "").strip()
    if v:
        return v
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return ""


def parse_scenario(raw: str) -> dict:
    """'above:4600:bullish acceptance' -> {when, level, reading}.
    The reading may contain colons; only the first two split."""
    parts = raw.split(":", 2)
    if len(parts) != 3:
        raise SystemExit(f"REFUSED scenario {raw!r}: need when:level:reading "
                         f"(e.g. \"above:4600:bullish acceptance\")")
    when, level_s, reading = parts[0].strip().lower(), parts[1].strip(), parts[2].strip()
    if when not in ("above", "below"):
        raise SystemExit(f"REFUSED scenario {raw!r}: when must be above|below, got {when!r}")
    try:
        level = float(level_s)
    except ValueError:
        raise SystemExit(f"REFUSED scenario {raw!r}: level must be a number, got {level_s!r}")
    if not reading:
        raise SystemExit(f"REFUSED scenario {raw!r}: a level with no reading is noise")
    for word in BANNED:
        if word in reading.lower():
            raise SystemExit(f"REFUSED scenario {raw!r}: contains {word!r} — send levels "
                             f"and readings, not certainty (platform rejects it by name)")
    return {"when": when, "level": level, "reading": reading}


def build_payload(symbol: str, horizon: str, thesis: str, source: str,
                  scenarios: list[str], valid_hours: int | None) -> dict:
    if horizon not in ("weekly", "monthly"):
        raise SystemExit(f"REFUSED: horizon must be weekly|monthly, got {horizon!r}")
    if not thesis.strip():
        raise SystemExit("REFUSED: thesis is required — an outlook with no thesis "
                         "is a blank wearing an envelope")
    if not source.strip():
        raise SystemExit("REFUSED: source is required — every outlook names its author")
    for word in BANNED:
        if word in thesis.lower():
            raise SystemExit(f"REFUSED: thesis contains {word!r} — send levels and "
                             f"readings, not certainty (platform rejects it by name)")
    body = {
        "symbol": symbol.upper().strip(),
        "horizon": horizon,
        "thesis": thesis.strip(),
        "source": source.strip(),
        "scenarios": [parse_scenario(s) for s in scenarios],
    }
    if valid_hours is not None:
        body["valid_hours"] = int(valid_hours)
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--horizon", required=True, choices=("weekly", "monthly"))
    ap.add_argument("--thesis", required=True)
    ap.add_argument("--source", required=True,
                    help="the author's name — a person or 'bot box'")
    ap.add_argument("--scenario", action="append", default=[],
                    metavar="when:level:reading",
                    help="repeatable, e.g. \"above:4600:bullish acceptance\"")
    ap.add_argument("--valid-hours", type=int, default=None,
                    help="omit for the defaults (weekly 168h / monthly 720h)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the payload, send nothing")
    a = ap.parse_args()

    body = build_payload(a.symbol, a.horizon, a.thesis, a.source,
                         a.scenario, a.valid_hours)
    if a.dry_run:
        print(json.dumps(body, indent=2))
        return 0

    url = _env("PLATFORM_WEBHOOK_URL")
    secret = _env("PLATFORM_WEBHOOK_SECRET")
    if not url or not secret:
        print("REFUSED to send: PLATFORM_WEBHOOK_URL / PLATFORM_WEBHOOK_SECRET "
              "not set (env or .env) — same values the platform mirror uses. "
              "The secret is never typed into chat (Iron Rule 8).")
        return 1

    req = urllib.request.Request(
        f"{url.rstrip('/')}/webhooks/brain/outlook",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Brain-Secret": secret})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            reply = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"PLATFORM REFUSED ({e.code}): {e.read().decode()[:400]}")
        return 1
    except Exception as e:
        print(f"SEND FAILED (nothing stored): {e}")
        return 1
    print(f"STORED: outlook id={reply.get('id')} {reply.get('symbol')} "
          f"{reply.get('horizon')} · {reply.get('scenarios')} scenario(s) · "
          f"valid until {reply.get('valid_until')}")
    if reply.get("ignored_keys"):
        print(f"NOTE — platform ignored keys: {reply['ignored_keys']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
