"""Tests for core/reconcile.py — labelling v7 vs broker, never repairing it.

The two live cases that prompted the module are pinned by name, because
mislabelling either as an error would send someone to close a healthy
position.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import reconcile as rc

SID = "SS-BUY-1"
COMMENT = "BS_" + hashlib.md5(SID.encode()).hexdigest()[:8]   # what the bridge writes


def pos(**kw):
    base = {"ticket": 1, "symbol": "GOLD", "type": "BUY", "comment": COMMENT,
            "volume": 0.1, "price_open": 100.0}
    return {**base, **kw}


def tracked(**kw):
    base = {"order_id": 1, "symbol": "GOLD", "direction": "BUY",
            "signal_id": SID, "opened_at": "2026-08-18T10:00:00+00:00"}
    return {**base, **kw}


def verdict(**kw):
    base = {"ts": "2026-08-18T12:00:00+00:00", "direction": "BUY",
            "stance": "TRADE", "gate": "PASSED"}
    return {**base, **kw}


# ── the two live cases ───────────────────────────────────────────────────────

def test_us30_a_rejected_signal_does_not_contradict_an_older_position():
    """Verdict REJECT SELL while two SELLs are open. A rejection refuses a
    NEW signal; it never closes an existing trade. Labelling this an error
    would send someone to close healthy positions."""
    out = rc.reconcile_symbol(
        "US30",
        verdict(direction="SELL", stance="REJECT", gate="GATE-RR"),
        tracked(symbol="US30", direction="SELL"),
        [pos(symbol="US30", type="SELL", ticket=1),
         pos(symbol="US30", type="SELL", ticket=2, comment="manual")])
    # one is v7's and tracked, one is not v7's at all — and v7 can hold only
    # ONE position per asset class, so two v7 SELLs is impossible by design
    assert out["label"] == rc.MIXED_OWNERSHIP
    assert out["ours_n"] == 1 and out["foreign_n"] == 1
    assert "at most ONE position per asset class" in out["why"]
    assert rc.UNEXPLAINED not in [p["label"] for p in out["positions"]]


def test_us30_when_every_open_sell_is_v7s_the_reject_is_explained_by_history():
    """The pure form of the same case: v7 tracks the position, the newest
    verdict refuses a new one. That is history, not a contradiction."""
    out = rc.reconcile_symbol(
        "US30", verdict(direction="BUY", stance="REJECT", gate="GATE-RR"),
        tracked(symbol="US30", direction="SELL"),
        [pos(symbol="US30", type="SELL", ticket=1)])
    assert out["label"] == rc.EXPLAINED_BY_HISTORY
    assert "never closes an open one" in out["why"]


def test_silver_a_pending_order_is_provably_not_v7s():
    """v7's bridge sends TRADE_ACTION_DEAL only — it cannot place a pending.
    So a resting SELL LIMIT beside a BUY verdict is not a v7 contradiction."""
    out = rc.reconcile_symbol(
        "SILVER", verdict(direction="BUY", stance="TRADE"), None,
        [pos(symbol="SILVER", type="SELL LIMIT", comment="", ticket=9)])
    assert out["label"] == rc.NOT_PLACED_BY_V7
    assert out["positions"][0]["label"] == rc.NOT_PLACED_BY_V7
    assert "market orders only" in out["positions"][0]["why"]
    assert out["ours_n"] == 0


# ── per-position labels ──────────────────────────────────────────────────────

def test_a_tracked_matching_position_is_consistent():
    out = rc.reconcile_symbol("GOLD", verdict(), tracked(), [pos()])
    assert out["label"] == rc.CONSISTENT and out["ours_n"] == 1


def test_matching_by_hashed_comment_when_the_ticket_is_unknown():
    """The bridge's hashed comment must identify the position even if the
    tracked ticket was never recorded."""
    out = rc.reconcile_symbol("GOLD", verdict(), tracked(order_id=None),
                              [pos(ticket=777)])
    assert out["label"] == rc.CONSISTENT


def test_direction_mismatch_is_flagged_not_fixed():
    out = rc.reconcile_symbol("GOLD", verdict(), tracked(direction="SELL"), [pos()])
    assert out["label"] == rc.DIRECTION_MISMATCH
    assert "verify by hand" in out["positions"][0]["why"]


def test_a_v7_commented_position_nobody_tracks_is_an_orphan():
    out = rc.reconcile_symbol("GOLD", verdict(), None, [pos()])
    assert out["label"] == rc.ORPHAN and out["ours_n"] == 1
    assert "timeout lie" in out["positions"][0]["why"]


def test_a_foreign_comment_is_never_adopted_as_v7s():
    out = rc.reconcile_symbol("GOLD", verdict(), None, [pos(comment="manual scalp")])
    assert out["label"] == rc.NOT_PLACED_BY_V7
    assert out["ours_n"] == 0 and out["foreign_n"] == 1


def test_a_missing_comment_is_unknown_not_declared_foreign():
    out = rc.reconcile_symbol("GOLD", verdict(), None, [pos(comment=None)])
    assert out["positions"][0]["label"] == rc.PROVENANCE_UNKNOWN
    assert out["unknown_n"] == 1 and out["foreign_n"] == 0


def test_numeric_mt5_position_types_are_understood():
    """MT5 reports type as 0/1, not BUY/SELL. Misreading it would invert
    every direction comparison in this module."""
    out = rc.reconcile_symbol("GOLD", verdict(direction="SELL"),
                              tracked(direction="SELL"),
                              [pos(type=1)])          # 1 == SELL in MT5
    assert out["positions"][0]["side"] == "SELL"
    assert out["label"] == rc.CONSISTENT
    flipped = rc.reconcile_symbol("GOLD", verdict(direction="BUY"),
                                  tracked(direction="BUY"), [pos(type=0)])
    assert flipped["positions"][0]["side"] == "BUY"


# ── symbol-level states ──────────────────────────────────────────────────────

def test_tracked_but_absent_at_the_broker_is_a_ghost():
    out = rc.reconcile_symbol("GOLD", verdict(), tracked(), [])
    assert out["label"] == rc.GHOST
    assert "Verify before acting" in out["why"]


def test_nothing_anywhere_is_flat_not_an_anomaly():
    out = rc.reconcile_symbol("GOLD", verdict(stance="WAIT"), None, [])
    assert out["label"] == rc.FLAT


def test_a_contradiction_the_timing_cannot_explain_is_unexplained():
    """An untracked-but-ours position opposing a fresh TRADE verdict, with no
    history to explain it, must reach a human rather than be normalised."""
    out = rc.reconcile_symbol(
        "GOLD", verdict(direction="BUY", stance="TRADE"),
        tracked(direction="BUY", order_id=1),
        [pos(ticket=1, type="SELL")])
    assert out["label"] == rc.DIRECTION_MISMATCH        # tracked -> mismatch wins
    out2 = rc.reconcile_symbol(
        "GOLD", verdict(direction="BUY", stance="TRADE"), None,
        [pos(ticket=5, type="SELL", comment="BS_" +
             hashlib.md5(b"other").hexdigest()[:8])])
    assert out2["label"] == rc.ORPHAN                   # ours, untracked


# ── the whole book ───────────────────────────────────────────────────────────

def test_reconcile_all_covers_every_market_from_either_side():
    verdicts = {"GOLD": verdict(), "EURUSD": verdict(stance="WAIT")}
    slots = {"metals": tracked(), "crypto": None}
    positions = [pos(), pos(symbol="US30", ticket=3, comment="manual")]
    rows = rc.reconcile_all(verdicts, slots, positions)
    assert {r["symbol"] for r in rows} == {"GOLD", "EURUSD", "US30"}


def test_rows_needing_a_human_sort_to_the_top():
    verdicts = {"GOLD": verdict(), "SILVER": verdict()}
    rows = rc.reconcile_all(
        verdicts,
        {"metals": tracked(symbol="SILVER", order_id=99, signal_id="X")},
        [pos(symbol="GOLD")])
    assert rows[0]["symbol"] == "SILVER" and rows[0]["label"] == rc.GHOST
    assert rc.needs_attention(rows) == [rows[0]]


def test_needs_attention_stays_short_enough_to_be_read():
    rows = [{"label": rc.CONSISTENT}, {"label": rc.FLAT},
            {"label": rc.EXPLAINED_BY_HISTORY}, {"label": rc.NOT_PLACED_BY_V7},
            {"label": rc.ORPHAN}, {"label": rc.GHOST}]
    assert rc.needs_attention(rows) == [{"label": rc.GHOST}]


def test_empty_inputs_never_raise():
    assert rc.reconcile_all({}, {}, []) == []
    assert rc.reconcile_all(None, None, None) == []
    assert rc.needs_attention(None) == []
