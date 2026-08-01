"""Tests for the log-only telemetry writer + unified feature-store join."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import learning.telemetry as tm  # noqa: E402


def test_blank_row_has_every_field_null():
    row = tm.blank_row()
    for f in ("signal_id", "spread", "fill_price", "slippage", "broker_latency",
              "setup_type", "zone", "ai_score", "signal_time"):
        assert f in row and row[f] is None


def test_build_open_row_fills_known_ignores_unknown():
    row = tm.build_open_row(signal_id="s1", symbol="GOLD", side="SELL",
                            ai_score=61, totally_unknown_field="x")
    assert row["signal_id"] == "s1" and row["symbol"] == "GOLD"
    assert row["ai_score"] == 61
    assert "totally_unknown_field" not in row       # extras ignored, never crash
    assert row["_type"] == "telemetry_open"


def test_spread_derived_from_bid_ask():
    row = tm.build_open_row(signal_id="s2", bid=1.10000, ask=1.10020)
    assert abs(row["spread"] - 0.0002) < 1e-9


def test_spread_not_overwritten_if_given():
    row = tm.build_open_row(signal_id="s3", bid=1.0, ask=2.0, spread=0.5)
    assert row["spread"] == 0.5


def test_write_and_capture_never_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "TELEMETRY_FILE", str(tmp_path / "telemetry.jsonl"))
    tm.capture_open(signal_id="s4", symbol="SILVER", requested_price=57.5)
    # a broken row must not raise either
    tm.write_row({"signal_id": "s5", "bad": object()})
    lines = (tmp_path / "telemetry.jsonl").read_text().strip().splitlines()
    assert len(lines) >= 1
    assert json.loads(lines[0])["signal_id"] == "s4"


def test_load_unified_joins_by_signal_id(tmp_path, monkeypatch):
    tfile = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(tm, "TELEMETRY_FILE", str(tfile))
    tm.capture_open(signal_id="j1", symbol="GOLD", side="SELL",
                    requested_price=4300.0, ai_score=61)
    trades = [
        {"signal_id": "j1", "won": False, "net_profit": -30.0, "mae": 8.0,
         "mfe": 4.0, "symbol": "GOLD", "direction": "SELL"},
        {"signal_id": "j2", "won": True, "net_profit": 20.0},   # outcome, no telemetry
    ]
    rows = {r["signal_id"]: r for r in tm.load_unified(str(tfile), trades)}
    assert len(rows) == 2                              # one row per trade, no dup
    j1 = rows["j1"]
    assert j1["requested_price"] == 4300.0             # telemetry facts present
    assert j1["ai_score"] == 61
    assert j1["won"] is False and j1["net_profit"] == -30.0 and j1["mae"] == 8.0
    j2 = rows["j2"]
    assert j2["won"] is True                           # outcome-only row still appears
    assert j2.get("requested_price") is None
