# EVIDENCE — ISO-06 proposal, golden fixtures on the PROPOSED copy (never the live file), keep.
"""Run from the repo root:  python3 -m pytest tests/audit/2026-09-05_iso06 -q"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOB3 = HERE.parent / "2026-09-04_job3"
for p in (str(JOB3), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)
from conftest import V7_ACCOUNT, FakeMT5, FakeResult, load_v7_bridge  # noqa: E402
import proposal_hunks  # noqa: E402

PROPOSED = HERE / "fixtures" / "proposed_sniper_executor_iso06.py"
LIVE = HERE.parents[2] / "sniper_executor.py"


def _sig(sid="SS-BUY-20260905120000", **extra):
    d = {"secret": "s3cret", "symbol": "GOLD", "direction": "BUY", "lot": 0.05, "sl": 2390.0,
         "tp": 2420.0, "signal_id": sid, "account_id": str(V7_ACCOUNT)}
    d.update(extra)
    return d


def _bridge(tmp_path, monkeypatch, term=None):
    monkeypatch.setenv("V7_SEEN_FILE", str(tmp_path / "v7_seen_signals.json"))
    term = term or FakeMT5(V7_ACCOUNT)
    return term, load_v7_bridge(term, monkeypatch, path=PROPOSED)


def test_proposal_applies_cleanly_to_the_current_source():
    assert proposal_hunks.apply(LIVE.read_text(encoding="utf-8")) == PROPOSED.read_text(encoding="utf-8")
    assert "_seen_check_and_mark" not in LIVE.read_text(encoding="utf-8")     # NOT applied


def test_golden_ISO06_same_signal_twice_is_one_fill(tmp_path, monkeypatch):
    term, ex = _bridge(tmp_path, monkeypatch)
    c = ex.app.test_client()
    assert c.post("/execute", json=_sig()).get_json()["status"] == "ok"
    r = c.post("/execute", json=_sig())
    assert r.status_code == 409 and r.get_json()["msg"] == "duplicate_signal"
    assert r.get_json()["first"]["state"] == "filled" and r.get_json()["first"]["ticket"] == 900001
    assert len(term.orders) == 1


def test_golden_ISO06_different_ids_are_two_fills(tmp_path, monkeypatch):
    term, ex = _bridge(tmp_path, monkeypatch)
    c = ex.app.test_client()
    assert c.post("/execute", json=_sig("SS-1")).get_json()["status"] == "ok"
    assert c.post("/execute", json=_sig("SS-2")).get_json()["status"] == "ok"
    assert len(term.orders) == 2


def test_golden_ISO06_key_carries_the_account(tmp_path, monkeypatch):
    _, ex = _bridge(tmp_path, monkeypatch)
    assert ex._seen_check_and_mark("52834417", "SS-1") == (True, None)
    assert ex._seen_check_and_mark("52901228", "SS-1") == (True, None)      # same Pine id, other arm: not a duplicate
    assert ex._seen_check_and_mark("52834417", "SS-1")[0] is False


def test_golden_ISO06_broker_rejection_frees_the_id(tmp_path, monkeypatch):
    term, ex = _bridge(tmp_path, monkeypatch)
    real = term.order_send
    def reject(req):
        term.orders.append(dict(req)); return FakeResult(order=0, volume=0.0, retcode=10019)   # NO_MONEY
    term.order_send = reject
    c = ex.app.test_client()
    assert c.post("/execute", json=_sig()).get_json()["status"] == "error"
    term.order_send = real
    assert c.post("/execute", json=_sig()).get_json()["status"] == "ok"      # legitimate retry
    assert len(term.orders) == 2


def test_golden_ISO06_ambiguous_none_result_keeps_the_id(tmp_path, monkeypatch):
    term, ex = _bridge(tmp_path, monkeypatch)
    term.order_send = lambda req: None
    c = ex.app.test_client()
    assert c.post("/execute", json=_sig()).status_code == 502
    r = c.post("/execute", json=_sig())
    assert r.status_code == 409 and r.get_json()["first"]["state"] == "ambiguous"


def test_golden_ISO06_missing_signal_id_is_refused(tmp_path, monkeypatch):
    term, ex = _bridge(tmp_path, monkeypatch)
    d = _sig(); del d["signal_id"]
    r = ex.app.test_client().post("/execute", json=d)
    assert r.status_code == 400 and r.get_json()["msg"] == "no_signal_id" and term.orders == []


def test_golden_ISO06_unreadable_store_is_unknown_and_refuses(tmp_path, monkeypatch):
    bad = tmp_path / "v7_seen_signals.json"; bad.write_text("{not json")
    term, ex = _bridge(tmp_path, monkeypatch)
    r = ex.app.test_client().post("/execute", json=_sig())
    assert r.status_code == 503 and r.get_json()["msg"] == "seen_store_unknown" and term.orders == []


def test_golden_ISO06_mark_survives_a_restart(tmp_path, monkeypatch):
    term, ex = _bridge(tmp_path, monkeypatch)
    assert ex.app.test_client().post("/execute", json=_sig()).get_json()["status"] == "ok"
    term2, ex2 = _bridge(tmp_path, monkeypatch)                              # fresh module, same store file
    assert ex2.app.test_client().post("/execute", json=_sig()).status_code == 409 and term2.orders == []


def test_golden_ISO06_ttl_expiry_frees_the_id(tmp_path, monkeypatch):
    term, ex = _bridge(tmp_path, monkeypatch)
    c = ex.app.test_client()
    assert c.post("/execute", json=_sig()).get_json()["status"] == "ok"
    now = ex.time.time()
    monkeypatch.setattr(ex.time, "time", lambda: now + ex._SEEN_TTL_S + 1)
    assert c.post("/execute", json=_sig()).get_json()["status"] == "ok" and len(term.orders) == 2


def test_holds_accepted_path_request_is_byte_identical(tmp_path, monkeypatch):
    term, ex = _bridge(tmp_path, monkeypatch)
    ex.app.test_client().post("/execute", json=_sig())
    live_term = FakeMT5(V7_ACCOUNT)
    live = load_v7_bridge(live_term, monkeypatch)
    live.app.test_client().post("/execute", json=_sig())
    assert term.orders[0] == live_term.orders[0]
