# EVIDENCE — golden fixtures for the ISO-01 patch (patch_iso01_identity.py), keep.
"""Proves the PROPOSED patch, without applying it to the repo file: each test
copies sniper_executor.py to a temp dir, runs patch_iso01_identity.py on the
copy, and drives the patched bridge with a FakeMT5 terminal.

Golden expectation (inverse of test_repro_ISO01_*): a terminal on the wrong
account, or no V7_MT5_LOGIN at all, means 503 on every order route and no
order_send. The right account behaves byte-for-byte as before.

Coverage for the P0 gate (docs/BROTHER_DEVELOPER.md rule 5): unit + failure
injection + regression are here; integration on the box and human approval
are Shyam's (deploy ceremony in patch_iso01_identity.py's docstring).
"""
from __future__ import annotations

import importlib.util
import shutil

import pytest

from conftest import V18_ACCOUNT, V7_ACCOUNT, V7_ROOT, FakeMT5, load_v7_bridge

SIGNAL = {"secret": "s3cret", "symbol": "GOLD", "direction": "BUY",
          "lot": 0.05, "sl": 2390.0, "tp": 2420.0, "signal_id": "SS-BUY-20260904123000"}


def _patch_script():
    spec = importlib.util.spec_from_file_location("patch_iso01_identity", V7_ROOT / "patch_iso01_identity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def patched_copy(tmp_path, capsys):
    """A patched COPY of the repo's sniper_executor.py (repo file untouched)."""
    dst = tmp_path / "sniper_executor.py"
    shutil.copy2(V7_ROOT / "sniper_executor.py", dst)
    before = dst.read_text(encoding="utf-8")
    ps = _patch_script()
    ps.TGT = str(dst)
    ps.main()
    out = capsys.readouterr().out
    assert "OK patched + compiled" in out
    after = dst.read_text(encoding="utf-8")
    assert "V7_MT5_LOGIN" in after and "V7_MT5_LOGIN" not in before
    assert list(tmp_path.glob("sniper_executor.py.bak.*")), "no backup written"
    assert (V7_ROOT / "sniper_executor.py").read_text(encoding="utf-8") == before   # repo file untouched
    return dst


def test_golden_ISO01_wrong_account_refuses_every_order_route(patched_copy, monkeypatch):
    term = FakeMT5(V18_ACCOUNT)                                     # terminal holds v18's account
    ex = load_v7_bridge(term, monkeypatch, path=patched_copy, expected_login=V7_ACCOUNT)
    c = ex.app.test_client()
    assert c.get("/health").status_code == 503
    assert c.post("/execute", json=SIGNAL).status_code == 503
    assert c.post("/close", json={"secret": "s3cret", "ticket": 1}).status_code == 503
    assert c.post("/modify", json={"secret": "s3cret", "ticket": 1, "sl": 1.0}).status_code == 503
    assert term.orders == []


def test_golden_ISO01_missing_env_is_not_runnable_never_a_default(patched_copy, monkeypatch):
    term = FakeMT5(V7_ACCOUNT)                                      # even the RIGHT account
    ex = load_v7_bridge(term, monkeypatch, path=patched_copy, expected_login=None)
    c = ex.app.test_client()
    assert c.get("/health").status_code == 503
    assert c.post("/execute", json=SIGNAL).status_code == 503
    assert term.orders == []


def test_golden_ISO01_right_account_is_byte_identical_on_the_accepted_path(patched_copy, monkeypatch):
    """Regression: same order_send request as the unpatched bridge."""
    unpatched = FakeMT5(V7_ACCOUNT)
    load_v7_bridge(unpatched, monkeypatch).app.test_client().post("/execute", json=SIGNAL)
    patched = FakeMT5(V7_ACCOUNT)
    ex = load_v7_bridge(patched, monkeypatch, path=patched_copy, expected_login=V7_ACCOUNT)
    r = ex.app.test_client().post("/execute", json=SIGNAL)
    assert r.get_json()["status"] == "ok"
    assert ex.app.test_client().get("/health").get_json()["account"] == V7_ACCOUNT
    assert patched.orders == unpatched.orders


def test_golden_ISO01_account_swap_mid_run_is_refused_on_the_next_request(patched_copy, monkeypatch):
    """Failure injection: the terminal re-logs into another account between two requests."""
    term = FakeMT5(V7_ACCOUNT)
    ex = load_v7_bridge(term, monkeypatch, path=patched_copy, expected_login=V7_ACCOUNT)
    c = ex.app.test_client()
    assert c.post("/execute", json=SIGNAL).get_json()["status"] == "ok"
    term.account.login = V18_ACCOUNT
    assert c.post("/execute", json=SIGNAL).status_code == 503
    assert len(term.orders) == 1


def test_golden_patch_script_is_idempotent_and_aborts_on_unknown_anchor(patched_copy, tmp_path, capsys):
    ps = _patch_script()
    ps.TGT = str(patched_copy)
    ps.main()                                                        # second run
    assert "Already patched" in capsys.readouterr().out
    foreign = tmp_path / "other.py"
    foreign.write_text("def ensure_mt5():\n    return True\n", encoding="utf-8")
    ps.TGT = str(foreign)
    with pytest.raises(SystemExit) as e:
        ps.main()
    assert "ABORT" in str(e.value) and foreign.read_text(encoding="utf-8").count("\n") == 2   # untouched
    assert not list(tmp_path.glob("other.py.bak.*"))
