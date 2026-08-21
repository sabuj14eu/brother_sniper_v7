"""Setup Edge tests.

The one that matters most is test_r_formula_matches_kept_lane: two modules
computing "R" two ways is how a desk ends up showing two different truths for
one trade. That test fails the moment they disagree.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_effectiveness as ge  # noqa: E402
import setup_edge as se  # noqa: E402


def _trade(net, symbol="SILVER", side="BUY", session="LONDON",
           bal=1000.0, risk=0.01, **extra):
    row = {"net_profit": net, "balance_at_open": bal, "risk_pct": risk,
           "symbol": symbol, "side": side, "session": session}
    row.update(extra)
    return row


# ── the anti-drift test ──────────────────────────────────────────────────────

def test_r_formula_matches_kept_lane():
    """setup_edge.row_r must agree with gate_effectiveness.kept_lane, which is
    the canonical realized-R for the whole desk."""
    rows = [_trade(10.0), _trade(-5.0), _trade(20.0, bal=2000.0, risk=0.005),
            _trade(-7.5, bal=500.0, risk=0.02)]
    mine = [se.row_r(r) for r in rows]
    assert None not in mine
    theirs = ge.kept_lane(rows)
    assert theirs["n"] == len(rows)
    assert round(sum(mine) / len(mine), 3) == theirs["expectancy_r"]
    assert round(sum(1 for r in mine if r > 0) / len(mine) * 100, 1) == \
        theirs["win_rate"]


def test_row_r_refuses_impossible_rows():
    assert se.row_r({}) is None
    assert se.row_r(_trade(10.0, bal=0.0)) is None
    assert se.row_r(_trade(10.0, risk=0.0)) is None
    assert se.row_r({"net_profit": None, "balance_at_open": 1, "risk_pct": 1}) is None
    # an open trade has no outcome yet and must not be scored as a zero
    assert se.row_r({"balance_at_open": 1000, "risk_pct": 0.01}) is None


# ── bucketing ────────────────────────────────────────────────────────────────

def test_combines_two_dimensions():
    rows = ([_trade(10.0, side="BUY")] * 5 +
            [_trade(-10.0, side="SELL")] * 5)
    fam = se.by_combo(rows, ("symbol", "side"))
    keys = {r["key"] for r in fam["rows"]}
    assert keys == {"SILVER · BUY", "SILVER · SELL"}
    buy = next(r for r in fam["rows"] if r["parts"]["side"] == "BUY")
    assert buy["n"] == 5 and buy["win_rate"] == 100.0


def test_small_sample_is_never_called_strong():
    """The spec's own example: n=9 at 100% WR is not an edge."""
    rows = [_trade(10.0)] * 9
    fam = se.by_combo(rows, ("symbol", "side"))
    row = fam["rows"][0]
    assert row["n"] == 9 and row["win_rate"] == 100.0
    assert row["verdict"] == "UNPROVEN"
    assert row["provisional"] is True


def test_verdict_requires_min_n():
    winners = [_trade(10.0)] * 25 + [_trade(-5.0)] * 5
    fam = se.by_combo(winners, ("symbol", "side"))
    row = fam["rows"][0]
    assert row["n"] >= ge.MIN_N
    assert row["verdict"] in ("STRONG", "NEUTRAL", "WEAK")


# ── honesty about what is missing ────────────────────────────────────────────

def test_missing_fields_are_uncovered_not_a_bucket():
    """A trade that never recorded `regime` must not become a REGIME bucket."""
    rows = [_trade(10.0, regime=None)] * 4 + [_trade(-5.0, regime="TREND")] * 4
    fam = se.by_combo(rows, ("regime", "side"))
    assert fam["uncovered"] == 4
    assert all(r["parts"]["regime"] == "TREND" for r in fam["rows"])
    assert fam["coverage_pct"] == 50.0


def test_zero_coverage_reports_zero_not_empty_edge():
    rows = [_trade(10.0)] * 10          # no regime recorded at all
    fam = se.by_combo(rows, ("regime", "side"))
    assert fam["coverage_pct"] == 0.0 and fam["rows"] == []
    assert fam["scored"] == 10 and fam["uncovered"] == 10


def test_thin_buckets_are_counted_not_dropped():
    rows = [_trade(10.0, symbol=f"SYM{i}") for i in range(6)]   # n=1 each
    fam = se.by_combo(rows, ("symbol", "side"))
    assert fam["rows"] == []
    assert fam["hidden_thin"] == 6 and fam["hidden_thin_rows"] == 6
    assert fam["scored"] == 6


def test_truncation_is_reported():
    rows = []
    for i in range(45):
        rows += [_trade(10.0, symbol=f"S{i}")] * 3
    fam = se.by_combo(rows, ("symbol", "side"))
    assert len(fam["rows"]) == se.TOP_N
    assert fam["truncated"] == 45 - se.TOP_N


def test_direction_alias_is_read():
    """Older journal rows carry `direction`; telemetry rows carry `side`."""
    row = {"net_profit": 10.0, "balance_at_open": 1000.0, "risk_pct": 0.01,
           "symbol": "GOLD", "direction": "SELL", "session": "ASIA"}
    assert se._val(row, "side") == "SELL"
    fam = se.by_combo([row] * 3, ("symbol", "side"))
    assert fam["rows"][0]["key"] == "GOLD · SELL"


def test_grade_qualifiers_merge_into_one_bucket():
    """Pine sends "A+ strong" and "A+" for the same grade. Bucketed verbatim
    they read as two thin cells; the collection week looked empty for exactly
    this reason while 29 C/D signals had actually fired."""
    for raw, want in [("A+ strong", "A+"), ("A strong", "A"), ("B ok", "B"),
                      ("C ok", "C"), ("D", "D"), ("a+", "A+")]:
        assert se._val({"grade": raw}, "grade") == want


def test_grade_merge_reaches_the_buckets():
    rows = ([_trade(10.0, grade="A+ strong")] * 3 + [_trade(-5.0, grade="A+")] * 3)
    fam = se.by_combo(rows, ("grade", "side"))
    assert [r["key"] for r in fam["rows"]] == ["A+ · BUY"]
    assert fam["rows"][0]["n"] == 6


def test_other_dimensions_are_not_token_split():
    """Only grade is normalised — a two-word session or symbol must survive."""
    assert se._val({"session": "NEW YORK"}, "session") == "NEW YORK"


def test_blank_strings_count_as_missing():
    for blank in ("", "  ", "none", "UNKNOWN", "—"):
        assert se._val({"session": blank}, "session") is None


# ── the whole report ─────────────────────────────────────────────────────────

def test_setup_edge_reports_every_family():
    rows = [_trade(10.0)] * 30 + [_trade(-5.0, side="SELL")] * 30
    rep = se.setup_edge(rows)
    assert {f["name"] for f in rep["families"]} == {f["name"] for f in se.FAMILIES}
    assert rep["min_n"] == ge.MIN_N
    for fam in rep["families"]:
        assert "coverage_pct" in fam and "rows" in fam


def test_empty_journal_does_not_crash():
    rep = se.setup_edge([])
    assert all(f["rows"] == [] and f["scored"] == 0 for f in rep["families"])
