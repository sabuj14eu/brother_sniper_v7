"""Tests for core/v7_status.py — the v7 status mirror (display-only layer)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import v7_status as vs


# ── gate classification: every real handle_signal return maps correctly ──────

def test_classify_real_messages():
    cases = [
        ("ok", "", "PASSED", "TRADE"),
        ("ignored", "BSv18 grade C below threshold", "GATE-GRADE", "REJECT"),
        ("ignored", "BSv18 v4_rr veto failed", "GATE-V4RR", "REJECT"),
        ("rejected", "GOLD entry price 12 outside expected range - Pine alert likely on wrong chart", "GATE-PRICE", "REJECT"),
        ("rejected", "BUY signal had SL above entry or TP below entry — Pine script bug", "GATE-DIRECTION", "REJECT"),
        ("rejected", "signal carries no SL — auto-SL fabrication removed (F7)", "GATE-SL-MISSING", "REJECT"),
        ("rejected", "trust mode SL distance 9.20% out of range", "GATE-SL-SANITY", "REJECT"),
        ("rejected", "SL floor 8.2 exceeds 1.6x Pine stop 4.1 — R:R collapsed", "GATE-SL-FLOOR", "REJECT"),
        ("rejected", "R:R 0.8 below minimum 1.0", "GATE-RR", "REJECT"),
        ("skipped", "duplicate", "GATE-DEDUP", "WAIT"),
        ("skipped", "GOLD disabled by asset gate", "GATE-ASSET-BENCH", "WAIT"),
        ("skipped", "metals slot already open", "GATE-SLOT", "WAIT"),
        ("skipped", "margin floor / balance unreadable", "GATE-MARGIN", "WAIT"),
        ("paused", "paused — POST /reset", "GATE-PAUSED", "WAIT"),
        ("blocked", "News in 22min: FOMC [USD]", "GATE-NEWS", "WAIT"),
        ("blocked", "EV gate: cluster expectancy -0.61R below floor", "GATE-EV", "WAIT"),
        ("blocked", "Total DD 20pct breached — hard stop", "GATE-EQUITY-GUARD", "WAIT"),
        ("filtered", "score 3.1 below threshold 5", "GATE-AI-FILTER", "WAIT"),
        ("error", "unsupported: FOO", "ERROR", "ERROR"),
    ]
    for status, msg, want_gate, want_stance in cases:
        gate, stance = vs.classify_gate(status, msg)
        assert gate == want_gate, f"{status}/{msg}: got {gate}, want {want_gate}"
        assert stance == want_stance, f"{status}/{msg}: got {stance}"


def test_classify_unknown_is_total():
    gate, stance = vs.classify_gate("weird", None)
    assert gate == "WEIRD" and stance == "ERROR"
    gate, stance = vs.classify_gate(None, None)
    assert gate == "UNKNOWN"


# ── decision records ─────────────────────────────────────────────────────────

_PAYLOAD = {"signal_id": "SS-GOLD-1", "symbol": "GOLD", "direction": "BUY",
            "system": "BSv18", "type": "SMART_SCALP", "grade": "A",
            "score": 8, "entry": "4400.5", "sl": "4392.1", "tp1": "4412.0",
            "atr": 5.4, "session": "london", "pine_ver": "18.12"}


def test_build_decision_executed():
    res = {"status": "ok", "order_id": 123, "lot": 0.05, "signal_id": "SS-GOLD-1",
           "sl": 4390.0, "rr": 1.4, "score": 7.2, "ev": 0.2,
           "cluster": "GOLD|BUY|london|TREND", "regime": "TREND"}
    d = vs.build_decision(_PAYLOAD, res)
    assert d["stance"] == "TRADE" and d["executed"] is True
    assert d["gate"] == "PASSED" and d["order_id"] == 123
    assert d["entry"] == 4400.5 and d["sl"] == 4390.0  # result SL wins
    assert d["cluster"] == "GOLD|BUY|london|TREND"
    assert d["pine_ver"] == "18.12"


def test_build_decision_blocked_keeps_gate_detail():
    res = {"status": "blocked", "msg": "News in 22min: FOMC [USD]"}
    d = vs.build_decision(_PAYLOAD, res)
    assert d["stance"] == "WAIT" and d["gate"] == "GATE-NEWS"
    assert d["gate_detail"] == "News in 22min: FOMC [USD]"
    assert d["executed"] is False and "order_id" not in d
    assert d["symbol"] == "GOLD"


def test_build_decision_never_crashes_on_garbage():
    d = vs.build_decision({"entry": "not-a-number"}, None)
    assert d["kind"] == "v7_decision" and "entry" not in d


# ── heartbeat ────────────────────────────────────────────────────────────────

def test_build_heartbeat_slots_and_guard():
    state = {"paused": False, "consecutive_losses": 1, "total_trades": 10,
             "total_wins": 6, "total_losses": 4,
             "open_trades": {"metals": {"symbol": "SILVER", "order_id": 42,
                                        "direction": "BUY", "entry": 39.1,
                                        "mae": 0.2, "mfe": 0.5},
                             "crypto": None, "forex": None, "other": None}}
    guard = {"hard_stopped": False, "peak_balance": 6749.7,
             "day_pnl": 12.0, "week_pnl": -3.4}
    hb = vs.build_heartbeat(state, guard, bridge_ok=True, balance=6700.0,
                            symbols_enabled={"GOLD", "SILVER"})
    assert hb["open_slots"]["metals"]["ticket"] == 42
    assert hb["open_slots"]["crypto"] is None
    assert hb["paused"] is False and hb["hard_stopped"] is False
    assert hb["bridge_ok"] is True and hb["balance"] == 6700.0
    assert hb["symbols_enabled"] == ["GOLD", "SILVER"]
    assert hb["peak_balance"] == 6749.7


# ── persistence round-trip + never-raise ─────────────────────────────────────

def test_record_and_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "STATUS_FILE", str(tmp_path / "v7_status.json"))
    vs._decisions.clear()
    vs.record_decision(_PAYLOAD, {"status": "skipped", "msg": "duplicate"})
    vs.update_heartbeat({"paused": True, "open_trades": {}}, {})
    data = json.loads((tmp_path / "v7_status.json").read_text())
    assert data["schema"] == vs.SCHEMA_VER
    assert data["decisions"][-1]["gate"] == "GATE-DEDUP"
    assert data["heartbeat"]["paused"] is True
    # heartbeat knows the last decision time
    assert data["heartbeat"]["last_decision_ts"] == data["decisions"][-1]["ts"]

    # restart: a fresh ring re-seeds from the file
    vs._decisions.clear()
    vs._loaded = False
    vs.record_decision(_PAYLOAD, {"status": "paused", "msg": "paused — POST /reset"})
    data = json.loads((tmp_path / "v7_status.json").read_text())
    gates = [d["gate"] for d in data["decisions"]]
    assert gates == ["GATE-DEDUP", "GATE-PAUSED"]


def test_entry_points_never_raise(monkeypatch):
    # unwritable path: both entry points must swallow the failure
    monkeypatch.setattr(vs, "STATUS_FILE", "/nonexistent-dir-xyz/no/v7.json")
    vs.record_decision(_PAYLOAD, {"status": "ok"})
    vs.update_heartbeat({}, {})


def test_push_disabled_by_default(monkeypatch):
    monkeypatch.delenv("V7_MIRROR_ENABLED", raising=False)
    called = []
    monkeypatch.setattr(vs.threading, "Thread",
                        lambda **k: called.append(k) or type("T", (), {"start": lambda s: None})())
    vs._push({"kind": "x"})
    assert called == []  # flag off -> no thread, no network
