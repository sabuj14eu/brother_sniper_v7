"""Conditional profile (2026-08-24) — adaptive-gates spec, read-model layer.
Pure functions over synthetic unified rows; gates nothing by construction."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.conditional_profile import (FLOOR, cell_stats, context_of,
                                          profile_verdict, symbol_report)


def _row(symbol="GOLD", side="BUY", htf="UP", session="NY", grade="A",
         dist=0.4, news=None, r=1.0):
    return {"symbol": symbol, "side": side, "htf_align": htf,
            "session": session, "grade": grade, "entry_dist_atr": dist,
            "news_minutes": news, "r": r}


def test_context_honest_unknowns():
    c = context_of({"symbol": "GOLD"})
    assert c["aligned"] == "UNKNOWN" and c["grade"] == "UNKNOWN"
    assert c["dist"] == "UNKNOWN" and c["news"] == "UNKNOWN"
    c2 = context_of(_row(side="SELL", htf="DOWN", dist=4.0, news=15))
    assert c2["aligned"] == "WITH-TREND" and c2["dist"] == ">3"
    assert c2["news"] == "NEWS<30m"


def test_shyams_gold_example_two_conditions_two_verdicts():
    """GOLD overall negative, but NY trend-aligned A-grade near entries
    positive while Asia counter-trend far entries negative — the exact
    §3 example, answered from cells instead of a label."""
    good = [_row(r=0.8) for _ in range(25)]                       # NY aligned A near
    bad = [_row(htf="DOWN", session="ASIA", grade="D", dist=4.0, r=-1.0)
           for _ in range(30)]                                    # counter-trend far
    rows = good + bad
    assert cell_stats(rows)["expectancy_r"] < 0                   # pooled: "GOLD bad"

    v_good = profile_verdict(rows, context_of(_row()))
    assert v_good["verdict"] == "POSITIVE CELL" and v_good["stats"]["n"] == 25
    v_bad = profile_verdict(rows, context_of(
        _row(htf="DOWN", session="ASIA", grade="D", dist=4.0)))
    assert v_bad["verdict"] == "NEGATIVE CELL" and v_bad["stats"]["n"] == 30


def test_thin_cells_back_off_and_say_so():
    rows = [_row(r=0.5) for _ in range(25)]
    # exact ctx differs only in news band -> level-1 backoff answers
    v = profile_verdict(rows, context_of(_row(news=10)))
    assert v["verdict"] == "POSITIVE CELL" and v["level"] == 1
    assert "news" in v["note"]


def test_no_floor_anywhere_is_unknown_never_pretended():
    rows = [_row(r=1.0) for _ in range(3)]                        # n=3
    v = profile_verdict(rows, context_of(_row()))
    assert v["verdict"] == "UNKNOWN" and "do not pretend" in v["note"]
    assert v["stats"]["strength"] == "LUCK-ZONE"


def test_report_cuts_by_every_dimension():
    rows = [_row(r=1.0), _row(session="ASIA", r=-1.0)]
    rep = symbol_report(rows, "gold")
    assert rep["symbol"] == "GOLD"
    assert set(rep["cuts"]) >= {"aligned", "session", "grade", "dist",
                                "news", "side", "aligned x session"}
    assert rep["cuts"]["session"]["NY"]["n"] == 1


def test_r_derived_from_money_when_r_absent():
    row = {"symbol": "GOLD", "net_profit": 50.0, "balance_at_open": 10000.0,
           "risk_pct": 0.005}                                     # risked $50 -> +1R
    assert cell_stats([row])["expectancy_r"] == 1.0
