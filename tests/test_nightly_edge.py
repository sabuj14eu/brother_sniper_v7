"""Tests for the nightly edge engine's statistics — the part that must be
provably correct, since it decides which setups look profitable."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nightly_edge import (  # noqa: E402
    ev_lower_bound, r_multiple, shrunk_wr, suggested_weight, summarize, MIN_N,
)


# ── shrinkage pulls small samples toward the global mean ─────────────────────

def test_shrinkage_pulls_small_n_toward_global():
    g = 0.50
    # a 3/3 (100%) bucket must NOT read 100% after shrinkage
    s = shrunk_wr(wins=3, n=3, global_wr=g, k=6)
    assert 0.55 < s < 0.75, s          # pulled hard toward 0.50
    # a large well-sampled bucket barely moves
    s_big = shrunk_wr(wins=70, n=100, global_wr=g, k=6)
    assert s_big > 0.66                 # stays near its raw 0.70


def test_shrinkage_identity_at_global():
    # a bucket exactly at the global rate is unchanged
    assert abs(shrunk_wr(50, 100, 0.50, k=6) - 0.50) < 1e-9


# ── lower-bound expectancy is conservative and sample-aware ──────────────────

def test_ev_lower_bound_below_mean():
    rs = [2.0, -1.0, 2.0, -1.0, 2.0, -1.0]   # mean = +0.5R
    mean, lcb, n = ev_lower_bound(rs)
    assert abs(mean - 0.5) < 1e-9
    assert lcb < mean                         # LCB always below the point estimate
    assert n == 6


def test_ev_lower_bound_tightens_with_n():
    # same distribution, 4x the sample -> LCB closer to the mean (less penalty)
    small = ev_lower_bound([2, -1, 2, -1])[1]
    big = ev_lower_bound([2, -1] * 20)[1]
    assert big > small


def test_ev_lower_bound_empty():
    assert ev_lower_bound([]) == (None, None, 0)


# ── R multiple ───────────────────────────────────────────────────────────────

def test_r_multiple():
    assert r_multiple({"net_profit": 30.0, "balance_at_open": 6000.0, "risk_pct": 0.005}) == 1.0
    assert r_multiple({"net_profit": -30.0, "balance_at_open": 6000.0, "risk_pct": 0.005}) == -1.0
    assert r_multiple({"net_profit": 5}) is None          # missing inputs
    assert r_multiple({"net_profit": 5, "balance_at_open": 0, "risk_pct": 0.005}) is None


# ── advisory weight is gated on sample size and clamped ──────────────────────

def test_weight_none_below_min_n():
    assert suggested_weight(0.5, MIN_N - 1) is None


def test_weight_scales_and_clamps():
    assert suggested_weight(0.0, MIN_N) == 1.0            # neutral expectancy -> 1.0
    assert suggested_weight(0.45, MIN_N) == 1.45          # matches the vision's scale
    assert suggested_weight(5.0, MIN_N) == 2.00           # clamped high
    assert suggested_weight(-5.0, MIN_N) == 0.30          # clamped low


# ── summarize end-to-end on a tiny fixture ───────────────────────────────────

def _mk(sym, won_, r_net):
    return {"symbol": sym, "net_profit": r_net, "won": won_,
            "balance_at_open": 6000.0, "risk_pct": 0.005}


def test_summarize_ranks_and_flags():
    trades = ([_mk("SILVER", True, 30) for _ in range(25)] +
              [_mk("SILVER", False, -30) for _ in range(5)] +
              [_mk("GOLD", False, -30) for _ in range(3)])
    global_wr = 25 / 33
    rows = {r["label"]: r for r in summarize(trades, lambda t: t["symbol"], global_wr)}
    assert rows["SILVER"]["n"] == 30 and rows["GOLD"]["n"] == 3
    assert rows["GOLD"]["weight"] is None          # n<MIN_N -> no advisory weight
    assert rows["SILVER"]["weight"] is not None
    # GOLD's shrunk WR is pulled UP off 0% toward global; raw is 0
    assert rows["GOLD"]["wr"] == 0.0 and rows["GOLD"]["swr"] > 0
