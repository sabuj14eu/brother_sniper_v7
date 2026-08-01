"""First tests for brother_sniper_v7 (08-01 hygiene sweep).

Covers the standalone-importable modules: sl_engine, ai_filter (incl. the F8
dial), equity_guard, asset_gate, and the two study scripts' pure functions.
bot.py itself is NOT importable from a clean clone — it imports learning/*.py
modules that are gitignored (documented in the audit; needs the code files
committed from the box).

Run from repo root:  python3 -m pytest tests/ -q
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.sl_engine import calculate_institutional_sl, validate_rr  # noqa: E402
from filters.ai_filter import score_signal, _get_session  # noqa: E402
from risk.equity_guard import EquityGuard  # noqa: E402
from utils.asset_gate import asset_gate_check  # noqa: E402
from mae_study import replay_at_stop, task1_evidence  # noqa: E402
from shadow_eye_score import score as eye_score, _r_multiple  # noqa: E402


# ── sl_engine ────────────────────────────────────────────────────────────────

def test_validate_rr_pass_and_floor():
    rr, err = validate_rr(100.0, 99.0, 103.0, "BUY", 1.0)
    assert rr == 3.0 and err == ""
    rr, err = validate_rr(100.0, 99.0, 100.5, "BUY", 1.0)
    assert err and "below minimum" in err


def test_validate_rr_tp_wrong_side():
    _, err = validate_rr(100.0, 99.0, 98.0, "BUY", 0.1)
    assert "must be above entry" in err
    _, err = validate_rr(100.0, 101.0, 102.0, "SELL", 0.1)
    assert "must be below entry" in err


def test_sl_engine_buy_below_entry():
    r = calculate_institutional_sl("GOLD", "BUY", 4300.0, 4290.0, atr=30.0)
    assert r.sl_price < 4300.0
    assert r.sl_distance > 0


def test_sl_engine_max_dist_rejects():
    # absurdly wide raw SL -> beyond MAX_SL_PCT -> flagged not-within-limits
    r = calculate_institutional_sl("GOLD", "BUY", 4300.0, 3000.0, atr=30.0)
    assert not r.within_limits and r.rejection_reason


# ── ai_filter + F8 dial ──────────────────────────────────────────────────────

def _score_counter_trend():
    # BUY against DOWN htf trend = confirmed counter-trend, decent RR
    return score_signal(symbol="GOLD", direction="BUY", entry=4300.0,
                        sl_price=4285.0, tp=4345.0, htf_trend="DOWN",
                        news_minutes=999, atr=15.0)


def test_f8_dial_off_by_default(monkeypatch):
    monkeypatch.delenv("F8_CT_50", raising=False)
    res = _score_counter_trend()
    assert "counter_trend_penalty" in res.breakdown
    assert "0.65" in res.breakdown["counter_trend_penalty"]["detail"]


def test_f8_dial_on(monkeypatch):
    monkeypatch.setenv("F8_CT_50", "true")
    res_on = _score_counter_trend()
    assert "0.5" in res_on.breakdown["counter_trend_penalty"]["detail"]
    monkeypatch.setenv("F8_CT_50", "false")
    res_off = _score_counter_trend()
    assert res_on.score <= res_off.score


def test_aligned_trade_no_penalty():
    res = score_signal(symbol="GOLD", direction="BUY", entry=4300.0,
                       sl_price=4285.0, tp=4345.0, htf_trend="UP",
                       news_minutes=999, atr=15.0)
    assert "counter_trend_penalty" not in res.breakdown


def test_session_returns_known_value():
    assert _get_session() in ("overlap", "london", "new_york", "asian", "dead")


# ── equity_guard ─────────────────────────────────────────────────────────────

def test_equity_guard_streak_blocks():
    g = EquityGuard()
    g.update_balance(1000.0)
    res = g.check(1000.0, consecutive_losses=3)
    assert not res.allowed and res.tier_hit == "streak"


def test_equity_guard_allows_normal():
    g = EquityGuard()
    g.update_balance(1000.0)
    res = g.check(1000.0, consecutive_losses=0)
    assert res.allowed and res.risk_pct > 0


# ── asset gate (off by default = inert) ──────────────────────────────────────

def test_asset_gate_default_inert(monkeypatch):
    monkeypatch.delenv("ASSET_GATE_ENABLED", raising=False)
    monkeypatch.setenv("ASSET_GATE_DISABLE", "GOLD")
    monkeypatch.setenv("ASSET_GATE_SIZE", "GOLD:0.5")
    assert asset_gate_check("GOLD") == (False, 1.0)


def test_asset_gate_bench(monkeypatch):
    monkeypatch.setenv("ASSET_GATE_ENABLED", "true")
    monkeypatch.setenv("ASSET_GATE_DISABLE", "GOLD")
    monkeypatch.setenv("ASSET_GATE_SIZE", "")
    blocked, mult = asset_gate_check("GOLD")
    assert blocked
    assert asset_gate_check("SILVER") == (False, 1.0)


def test_asset_gate_size_down_and_clamp(monkeypatch):
    monkeypatch.setenv("ASSET_GATE_ENABLED", "true")
    monkeypatch.setenv("ASSET_GATE_DISABLE", "")
    monkeypatch.setenv("ASSET_GATE_SIZE", "GOLD:0.5,SILVER:2.0,BAD:x")
    assert asset_gate_check("GOLD") == (False, 0.5)
    # Iron Rule 7: multiplier can never RAISE size — 2.0 clamps to 1.0
    assert asset_gate_check("SILVER") == (False, 1.0)
    assert asset_gate_check("BAD") == (False, 1.0)


# ── mae_study pure functions ─────────────────────────────────────────────────

def test_replay_at_stop_survived_tp():
    t = {"atr": 10.0, "mae": 8.0, "mfe": 30.0, "tp_distance": 25.0}
    r = replay_at_stop(t, 1.0)  # stop=10 > mae=8 -> survived; mfe>=tp -> win
    assert r["survived"] and r["hit_tp"] and r["r"] == 2.5


def test_replay_at_stop_stopped_out():
    t = {"atr": 10.0, "mae": 12.0, "mfe": 30.0, "tp_distance": 25.0}
    r = replay_at_stop(t, 1.0)
    assert not r["survived"] and r["r"] == -1.0


def test_replay_at_stop_missing_data():
    assert replay_at_stop({"atr": 10.0, "mae": None, "mfe": 1, "tp_distance": 5}, 1.0) is None


def test_task1_evidence_flags_1r_reachers():
    done = [
        {"signal_id": "a", "symbol": "GOLD", "direction": "BUY",
         "sl_distance": 10.0, "mfe": 12.0, "net_profit": -5},
        {"signal_id": "b", "symbol": "GOLD", "direction": "BUY",
         "sl_distance": 10.0, "mfe": 4.0, "net_profit": 5},
    ]
    ev = task1_evidence(done)
    assert len(ev) == 1 and ev[0]["signal_id"] == "a" and ev[0]["mfe_R"] == 1.2


# ── shadow_eye_score pure functions ──────────────────────────────────────────

def test_r_multiple():
    t = {"net_profit": 30.0, "balance_at_open": 6000.0, "risk_pct": 0.005}
    assert _r_multiple(t) == 1.0
    assert _r_multiple({"net_profit": 1}) is None


def test_eye_score_joins_by_signal_id():
    votes = [
        {"model": "deepseek", "signal_id": "s1", "take": True, "confidence": 70},
        {"model": "deepseek", "signal_id": "s2", "take": True, "confidence": 50},
        {"model": "gemini", "signal_id": "s1", "take": False, "confidence": 80},
        {"model": "gemini", "signal_id": "missing", "take": True},
    ]
    trades = {
        "s1": {"won": True, "net_profit": 30.0, "balance_at_open": 6000.0, "risk_pct": 0.005},
        "s2": {"won": False, "net_profit": -30.0, "balance_at_open": 6000.0, "risk_pct": 0.005},
    }
    res = eye_score(votes, trades)
    ds = res[("deepseek", "TAKE")]
    assert ds["votes"] == 2 and ds["joined"] == 2 and ds["wins"] == 1
    assert ds["conf_hi_joined"] == 1 and ds["conf_hi_wins"] == 1
    gm = res[("gemini", "BLOCK")]
    assert gm["joined"] == 1 and gm["wins"] == 1
    assert res[("gemini", "TAKE")]["joined"] == 0
