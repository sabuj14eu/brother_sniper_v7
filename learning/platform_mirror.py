"""Read-only mirror: post every v7 decision to the Brother Bot Platform.

THE LAW (same as the v18 mirror): the platform DISPLAYS what v7 decided.
It never dispatches trades, never modifies signals, never becomes an input
to a trading decision. Data flows one way only: bot -> platform. Nothing in
this module returns anything the trading path reads.

- Non-blocking: POST runs on a daemon thread; the webhook path never waits.
- Aggressive timeout (3s) so even the worker thread dies fast.
- Fail-silent: platform errors are logged and the payload is queued to
  learning/mirror_queue.jsonl; each later call opportunistically flushes a
  few queued rows (async retry). The queue is capped; oldest rows drop.
- Feature-flagged: PLATFORM_MIRROR_ENABLED (default false).
- signal_id is prefixed "v7-" so the SAME Pine signal judged by BOTH arms
  shows as two decisions on the platform (v18 council vs v7 mechanical),
  never as one overwriting the other.
- telemetry.jsonl is never touched by this module (read-only sibling).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request

log = logging.getLogger("sniper.platform_mirror")

_QUEUE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_queue.jsonl")
_QUEUE_MAX = 5000          # rows kept when trimming
_FLUSH_PER_CALL = 5        # opportunistic retries per new decision
_TIMEOUT = 3.0
_lock = threading.Lock()


def mirror_enabled() -> bool:
    return os.getenv("PLATFORM_MIRROR_ENABLED", "false").lower() in ("1", "true", "yes")


def build_v7_payload(payload: dict, status: str, reason: str = "",
                     order_id=None) -> dict:
    """Map a v7 decision onto the platform webhook contract (v18-compatible).

    status_in: v7's own status word (rejected/blocked/filtered/skipped/
    paused/ignored -> platform 'rejected'; executed open -> 'approved').
    council 0/0 = non-council path, exactly how gate decisions render for v18.
    """
    p = payload or {}
    approved = status == "approved"
    return {
        "signal_id": f"v7-{p.get('signal_id') or 'unknown'}",
        "system": "BSv7",
        "symbol": p.get("symbol"),
        "direction": (p.get("direction") or p.get("signal") or "").upper() or None,
        "entry": p.get("entry"),
        "sl": p.get("sl"),
        "tp1": p.get("tp1", p.get("tp")),
        "tp2": p.get("tp2"),
        "rr": p.get("rr"),
        "grade": p.get("grade"),
        "council": {"approve": 0, "total": 0},
        "status": "approved" if approved else "rejected",
        "confidence": None,
        # append-only extras (platform passes unknown keys through)
        "v7_status": status,
        "reject_reason": (reason or "")[:300] or None,
        "order_id": order_id,
        "pine_ver": p.get("pine_ver"),
        "type": p.get("type"),
    }


def _post_one(body: dict, url: str, secret: str) -> bool:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{url.rstrip('/')}/webhooks/brain/signal", data=data,
        headers={"Content-Type": "application/json", "X-Brain-Secret": secret})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.status < 300


def _enqueue(body: dict) -> None:
    try:
        with _lock:
            with open(_QUEUE, "a", encoding="utf-8") as f:
                f.write(json.dumps(body) + "\n")
    except Exception:
        pass


def _flush_queue(url: str, secret: str) -> None:
    """Retry a few queued failures; rewrite the queue with what remains."""
    try:
        with _lock:
            if not os.path.exists(_QUEUE):
                return
            lines = open(_QUEUE, encoding="utf-8").read().splitlines()
        if not lines:
            return
        sent = 0
        remaining = []
        for i, ln in enumerate(lines):
            if sent >= _FLUSH_PER_CALL:
                remaining.extend(lines[i:])
                break
            try:
                if _post_one(json.loads(ln), url, secret):
                    sent += 1
                else:
                    remaining.append(ln)
            except Exception:
                remaining.append(ln)
                remaining.extend(lines[i + 1:])   # platform still down; stop trying
                break
        remaining = remaining[-_QUEUE_MAX:]
        with _lock:
            with open(_QUEUE, "w", encoding="utf-8") as f:
                f.write("\n".join(remaining) + ("\n" if remaining else ""))
        if sent:
            log.info(f"platform mirror: flushed {sent} queued row(s), {len(remaining)} left")
    except Exception as e:
        log.warning(f"platform mirror: queue flush skipped: {type(e).__name__}")


def _worker(body: dict, url: str, secret: str) -> None:
    """Daemon thread. Never raises."""
    try:
        ok = _post_one(body, url, secret)
        if ok:
            log.info(f"platform mirror: posted {body.get('signal_id')} "
                     f"status={body.get('status')} ({body.get('v7_status')})")
        else:
            log.warning(f"platform mirror: non-2xx for {body.get('signal_id')} — queued")
            _enqueue(body)
    except Exception as e:
        log.warning(f"platform mirror: post failed ({type(e).__name__}) — queued")
        _enqueue(body)
    _flush_queue(url, secret)


def mirror_v7(payload: dict, status: str, reason: str = "", order_id=None) -> None:
    """Fire-and-forget mirror of one v7 decision. Never raises, never blocks."""
    try:
        if not mirror_enabled():
            return
        url = os.getenv("PLATFORM_WEBHOOK_URL", "").strip()
        secret = os.getenv("PLATFORM_WEBHOOK_SECRET", "").strip()
        if not url or not secret:
            log.warning("platform mirror: enabled but PLATFORM_WEBHOOK_URL/"
                        "PLATFORM_WEBHOOK_SECRET not set — skipping")
            return
        body = build_v7_payload(payload, status, reason, order_id)
        threading.Thread(target=_worker, args=(body, url, secret), daemon=True).start()
    except Exception as e:
        log.warning(f"platform mirror: skipped ({type(e).__name__})")
