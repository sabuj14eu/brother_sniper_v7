"""Tests for Strategy DNA classification (Stage 8) + reject telemetry (Stage 3)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.strategy_dna import classify, classify_named, STRATEGIES  # noqa: E402
import learning.telemetry as tm  # noqa: E402


def test_news_reaction_dominates():
    assert classify({"type": "PULLBACK", "news_window": True}) == "S5"
    assert classify({"news_window": "true", "direction": "BUY"}) == "S5"


def test_breakout():
    assert classify({"type": "BREAKOUT"}) == "S3"
    assert classify({"breakout_prob": 72}) == "S3"
    assert classify({"breakout_strength": "Strong"}) == "S3"


def test_pullback():
    assert classify({"type": "PULLBACK"}) == "S2"


def test_mean_reversion_counter_trend_and_fade():
    # counter-trend: SELL while H1 trend is up
    assert classify({"trend": "UP", "direction": "SELL"}) == "S4"
    # fade: SELL in a discount (support) zone
    assert classify({"direction": "SELL", "zone": "DISCOUNT"}) == "S4"
    assert classify({"direction": "BUY", "zone": "PREMIUM"}) == "S4"


def test_trend_continuation():
    assert classify({"trend": "DOWN", "direction": "SELL"}) == "S1"
    assert classify({"htf_trend": "UP", "signal": "BUY"}) == "S1"


def test_unclassified():
    assert classify({}) == "S0"
    assert classify({"symbol": "GOLD"}) == "S0"


def test_named():
    sid, name = classify_named({"type": "PULLBACK"})
    assert sid == "S2" and name == "pullback_sniper"
    assert set(STRATEGIES) >= {"S1", "S2", "S3", "S4", "S5", "S0"}


def test_capture_reject_writes_row(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "TELEMETRY_FILE", str(tmp_path / "t.jsonl"))
    payload = {"signal_id": "r1", "symbol": "XAUUSD", "direction": "BUY",
               "type": "PULLBACK", "grade": "A", "score": 7,
               "zone": "DISCOUNT", "trend": "DOWN"}
    tm.capture_reject(payload, "blocked", "Macro score low; council disagreement")
    line = json.loads((tmp_path / "t.jsonl").read_text().strip())
    assert line["_type"] == "reject"
    assert line["reject_status"] == "blocked"
    assert line["reject_reason"].startswith("Macro")
    assert line["symbol"] == "XAUUSD" and line["strategy_id"] == "S2"
    assert line["grade"] == "A"


def test_capture_reject_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "TELEMETRY_FILE", str(tmp_path / "t.jsonl"))
    tm.capture_reject(None, "rejected", "x")   # bad payload must not raise
