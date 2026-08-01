"""In-process sliding-window rate limiter for auth-sensitive endpoints.

Good for a single app process (the default deployment). When scaling to
multiple workers/hosts, back this with Redis using the same interface —
callers only use allow()/lockout_remaining().
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

_buckets: dict[tuple[str, str], deque] = defaultdict(deque)
_lock = threading.Lock()

# bucket -> (max hits, window seconds)
LIMITS = {
    "login": (8, 300),        # 8 attempts / 5 min per phone+IP
    "login_fail": (10, 900),  # 10 failures / 15 min per phone -> lockout
    "otp_send": (4, 600),     # 4 SMS / 10 min per phone
    "register": (5, 3600),    # 5 registrations / hour per IP
    "forgot": (5, 3600),
}


def _prune(q: deque, window: float, now: float) -> None:
    while q and q[0] <= now - window:
        q.popleft()


def allow(bucket: str, key: str) -> bool:
    """Record one hit; return False when over the limit."""
    limit, window = LIMITS[bucket]
    now = time.monotonic()
    with _lock:
        q = _buckets[(bucket, key)]
        _prune(q, window, now)
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def record(bucket: str, key: str) -> None:
    """Record a hit without enforcing (e.g. counting failures)."""
    _, window = LIMITS[bucket]
    now = time.monotonic()
    with _lock:
        q = _buckets[(bucket, key)]
        _prune(q, window, now)
        q.append(now)


def is_locked(bucket: str, key: str) -> bool:
    limit, window = LIMITS[bucket]
    now = time.monotonic()
    with _lock:
        q = _buckets[(bucket, key)]
        _prune(q, window, now)
        return len(q) >= limit


def clear(bucket: str, key: str) -> None:
    with _lock:
        _buckets.pop((bucket, key), None)


def reset_all() -> None:
    """Test helper."""
    with _lock:
        _buckets.clear()
