# EVIDENCE — golden fixtures for the ISO-02 deploy script (release gate artefact), keep.
"""patch_iso02_balance_unknown.py applied to the pre-fix tree (main a3640d6) must
produce EXACTLY the repo's ISO-02 fix (commit 4937532), back every file up, be
idempotent, and write nothing when an anchor is not found exactly once.
Run from the repo root:  python3 -m pytest tests/audit/2026-09-05_iso02 -q"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPT = REPO / "patch_iso02_balance_unknown.py"
PRE = HERE / "fixtures" / "prepatch_a3640d6"
RELS = ("core/ic_markets.py", "risk/equity_guard.py", "bot.py")
# The repo files keep moving (f400347 ISO-03, the heartbeat work order); the gate
# artefact is pinned to the ISO-02 commit itself, so expected == the tree at 4937532.
EXPECTED = {
    "bot.py": HERE / "fixtures" / "expected_bot_4937532.py",
    "risk/equity_guard.py": HERE / "fixtures" / "expected_risk_equity_guard_4937532.py",
    "core/ic_markets.py": HERE / "fixtures" / "expected_core_ic_markets_4937532.py",
}


def _stage(tmp_path) -> Path:
    root = tmp_path / "brother_sniper_v7"
    shutil.copytree(PRE, root)
    return root


def _run(root: Path):
    return subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)


def _baks(root: Path):
    return sorted(p for p in root.rglob("*.bak.*"))


def test_golden_ISO02_script_output_is_byte_identical_to_the_repo_fix(tmp_path):
    root = _stage(tmp_path)
    r = _run(root)
    assert r.returncode == 0, r.stdout + r.stderr
    for rel in RELS:
        assert (root / rel).read_text(encoding="utf-8") == EXPECTED[rel].read_text(encoding="utf-8"), rel
    assert len(_baks(root)) == 3 and all(".bak." in p.name for p in _baks(root))
    assert r.stdout.count("OK patched + compiled") == 3


def test_golden_ISO02_script_is_idempotent(tmp_path):
    root = _stage(tmp_path)
    assert _run(root).returncode == 0
    before = {rel: (root / rel).read_bytes() for rel in RELS}
    r = _run(root)
    assert r.returncode == 0 and r.stdout.count("Already patched") == 3 and "Nothing to do" in r.stdout
    assert {rel: (root / rel).read_bytes() for rel in RELS} == before
    assert len(_baks(root)) == 3                      # no second backup


def test_golden_ISO02_unknown_anchor_writes_nothing_anywhere(tmp_path):
    root = _stage(tmp_path)
    bot = root / "bot.py"
    bot.write_text(bot.read_text(encoding="utf-8").replace("except Exception: bal=1000.0", "except Exception: bal=999.0", 1),
                   encoding="utf-8")
    snapshot = {rel: (root / rel).read_bytes() for rel in RELS}
    r = _run(root)
    assert r.returncode != 0 and "ABORT" in (r.stdout + r.stderr) and "Nothing written anywhere" in (r.stdout + r.stderr)
    assert {rel: (root / rel).read_bytes() for rel in RELS} == snapshot   # ic_markets and equity_guard untouched too
    assert _baks(root) == []


def test_golden_ISO02_missing_file_aborts(tmp_path):
    root = _stage(tmp_path)
    (root / "risk" / "equity_guard.py").unlink()
    r = _run(root)
    assert r.returncode != 0 and "not found" in (r.stdout + r.stderr) and _baks(root) == []


def test_golden_ISO02_patched_client_and_guard_behave(tmp_path, monkeypatch):
    """The patched COPY (not the repo file) answers None on a 503 and the patched
    guard blocks on None before touching state — the live-box behaviour."""
    root = _stage(tmp_path)
    assert _run(root).returncode == 0
    monkeypatch.setenv("EXECUTOR_URL", "http://bridge/execute")
    monkeypatch.setenv("ACCOUNT_BALANCE", "6000.0")

    def _load(rel, name):
        spec = importlib.util.spec_from_file_location(name, root / rel)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

    icm = _load("core/ic_markets.py", "iso02_patched_ic_markets")

    class _Resp:
        status_code = 503
        def json(self): return {"status": "error", "msg": "mt5 disconnected"}
    class _Http:
        @staticmethod
        def get(url, timeout=5): return _Resp()
    monkeypatch.setattr(icm, "requests", _Http)
    assert icm.ICMarketsClient().get_balance() is None

    eg = _load("risk/equity_guard.py", "iso02_patched_equity_guard")
    g = eg.EquityGuard()
    peak_before = g.eq.peak_balance
    res = g.check(None, 0)
    assert res.allowed is False and "UNKNOWN" in res.block_reason
    assert g.eq.peak_balance == peak_before
    assert "UNKNOWN" in g.status_summary(None)
