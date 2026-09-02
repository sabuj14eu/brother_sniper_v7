# A2 — retire the v7 secret auto-injection (the nginx mirror carries the secret)

**Status 2026-09-02 (round 3):** v7 side SHIPPED DARK — `/webhook` accepts
`X-Webhook-Secret` for a *missing* body secret (`patch_webhook_header_secret.py`,
applied to the repo `bot.py`; tests `tests/test_round3_a2_incident.py::test_a2_*`).
The auto-injection in `handle_signal` is UNTOUCHED until step 2's log line proves
the mirror carries the header. Box side: one nginx line, then verify, then flip.

## Why this exists
Pine alerts hit `brain.signalmesh.dev/webhook/v18`; nginx `mirror` copies each
request to the v7 bot (`127.0.0.1:5000/webhook`). A mirrored body cannot be
rewritten, so the copy carries no `secret` — that is why `bot.py` auto-injects
the secret for `system in (BSv16, BSv17, BSv18, BSv11)`. Since round 2 that path
trusts X-Forwarded-For from loopback only. The remaining gap: anything on the
box's loopback can post a Pine-shaped body and be trusted. Deleting the
injection outright would cut off every Pine signal (round-1 refusal, correct).

## Step 1 — nginx on the brain box (Shyam)
In the location the mirror targets, add ONE line (the secret is v7's
`WEBHOOK_SECRET` from `/home/shyam/brother_sniper_v7/.env`):

    proxy_set_header X-Webhook-Secret "<v7 WEBHOOK_SECRET>";

Shape of the block, for orientation only — adapt to the real config, never
copy blindly:

    location = /webhook/v18 {
        mirror /_v7_mirror;
        mirror_request_body on;
        proxy_pass http://127.0.0.1:8443;
    }
    location = /_v7_mirror {
        internal;
        proxy_pass http://127.0.0.1:5000/webhook;
        proxy_set_header X-Webhook-Secret "<v7 WEBHOOK_SECRET>";
        proxy_set_header X-Forwarded-For $remote_addr;
    }

    sudo nginx -t && sudo systemctl reload nginx

The secret lives in `/etc/nginx/...` on the box only. It is never committed.

## Step 2 — v7 box deploy + verify
    cd /home/shyam/brother_sniper_v7
    git fetch origin claude/evidence-integrity-audit-35rlfa
    git checkout origin/claude/evidence-integrity-audit-35rlfa -- bot.py patch_webhook_header_secret.py
    python3 patch_webhook_header_secret.py      # prints ALREADY PATCHED when the repo copy carries it
    sudo systemctl restart sniper-bot
    grep -c "\[A2\] secret from header" logs/bot.log   # one line per mirrored Pine alert

Acceptance: after the next real Pine alert the count is ≥ 1 and the alert
traded/was judged exactly as before. Zero after a real alert means the mirror
block is not the one edited, or nginx was not reloaded.

## Step 3 — later round, after ≥ 1 day of every mirrored alert logging the A2 line
Remove the auto-injection block in `handle_signal` (its own patch script,
anchor-safe), restart, verify: Pine alerts still trade; a secret-less
Pine-shaped POST from loopback now answers `unauthorized`. Then rotate
`WEBHOOK_SECRET` (the 08-01 hygiene note still owes that rotation).
