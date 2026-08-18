"""Tests for v7_counterfactual.py — the replay that judges v7's gates.

These pin the honesty rules. If a future change makes rejected signals look
better than they were, one of these must break first.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import v7_counterfactual as cf

TS = 1_000_000  # signal time, epoch seconds
H = 3600


def bar(hours_after, low, high, close=None):
    return {"t": TS + int(hours_after * H), "l": low, "h": high,
            "c": close if close is not None else (low + high) / 2}


BUY = {"signal_id": "S1", "ts": TS, "symbol": "GOLD", "side": "BUY",
       "entry": 100.0, "sl": 90.0, "tp": 120.0, "gate": "GATE-NEWS"}
SELL = {**BUY, "signal_id": "S2", "side": "SELL", "entry": 100.0,
        "sl": 110.0, "tp": 80.0}


# ── the four honesty rules ───────────────────────────────────────────────────

def test_no_lookahead_bars_before_the_signal_are_invisible():
    """A bar that already hit TP BEFORE the signal must not create a win."""
    before = [{"t": TS - H, "l": 99.0, "h": 130.0, "c": 125.0}]
    r = cf.replay(BUY, before)
    assert r["would_have"] == "UNKNOWN"
    assert "no candles after" in r["why"]


def test_entry_never_touched_is_no_fill_not_a_loss():
    rows = [bar(i, 101.0, 105.0) for i in range(1, 14)]   # never trades down to 100
    r = cf.replay(BUY, rows)
    assert r["would_have"] == "NO_FILL" and r["r"] == 0.0
    assert "does not fill is not a trade" in r["why"]


def test_same_bar_tp_and_sl_resolves_to_sl():
    rows = [bar(1, 89.0, 121.0)]      # touches entry, SL and TP in one bar
    r = cf.replay(BUY, rows)
    assert r["would_have"] == "SL" and r["r"] == -1.0
    assert "same-bar ties resolve to SL" in r["why"]


def test_unresolved_after_the_window_is_open_never_a_win():
    rows = [bar(1, 99.0, 101.0)] + [bar(i, 99.5, 101.0) for i in range(2, 60)]
    r = cf.replay(BUY, rows)
    assert r["would_have"] == "OPEN" and r["r"] is None


# ── outcomes and R ───────────────────────────────────────────────────────────

def test_buy_hit_pays_its_own_rr_not_a_flat_number():
    rows = [bar(1, 99.0, 101.0), bar(2, 100.0, 121.0)]
    r = cf.replay(BUY, rows)
    assert r["would_have"] == "HIT"
    assert r["r"] == 2.0          # (120-100)/(100-90) — measured on its own risk
    assert r["rr"] == 2.0


def test_a_wider_stop_does_not_flatter_the_signal():
    wide = {**BUY, "sl": 80.0}     # same TP, double the risk
    rows = [bar(1, 99.0, 101.0), bar(2, 100.0, 121.0)]
    assert cf.replay(wide, rows)["r"] == 1.0     # not 2.0


def test_sell_side_is_mirrored_correctly():
    rows = [bar(1, 99.0, 101.0), bar(2, 79.0, 100.0)]
    r = cf.replay(SELL, rows)
    assert r["would_have"] == "HIT" and r["r"] == 2.0
    rows_sl = [bar(1, 99.0, 101.0), bar(2, 100.0, 111.0)]
    assert cf.replay(SELL, rows_sl)["would_have"] == "SL"


def test_inconsistent_geometry_is_unknown_never_reconstructed():
    broken = {**BUY, "sl": 130.0}          # SL above entry on a BUY
    r = cf.replay(broken, [bar(1, 99.0, 121.0)])
    assert r["would_have"] == "UNKNOWN" and "inconsistent" in r["why"]


def test_a_still_young_signal_is_open_not_no_fill():
    """Two hours of candles cannot prove a 12h limit failed to fill."""
    rows = [bar(1, 101.0, 105.0), bar(2, 101.0, 105.0)]
    r = cf.replay(BUY, rows)
    assert r["would_have"] == "OPEN" and "still inside" in r["why"]


def test_missing_feed_yields_unknown_not_an_invented_outcome():
    assert cf.replay(BUY, [])["would_have"] == "UNKNOWN"


# ── inputs ───────────────────────────────────────────────────────────────────

def test_load_verdicts_reads_journal_and_backfills_memory(tmp_path):
    journal = tmp_path / "decisions.jsonl"
    journal.write_text("\n".join(json.dumps(r) for r in [
        {"ts": "2026-08-18T10:00:00+00:00", "symbol": "GOLD", "direction": "BUY",
         "entry": 100, "sl": 90, "tp": 120, "gate": "GATE-SLOT", "signal_id": "A"},
        {"ts": "2026-08-18T11:00:00+00:00", "symbol": "SILVER", "direction": "SELL",
         "entry": 30, "sl": 31, "tp": 28, "gate": "PASSED", "signal_id": "B",
         "executed": True},
        {"ts": "2026-08-18T12:00:00+00:00", "symbol": "GOLD"},  # no levels -> skipped
        "" if False else json.dumps({"bad": "row"}),
    ]) + "\n")
    memory = tmp_path / "signal_memory.json"
    memory.write_text(json.dumps({"US30": [
        {"ts": "2026-08-17T09:00:00+00:00", "category": "TRADE_BUY",
         "entry": 50000, "sl": 49900, "tp": 50300, "session": "london"},
        {"ts": "2026-08-17T10:00:00+00:00", "category": "BIAS_BULL",   # not a trade
         "entry": 50000, "sl": 49900, "tp": 50300},
    ]}))
    got = cf.load_verdicts(str(journal), str(memory))
    assert [v["gate"] for v in got] == ["UNKNOWN", "GATE-SLOT", "PASSED"]
    assert [v["source"] for v in got] == ["signal_memory", "journal", "journal"]
    assert got[0]["symbol"] == "US30" and got[0]["side"] == "BUY"
    assert got[2]["executed"] is True
    assert all(v["ts"] for v in got)                      # sorted oldest first
    assert got[0]["ts"] < got[1]["ts"] < got[2]["ts"]


def test_missing_input_files_are_empty_not_an_error(tmp_path):
    assert cf.load_verdicts(str(tmp_path / "none.jsonl"),
                            str(tmp_path / "none.json")) == []


def test_candle_cache_fetches_once_per_symbol_and_tries_aliases():
    calls = []

    def fake(sym, tf=cf.TF, n=cf.MAX_BARS):
        calls.append(sym)
        return [bar(1, 99, 101)] if sym == "XAUUSD" else []

    get = cf.make_candle_cache(fake)
    assert get("GOLD") and get("GOLD")        # second call served from cache
    assert calls == ["XAUUSD"]                # alias resolved, fetched once
    assert get("NOPE") == []


# ── summary ──────────────────────────────────────────────────────────────────

def test_summary_keeps_open_and_unknown_out_of_the_denominator():
    results = [{"would_have": "HIT", "r": 2.0}, {"would_have": "SL", "r": -1.0},
               {"would_have": "NO_FILL", "r": 0.0}, {"would_have": "OPEN", "r": None},
               {"would_have": "UNKNOWN", "r": None}]
    s = cf.summarize(results)
    assert s["n_total"] == 5 and s["n_resolved"] == 3
    assert s["n_open"] == 1 and s["n_unknown"] == 1
    assert s["win_rate"] == round(1 / 3 * 100, 1)
    assert s["expectancy_r"] == round((2.0 - 1.0 + 0.0) / 3, 3)
    assert s["provisional"] is True                     # n<20 is luck


def test_summary_drops_provisional_flag_at_twenty():
    results = [{"would_have": "HIT", "r": 1.0} for _ in range(20)]
    assert cf.summarize(results)["provisional"] is False


def test_run_maps_every_verdict():
    verdicts = [BUY, {**SELL, "symbol": "SILVER"}]
    out = cf.run(verdicts, lambda sym: [bar(1, 99.0, 121.0)])
    assert len(out) == 2 and out[0]["symbol"] == "GOLD"
