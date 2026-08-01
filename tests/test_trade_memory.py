"""Round-trip test for the Task-1 journal fix: be_done/partial_done must
survive from close_trade() into the merged trades.jsonl row that scorecard.py
reads. Before the fix these kwargs did not exist and the scorecard counted a
field no producer emitted."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import learning.trade_memory as tm  # noqa: E402


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(tm, "MEMORY_FILE", str(tmp_path / "trades.jsonl"))


def _open_row(sid):
    return tm.TradeRecord(
        signal_id=sid, order_id=1, symbol="GOLD", direction="BUY",
        timestamp_open="2026-08-01T00:00:00+00:00", entry=4300.0, raw_sl=4290.0,
        inst_sl=4288.0, tp=4330.0, sl_distance=12.0, tp_distance=30.0, rr=2.5,
        session="london", utc_hour=9, day_of_week=4, atr=15.0, atr_ratio=0.8,
        fakeout_pad=8.0, sl_method="trust", htf_trend="UP", trend_aligned=True,
        news_minutes=120, pine_score=None, ai_score=60, score_breakdown={},
        balance_at_open=6000.0, equity_pct=100.0, risk_pct=0.005, lot=0.05,
    )


def test_close_row_carries_management_flags(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    tm.open_trade(_open_row("sig-be"))
    tm.close_trade("sig-be", 4325.0, 25.0, -0.5, -0.5,
                   hold_time_seconds=3600, mae=4.0, mfe=28.0,
                   be_done=True, partial_done=False)
    merged = {r["signal_id"]: r for r in tm.load_all()}
    row = merged["sig-be"]
    assert row["be_done"] is True
    assert row["partial_done"] is False
    assert row["mae"] == 4.0 and row["mfe"] == 28.0
    assert row["won"] is True and row["net_profit"] == 24.0


def test_close_without_flags_stays_backward_compatible(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    tm.open_trade(_open_row("sig-old"))
    tm.close_trade("sig-old", 4290.0, -30.0, 0.0, 0.0)
    row = {r["signal_id"]: r for r in tm.load_all()}["sig-old"]
    assert "be_done" not in row or row["be_done"] is None
    assert row["won"] is False
