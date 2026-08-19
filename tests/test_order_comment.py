"""Regression tests for the MT5 comment mismatch (audit finding, 2026-08-18).

The bot searched for `BS_<signal_id>`; the bridge writes
`BS_ + md5(signal_id)[:8]`. The timeout-recovery path therefore never
adopted its own filled order. These pin both directions of the fix.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import order_comment as oc

SID = "SS-BUY-20260818120000"


def _bridge_writes(signal_id):
    """Byte-for-byte what sniper_executor.py:229 puts in the MT5 comment."""
    return "BS_" + hashlib.md5(str(signal_id).encode()).hexdigest()[:8]


def test_the_bug_the_bridge_comment_is_not_the_plain_form():
    assert _bridge_writes(SID) != oc.plain(SID)      # the mismatch itself


def test_the_fix_the_bridge_comment_now_matches_its_signal():
    assert oc.matches(_bridge_writes(SID), SID)
    assert oc.hashed(SID) == _bridge_writes(SID)


def test_the_historical_plain_form_still_matches():
    """Positions adopted or commented before the bridge hashed must not
    stop matching — this fix may only ADD a recognised form."""
    assert oc.matches(f"BS_{SID}", SID)


def test_a_different_signals_comment_never_matches():
    assert not oc.matches(_bridge_writes("OTHER-SIGNAL"), SID)
    assert not oc.matches("BS_deadbeef", SID)


def test_broker_whitespace_padding_is_tolerated():
    assert oc.matches("  " + _bridge_writes(SID) + " ", SID)


def test_empty_and_missing_values_never_match():
    assert not oc.matches("", SID)
    assert not oc.matches(None, SID)
    assert not oc.matches(_bridge_writes(SID), None)
    assert not oc.matches(_bridge_writes(SID), "")


def test_is_ours_separates_v7_positions_from_everything_else():
    """A manual order or another system's position has no BS_ prefix and
    must never be adopted or counted as v7's."""
    assert oc.is_ours(_bridge_writes(SID))
    assert oc.is_ours("BS_close")
    assert not oc.is_ours("")
    assert not oc.is_ours(None)
    assert not oc.is_ours("manual scalp")
    assert not oc.is_ours("v18-council")


def test_forms_contains_exactly_the_two_recognised_shapes():
    assert oc.forms(SID) == {f"BS_{SID}", _bridge_writes(SID)}
