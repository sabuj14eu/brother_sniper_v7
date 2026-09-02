#!/usr/bin/env python3
"""A2 (2026-09-02, round 3): the nginx mirror that copies Pine alerts to v7
cannot rewrite the mirrored JSON body, which is WHY bot.py auto-injects the
secret for trusted Pine systems. To retire that injection the mirror must
carry the secret some other way — a header it CAN set
(proxy_set_header X-Webhook-Secret). This patch teaches the /webhook route
to fill a MISSING payload secret from that header. It never overrides a
secret the body already carries, and handle_signal remains the only place
the secret is checked. The auto-injection is untouched here; it is removed
in a later round once logs/bot.log shows every mirrored alert arriving with
the header ("[A2] secret from header"). Box steps: docs/A2_NGINX_MIRROR_SECRET.md

    python3 patch_webhook_header_secret.py
"""
import ast, os, shutil, sys, time

BOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")
MARK = "[A2 2026-09-02]"
ROUTE_OLD = '@app.route("/webhook",methods=["POST"])\ndef webhook():\n'
ROUTE_NEW = (
    '# ' + MARK + ' the nginx mirror cannot rewrite a mirrored body, so it may\n'
    '# carry the webhook secret as a header instead (proxy_set_header\n'
    '# X-Webhook-Secret). The header fills a MISSING payload secret only, never\n'
    '# overrides one, and handle_signal stays the single place it is checked.\n'
    'def _header_secret(payload, headers):\n'
    '    try:\n'
    '        if isinstance(payload, dict) and not payload.get("secret"):\n'
    '            h = (headers.get("X-Webhook-Secret") or "").strip()\n'
    '            if h:\n'
    '                payload["secret"] = h\n'
    '                log.info("[A2] secret from header (system=%s)", payload.get("system"))\n'
    '    except Exception as e:\n'
    '        log.warning(f"[A2] header secret skipped (non-fatal): {e}")\n'
    '    return payload\n'
    '\n' + ROUTE_OLD)
CALL_OLD = '    result=handle_signal(payload,raw)\n'
CALL_NEW = '    payload=_header_secret(payload,request.headers)  # ' + MARK + '\n' + CALL_OLD


def main():
    src = open(BOT, encoding="utf-8").read()
    if MARK in src:
        print("ALREADY PATCHED — nothing to do")
        return 0
    for name, old in (("route", ROUTE_OLD), ("call", CALL_OLD)):
        if src.count(old) != 1:
            print(f"ABORT: {name} anchor found {src.count(old)}x, need exactly 1 — untouched")
            return 1
    bak = f"{BOT}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(BOT, bak)
    out = src.replace(ROUTE_OLD, ROUTE_NEW).replace(CALL_OLD, CALL_NEW)
    open(BOT, "w", encoding="utf-8").write(out)
    try:
        ast.parse(out)
    except SyntaxError as e:
        shutil.copy2(bak, BOT)
        print(f"ABORT: compile failed ({e}) — RESTORED")
        return 1
    print(f"PATCHED bot.py — /webhook accepts X-Webhook-Secret for a missing body secret (backup {os.path.basename(bak)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
