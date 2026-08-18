"""Tests for mae_recompute.py — exact excursions, and never a guess."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mae_recompute as mr

T0 = 1_000_000


def bar(min_after, low, high):
    return {"t": T0 + min_after * 60, "l": low, "h": high, "c": (low + high) / 2}


BUY = {"signal_id": "S1", "symbol": "GOLD", "direction": "BUY", "entry": 100.0,
       "sl_distance": 10.0, "net_profit": 30.0, "won": True,
       "timestamp_open": T0, "timestamp_close": T0 + 30 * 60,
       "mae": 2.0, "mfe": 4.0}


def test_buy_excursions_are_measured_from_the_true_extremes():
    rows = [bar(5, 94.0, 101.0), bar(10, 99.0, 118.0), bar(20, 98.0, 105.0)]
    got = mr.excursions(BUY, rows)
    assert got["mae_m1"] == 6.0      # entry 100 - lowest low 94
    assert got["mfe_m1"] == 18.0     # highest high 118 - entry
    assert got["mae_r"] == 0.6 and got["mfe_r"] == 1.8   # ÷ sl_distance 10
    assert got["bars"] == 3


def test_sell_excursions_are_mirrored_not_copied():
    sell = {**BUY, "direction": "SELL"}
    rows = [bar(5, 94.0, 101.0), bar(10, 99.0, 118.0)]
    got = mr.excursions(sell, rows)
    assert got["mae_m1"] == 18.0     # price ROSE against a SELL
    assert got["mfe_m1"] == 6.0


def test_bars_outside_the_holding_window_are_excluded():
    """A spike an hour after the close is not this trade's excursion."""
    rows = [bar(10, 99.0, 101.0), bar(120, 50.0, 500.0)]
    got = mr.excursions(BUY, rows)
    assert got["mae_m1"] == 1.0 and got["mfe_m1"] == 1.0


def test_no_candles_in_the_window_returns_nothing_not_a_zero():
    """Silence must leave the sampled value standing alone, not overwrite it
    with a fabricated 0.0 excursion."""
    assert mr.excursions(BUY, [bar(500, 90.0, 110.0)]) is None
    assert mr.excursions(BUY, []) is None


def test_excursions_are_never_negative():
    rows = [bar(5, 101.0, 102.0)]     # price never traded below entry
    got = mr.excursions(BUY, rows)
    assert got["mae_m1"] == 0.0 and got["mfe_m1"] == 2.0


def test_r_values_are_omitted_when_the_stop_distance_is_unknown():
    got = mr.excursions({**BUY, "sl_distance": None}, [bar(5, 94.0, 118.0)])
    assert "mae_r" not in got and got["mae_m1"] == 6.0


# ── selection ────────────────────────────────────────────────────────────────

def test_only_closed_replayable_trades_are_selected():
    rows = [
        BUY,                                                   # ok
        {**BUY, "net_profit": None},                           # still open
        {**BUY, "timestamp_close": None},                      # no close time
        {**BUY, "entry": None},                                # no entry
        {**BUY, "direction": ""},                              # no side
        {**BUY, "timestamp_close": T0 - 60},                   # closes before open
        "not a dict",
    ]
    assert mr.closed_trades(rows) == [BUY]


def test_iso_timestamps_are_accepted_as_well_as_epochs():
    iso = {**BUY, "timestamp_open": "2026-08-18T10:00:00+00:00",
           "timestamp_close": "2026-08-18T10:30:00+00:00"}
    assert mr.closed_trades([iso]) == [iso]


# ── the comparison that justifies the whole job ──────────────────────────────

def test_understatement_measures_what_sampling_missed():
    rows = [{"mae_m1": 6.0, "mae_sampled": 2.0, "mfe_m1": 18.0, "mfe_sampled": 4.0},
            {"mae_m1": 3.0, "mae_sampled": 3.0, "mfe_m1": 5.0, "mfe_sampled": 5.0}]
    u = mr.understatement(rows)
    assert u["n"] == 2 and u["mae_missed_avg"] == 2.0
    assert u["mfe_missed_avg"] == 7.0
    assert u["mae_worse_pct"] == 50.0


def test_understatement_is_empty_when_there_is_nothing_to_compare():
    assert mr.understatement([{"mae_m1": 1.0}])["n"] == 0
    assert mr.understatement([])["n"] == 0


def test_stop_headroom_counts_winners_that_nearly_stopped_out():
    rows = ([{"won": True, "mae_r": 0.9, "mfe_r": 2.0} for _ in range(3)]
            + [{"won": True, "mae_r": 0.2, "mfe_r": 2.0}]
            + [{"won": False, "mae_r": 1.0, "mfe_r": 1.4} for _ in range(2)]
            + [{"won": False, "mae_r": 1.0, "mfe_r": 0.3}])
    h = mr.stop_headroom(rows)
    assert h["winners_n"] == 4 and h["winners_near_stop"] == 3
    assert h["winners_max_mae_r"] == 0.9
    assert h["losers_n"] == 3 and h["losers_reached_1r"] == 2
    assert h["provisional"] is True


def test_headroom_ignores_trades_it_cannot_express_in_r():
    h = mr.stop_headroom([{"won": True}, {"won": False, "mfe_r": None}])
    assert h["winners_n"] == 0 and h["losers_n"] == 0


def test_run_skips_trades_with_no_feed_rather_than_dropping_the_batch():
    trades = [BUY, {**BUY, "signal_id": "S2", "symbol": "NOFEED"}]
    out = mr.run(trades, lambda s: [bar(5, 94.0, 118.0)] if s == "GOLD" else [])
    assert [r["signal_id"] for r in out] == ["S1"]
