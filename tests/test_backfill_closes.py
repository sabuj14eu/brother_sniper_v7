"""Tests for backfill_closes.py — recovering BOT-P0-1's 170 outcomes safely.

The dangerous failure modes are all about writing a close that is not true:
closing a live trade, double-closing, or inventing an outcome the broker
never reported. Each is pinned here.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backfill_closes as bf


def open_row(sid, ticket, symbol="GOLD", ts="2026-08-10T10:00:00+00:00"):
    return {"_type": "open", "signal_id": sid, "order_id": ticket,
            "symbol": symbol, "timestamp_open": ts}


def hist(pid, profit=30.0, swap=-0.5, commission=-1.5,
         close_time=1786800000, close_price=101.0):
    return {"position_id": pid, "profit": profit, "swap": swap,
            "commission": commission, "close_time": close_time,
            "close_price": close_price}


# ── selection: who may receive a close row ───────────────────────────────────

def test_a_live_or_tracked_position_never_gets_a_close_row():
    opens = {"A": open_row("A", 1), "B": open_row("B", 2)}
    out = bf.candidates(opens, closed=set(), live_tickets={2})
    assert [r["signal_id"] for r in out] == ["A"]


def test_an_already_closed_signal_is_untouchable():
    opens = {"A": open_row("A", 1)}
    assert bf.candidates(opens, closed={"A"}, live_tickets=set()) == []


def test_an_open_without_a_ticket_cannot_be_matched_so_is_skipped():
    opens = {"A": open_row("A", None), "B": open_row("B", 0)}
    assert bf.candidates(opens, closed=set(), live_tickets=set()) == []


# ── matching: broker truth only ──────────────────────────────────────────────

def test_matching_is_by_position_id_and_requires_a_real_close():
    cands = [open_row("A", 1), open_row("B", 2), open_row("C", 3)]
    history = [hist(1), {"position_id": 2, "close_price": None},  # never closed
               hist(99)]                                          # someone else's
    hits, misses = bf.match(cands, history)
    assert [h[0]["signal_id"] for h in hits] == ["A"]
    assert [m["signal_id"] for m in misses] == ["B", "C"]


def test_unmatched_is_reported_not_invented():
    hits, misses = bf.match([open_row("A", 1)], [])
    assert hits == [] and len(misses) == 1


# ── the record: the journal's own schema, honestly flagged ──────────────────

def test_close_record_matches_the_journal_schema_and_broker_arithmetic():
    rec = bf.close_record(open_row("A", 1), hist(1))
    assert rec["_type"] == "close" and rec["signal_id"] == "A"
    assert rec["gross_profit"] == 30.0 and rec["swap"] == -0.5
    assert rec["net_profit"] == 28.0 and rec["won"] is True   # 30 - 0.5 - 1.5
    assert rec["backfilled"] is True and rec["backfill_source"] == "bridge_history"
    assert rec["broker_ticket"] == 1
    assert rec["timestamp_close"].startswith("2026-")
    assert rec["hold_time_seconds"] > 0
    # the live sampler was not watching: no fabricated excursions
    assert "mae" not in rec and "mfe" not in rec


def test_a_net_loss_is_a_loss_even_when_gross_was_positive():
    rec = bf.close_record(open_row("A", 1), hist(1, profit=1.0, swap=-2.0,
                                                 commission=-1.0))
    assert rec["net_profit"] == -2.0 and rec["won"] is False


def test_missing_close_time_yields_null_not_a_guess():
    rec = bf.close_record(open_row("A", 1), hist(1, close_time=None))
    assert rec["timestamp_close"] is None and "hold_time_seconds" not in rec


# ── journal reading ──────────────────────────────────────────────────────────

def test_load_journal_pairs_opens_with_their_closes(tmp_path):
    import json
    p = tmp_path / "trades.jsonl"
    p.write_text("\n".join([
        json.dumps(open_row("A", 1)),
        json.dumps({"_type": "close", "signal_id": "A", "net_profit": 5}),
        json.dumps(open_row("B", 2)),
        "not json", json.dumps(["not", "a", "dict"]),
    ]) + "\n")
    opens, closed = bf.load_journal(str(p))
    assert set(opens) == {"A", "B"} and closed == {"A"}
    assert bf.load_journal(str(tmp_path / "absent.jsonl")) == ({}, set())
