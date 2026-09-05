# EVIDENCE — golden fixtures for the ISO-16 fix on the v7 bridge, keep.
"""ISO-16 (P0, ADR-008): one shared stop file refuses every new order on the
v7 bridge; /admin/halt engages it with the same token contract as v18.
Run from the repo root:  python3 -m pytest tests/audit/2026-09-05_iso16 -q"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

JOB3 = Path(__file__).resolve().parents[1] / "2026-09-04_job3"
if str(JOB3) not in sys.path:
    sys.path.insert(0, str(JOB3))
from conftest import V7_ACCOUNT, FakeMT5, load_v7_bridge  # noqa: E402

SIGNAL = {"secret": "s3cret", "symbol": "GOLD", "direction": "BUY", "lot": 0.05, "sl": 2390.0,
          "tp": 2420.0, "signal_id": "SS-BUY-1", "account_id": str(V7_ACCOUNT)}


@pytest.fixture
def stop_file(tmp_path, monkeypatch):
    p = tmp_path / "GLOBAL_STOP"
    monkeypatch.setenv("GLOBAL_STOP_FILE", str(p))
    return p


def test_golden_ISO16_stop_file_present_refuses_every_new_order(stop_file, monkeypatch):
    stop_file.write_text("test\n")
    term = FakeMT5(V7_ACCOUNT)
    ex = load_v7_bridge(term, monkeypatch)
    r = ex.app.test_client().post("/execute", json=SIGNAL)
    assert r.status_code == 503 and r.get_json()["msg"] == "global_stop" and r.get_json()["state"] == "STOP"
    assert term.orders == []
    assert ex.app.test_client().get("/health").get_json()["global_stop"] == "STOP"


def test_golden_ISO16_clear_executes_and_health_says_clear(stop_file, monkeypatch):
    term = FakeMT5(V7_ACCOUNT)
    ex = load_v7_bridge(term, monkeypatch)
    assert ex.app.test_client().post("/execute", json=SIGNAL).get_json()["status"] == "ok"
    assert ex.app.test_client().get("/health").get_json()["global_stop"] == "CLEAR"


def test_golden_ISO16_admin_halt_engages_the_file_then_orders_stop(stop_file, monkeypatch):
    monkeypatch.setenv("ADMIN_HALT_TOKEN", "halt-token-for-tests")
    term = FakeMT5(V7_ACCOUNT)
    ex = load_v7_bridge(term, monkeypatch)
    c = ex.app.test_client()
    assert c.post("/execute", json=SIGNAL).get_json()["status"] == "ok"        # before: trading
    r = c.post("/admin/halt", json={"reason": "test"}, headers={"X-Admin-Token": "halt-token-for-tests"})
    assert r.get_json()["status"] == "halted" and stop_file.exists()
    assert c.post("/execute", json=SIGNAL).status_code == 503                    # after: refused
    assert len(term.orders) == 1
    assert c.get("/admin/status", headers={"X-Admin-Token": "halt-token-for-tests"}).get_json()["global_stop"] == "STOP"


def test_golden_ISO16_admin_token_contract(stop_file, monkeypatch):
    term = FakeMT5(V7_ACCOUNT)
    monkeypatch.delenv("ADMIN_HALT_TOKEN", raising=False)
    ex = load_v7_bridge(term, monkeypatch)
    assert ex.app.test_client().post("/admin/halt", json={}).status_code == 503   # not configured
    monkeypatch.setenv("ADMIN_HALT_TOKEN", "right")
    ex = load_v7_bridge(FakeMT5(V7_ACCOUNT), monkeypatch)
    assert ex.app.test_client().post("/admin/halt", json={}, headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert not stop_file.exists()


def test_golden_ISO16_unreadable_witness_is_a_stop(stop_file, monkeypatch):
    term = FakeMT5(V7_ACCOUNT)
    ex = load_v7_bridge(term, monkeypatch)
    import os
    def boom(p):
        raise PermissionError("denied")
    monkeypatch.setattr(ex.os.path, "exists", boom)
    r = ex.app.test_client().post("/execute", json=SIGNAL)
    assert r.status_code == 503 and r.get_json()["state"] == "UNKNOWN" and term.orders == []


def test_holds_close_is_not_blocked_by_the_global_stop(stop_file, monkeypatch):
    """Closing reduces risk; the stop only refuses NEW orders."""
    from conftest import FakePosition
    stop_file.write_text("test\n")
    term = FakeMT5(V7_ACCOUNT, positions=[FakePosition(777002, "XAUUSD", magic=0, comment="BS_ab12cd34")])
    ex = load_v7_bridge(term, monkeypatch)
    assert ex.app.test_client().post("/close", json={"secret": "s3cret", "ticket": 777002}).get_json()["status"] == "ok"
