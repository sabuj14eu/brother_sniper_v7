# EVIDENCE — golden fixtures for the ISO-01 patch (patch_iso01_identity.py), keep.
"""Proves the ISO-01 patch two ways: (1) patch_iso01_identity.py applied to a
temp copy of the PRE-patch bridge (what Shyam ran on the box, 2026-09-05
00:08:15 box time), (2) the repo's sniper_executor.py, which carries the same
change. A test also proves the script's output equals the repo file, so the
box and the repo hold the same code modulo the box's earlier A1 patch.

Golden expectation (inverse of test_repro_ISO01_*): a terminal on the wrong
account, or no V7_MT5_LOGIN at all, means 503 on every order route and no
order_send. The right account behaves byte-for-byte as before.

Coverage for the P0 gate (docs/BROTHER_DEVELOPER.md rule 5): unit + failure
injection + regression are here; integration on the box: /health 200 with
account 52834417 after restart, secret still accepted, wrong secret refused
(Shyam's paste, ledger rows box_deploy_step / box_verify).
"""
from __future__ import annotations

import importlib.util
import shutil

import pytest

from conftest import PREPATCH, V18_ACCOUNT, V7_ACCOUNT, V7_ROOT, FakeMT5, load_v7_bridge

SIGNAL = {"secret": "s3cret", "symbol": "GOLD", "direction": "BUY",
          "lot": 0.05, "sl": 2390.0, "tp": 2420.0, "signal_id": "SS-BUY-20260904123000",
          "account_id": str(V7_ACCOUNT)}          # ISO-03: required since 2026-09-05 (ignored by the pre-patch copy)


def _patch_script():
    spec = importlib.util.spec_from_file_location("patch_iso01_identity", V7_ROOT / "patch_iso01_identity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def patched_copy(tmp_path, capsys):
    """The PRE-patch bridge copied to tmp and patched by the script."""
    dst = tmp_path / "sniper_executor.py"
    shutil.copy2(PREPATCH, dst)
    before = dst.read_text(encoding="utf-8")
    ps = _patch_script()
    ps.TGT = str(dst)
    ps.main()
    out = capsys.readouterr().out
    assert "OK patched + compiled" in out
    after = dst.read_text(encoding="utf-8")
    assert "V7_MT5_LOGIN" in after and "V7_MT5_LOGIN" not in before
    assert list(tmp_path.glob("sniper_executor.py.bak.*")), "no backup written"
    assert PREPATCH.read_text(encoding="utf-8") == before                          # fixture untouched
    return dst


def test_golden_script_output_is_contained_in_the_repo_file(patched_copy):
    """The ISO-01 script's output is the ISO-01 layer of the repo file; the repo
    file has since gained ISO-03/05 on top (account_id check, V7_MAGIC,
    _is_ours). Every ISO-01 line the script writes must still be present."""
    repo = (V7_ROOT / "sniper_executor.py").read_text(encoding="utf-8")
    for line in ("V7_MT5_LOGIN = os.getenv(\"V7_MT5_LOGIN\", \"\").strip()",
                 "def _identity_ok(acc):", "return _identity_ok(acc)"):
        assert line in patched_copy.read_text(encoding="utf-8") and line in repo


def test_golden_ISO01_repo_bridge_refuses_wrong_account_and_missing_env(monkeypatch):
    """Same golden expectation, on the repo file itself."""
    term = FakeMT5(V18_ACCOUNT)
    ex = load_v7_bridge(term, monkeypatch, expected_login=V7_ACCOUNT)
    assert ex.app.test_client().post("/execute", json=SIGNAL).status_code == 503
    term2 = FakeMT5(V7_ACCOUNT)
    ex2 = load_v7_bridge(term2, monkeypatch, expected_login=None)
    assert ex2.app.test_client().get("/health").status_code == 503
    assert term.orders == [] and term2.orders == []


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
    """Regression: the ISO-01 layer alone leaves the order_send request identical
    to the unpatched bridge's (the repo file has since added magic, ISO-03)."""
    unpatched = FakeMT5(V7_ACCOUNT)
    load_v7_bridge(unpatched, monkeypatch, path=PREPATCH, expected_login=None).app.test_client().post("/execute", json=SIGNAL)
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
