"""Tests for gate_effectiveness.py — measuring gates without judging them.

The whole point is that a frequent gate is not a wrong gate, and that no
verdict may be issued from a training half or a thin sample.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_effectiveness as ge


def cf_row(gate, would_have, r, ts, symbol="GOLD", executed=False):
    return {"gate": gate, "would_have": would_have, "r": r, "ts": ts,
            "symbol": symbol, "executed": executed}


# ── edge math ────────────────────────────────────────────────────────────────

def test_profit_factor_is_gross_win_over_gross_loss():
    assert ge.profit_factor([2.0, 1.0, -1.0, -1.0]) == 1.5


def test_profit_factor_with_no_losses_is_unknown_not_infinite():
    assert ge.profit_factor([1.0, 2.0]) is None
    assert ge.profit_factor([-1.0, -1.0]) is None
    assert ge.profit_factor([]) is None


def test_bucket_stats_reports_wr_expectancy_pf_and_luck_flag():
    s = ge.bucket_stats([2.0, -1.0, -1.0, 2.0])
    assert s["n"] == 4 and s["win_rate"] == 50.0
    assert s["expectancy_r"] == 0.5 and s["pf"] == 2.0
    assert s["avg_win_r"] == 2.0 and s["avg_loss_r"] == -1.0
    assert s["provisional"] is True                     # n<20
    assert ge.bucket_stats([1.0] * 20)["provisional"] is False


def test_no_fill_rows_count_as_neutral_not_as_losses():
    """A gate that blocked signals which would never have filled is neutral,
    not protective — expectancy must not be dragged negative."""
    s = ge.bucket_stats([0.0, 0.0, 0.0])
    assert s["expectancy_r"] == 0.0 and s["win_rate"] == 0.0
    assert s["pf"] is None


# ── the split ────────────────────────────────────────────────────────────────

def test_split_is_by_time_oldest_trains_newest_validates():
    rows = [{"ts": t} for t in (5, 1, 4, 2, 3, 6, 7, 8, 9, 10)]
    train, val = ge.split_train_validate(rows)
    assert [r["ts"] for r in train] == [1, 2, 3, 4, 5, 6, 7]
    assert [r["ts"] for r in val] == [8, 9, 10]


def test_rows_without_a_timestamp_cannot_enter_the_split():
    train, val = ge.split_train_validate([{"ts": None}, {"r": 1.0}])
    assert train == [] and val == []


# ── verdicts ─────────────────────────────────────────────────────────────────

def test_a_gate_that_killed_losers_is_a_good_gate():
    assert ge.verdict(ge.bucket_stats([-1.0] * 25)) == "GOOD GATE"


def test_a_gate_that_killed_winners_is_costly():
    assert ge.verdict(ge.bucket_stats([1.0] * 25)) == "COSTLY GATE"


def test_a_thin_sample_is_unproven_however_extreme():
    """Nineteen straight winners killed is still luck — never a verdict."""
    assert ge.verdict(ge.bucket_stats([3.0] * 19)) == "UNPROVEN"


def test_a_flat_gate_reads_neutral():
    assert ge.verdict(ge.bucket_stats([0.05, -0.05] * 15)) == "NEUTRAL"


# ── the table ────────────────────────────────────────────────────────────────

def test_gate_table_judges_only_the_validate_half():
    """Train half all winners, validate half all losers: the verdict must
    follow VALIDATE (GOOD GATE), not the flattering training data."""
    rows = ([cf_row("GATE-NEWS", "HIT", 2.0, ts) for ts in range(70)]
            + [cf_row("GATE-NEWS", "SL", -1.0, ts) for ts in range(70, 100)])
    t = ge.gate_table(rows)[0]
    assert t["gate"] == "GATE-NEWS" and t["killed"] == 100
    assert t["train"]["expectancy_r"] == 2.0
    assert t["validate"]["expectancy_r"] == -1.0
    assert t["verdict"] == "GOOD GATE"


def test_executed_signals_are_not_in_the_killed_lane():
    rows = [cf_row("PASSED", "HIT", 2.0, 1, executed=True),
            cf_row("GATE-RR", "SL", -1.0, 2)]
    gates = {g["gate"] for g in ge.gate_table(rows)}
    assert gates == {"GATE-RR"}


def test_open_and_unknown_rows_are_counted_but_never_scored():
    rows = ([cf_row("GATE-SLOT", "OPEN", None, i) for i in range(5)]
            + [cf_row("GATE-SLOT", "UNKNOWN", None, i) for i in range(5, 9)]
            + [cf_row("GATE-SLOT", "SL", -1.0, 9)])
    t = ge.gate_table(rows)[0]
    assert t["killed"] == 10 and t["resolved"] == 1
    assert t["open"] == 5 and t["unknown"] == 4
    assert t["verdict"] == "UNPROVEN"


def test_table_is_ordered_by_how_much_each_gate_stopped():
    rows = ([cf_row("GATE-A", "SL", -1.0, i) for i in range(3)]
            + [cf_row("GATE-B", "SL", -1.0, i) for i in range(10)])
    assert [g["gate"] for g in ge.gate_table(rows)] == ["GATE-B", "GATE-A"]


# ── the kept lane ────────────────────────────────────────────────────────────

def _trade(net, bal=6000.0, risk=0.005, **kw):
    return {"net_profit": net, "balance_at_open": bal, "risk_pct": risk, **kw}


def test_kept_lane_uses_the_canonical_v7_r_formula():
    stats = ge.kept_lane([_trade(30.0), _trade(-30.0)])   # +/-1R on 0.5% of 6000
    assert stats["n"] == 2 and stats["expectancy_r"] == 0.0
    assert stats["pf"] == 1.0 and stats["win_rate"] == 50.0


def test_kept_lane_skips_rows_it_cannot_price_rather_than_guessing():
    stats = ge.kept_lane([_trade(30.0), {"net_profit": 10.0},
                          _trade(30.0, risk=0)])
    assert stats["n"] == 1


def test_by_dimension_groups_and_ranks_by_sample():
    rows = ([_trade(30.0, session="london") for _ in range(3)]
            + [_trade(-30.0, session="asian")])
    out = ge.by_dimension(rows, "session")
    assert [b["key"] for b in out] == ["london", "asian"]
    assert out[0]["expectancy_r"] == 1.0 and out[1]["expectancy_r"] == -1.0
    assert all(b["provisional"] for b in out)


def test_missing_dimension_reads_as_a_dash_not_as_a_bucket_name():
    assert ge.by_dimension([_trade(30.0)], "session")[0]["key"] == "—"


# ── io + report ──────────────────────────────────────────────────────────────

def test_load_cf_tolerates_missing_and_corrupt_files(tmp_path):
    assert ge.load_cf(str(tmp_path / "absent.jsonl")) == []
    p = tmp_path / "cf.jsonl"
    p.write_text('{"gate":"G","would_have":"SL","r":-1.0,"ts":1}\n'
                 'not json\n"a string"\n\n')
    assert len(ge.load_cf(str(p))) == 1


def test_report_has_every_panel_the_desk_needs():
    rep = ge.report([cf_row("GATE-RR", "SL", -1.0, 1)], [_trade(30.0)])
    for key in ("kept_lane", "gates", "by_session", "by_symbol", "by_grade",
                "by_strategy", "min_n", "train_ratio"):
        assert key in rep
    assert rep["min_n"] == 20


def test_empty_inputs_produce_an_honest_empty_report():
    rep = ge.report([], [])
    assert rep["gates"] == [] and rep["kept_lane"]["n"] == 0
    assert rep["kept_lane"]["expectancy_r"] is None


# ── cluster labels (the STRONG / WEAK vocabulary the desk shows) ─────────────

def test_a_cluster_is_never_labelled_before_it_has_a_sample():
    """20 straight winners is a sample; 19 is luck, whatever the PF."""
    assert ge.cluster_verdict(ge.bucket_stats([2.0, -1.0] * 9)) == "UNPROVEN"
    assert ge.cluster_verdict(ge.bucket_stats([2.0, -1.0] * 10)) != "UNPROVEN"


def test_strong_needs_both_a_good_pf_and_a_positive_expectancy():
    strong = ge.bucket_stats([1.0] * 14 + [-1.0] * 6)      # PF 2.33, +0.4R
    assert ge.cluster_verdict(strong) == "STRONG"


def test_a_losing_cluster_reads_weak():
    weak = ge.bucket_stats([1.0] * 6 + [-1.0] * 14)        # PF 0.43, -0.4R
    assert ge.cluster_verdict(weak) == "WEAK"


def test_a_break_even_cluster_is_neutral_not_flattered():
    neutral = ge.bucket_stats([1.1] * 10 + [-1.0] * 10)    # PF 1.10, +0.05R
    assert ge.cluster_verdict(neutral) == "NEUTRAL"


def test_a_cluster_with_no_losses_yet_is_unproven_not_infinite():
    assert ge.cluster_verdict(ge.bucket_stats([1.0] * 25)) == "UNPROVEN"


def test_by_dimension_attaches_the_verdict_to_every_bucket():
    rows = [_trade(30.0, session="london") for _ in range(14)] + \
           [_trade(-30.0, session="london") for _ in range(6)] + \
           [_trade(-30.0, session="asian")]
    out = {b["key"]: b for b in ge.by_dimension(rows, "session")}
    assert out["london"]["verdict"] == "STRONG"
    assert out["asian"]["verdict"] == "UNPROVEN"     # n=1
