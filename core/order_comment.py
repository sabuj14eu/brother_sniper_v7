"""The MT5 order comment — the only thread tying a broker position to a signal.

BUG THIS EXISTS TO FIX (found 2026-08-18, audit finding):
the bot sent `signal_id` to the bridge and then searched broker positions for
a comment equal to `BS_<signal_id>` (bot.py RECONCILE path), but the bridge
writes `BS_ + md5(signal_id)[:8]` (sniper_executor.py:229). The comparison
could never be true, so the crash-recovery path — the one that adopts a
position when the order actually filled but the HTTP call timed out — never
matched anything. The ticket-based paths were unaffected, which is why the
bug stayed invisible: it only bites during a timeout, and then silently.

Fixed on the BOT side alone, deliberately: matching both forms needs no
change to the Windows bridge and no change to what is sent to MT5, so the
order path is untouched. If the bridge's comment format ever changes again,
add the new form here and both the recovery path and the reconciliation
layer learn it at once.
"""
from __future__ import annotations

import hashlib

PREFIX = "BS_"


def hashed(signal_id) -> str:
    """Exactly what sniper_executor.py:229 writes into the MT5 comment."""
    return PREFIX + hashlib.md5(str(signal_id).encode()).hexdigest()[:8]


def plain(signal_id) -> str:
    """The un-hashed form the bot historically searched for."""
    return f"{PREFIX}{signal_id}"


def forms(signal_id) -> set:
    """Every comment string that legitimately identifies this signal."""
    return {plain(signal_id), hashed(signal_id)}


def matches(comment, signal_id) -> bool:
    """Does this broker comment belong to this signal? Tolerant of the
    broker trimming trailing whitespace, strict about everything else."""
    if not comment or signal_id in (None, ""):
        return False
    return str(comment).strip() in forms(signal_id)


def is_ours(comment) -> bool:
    """Was this position placed by v7 at all? A position without our prefix
    was placed by something else — another system, or by hand — and must
    never be silently adopted or counted as v7's."""
    return str(comment or "").strip().startswith(PREFIX)
