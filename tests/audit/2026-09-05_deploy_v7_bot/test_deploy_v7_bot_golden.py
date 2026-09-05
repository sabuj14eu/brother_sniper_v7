# EVIDENCE — golden fixtures for the v7 BOT deploy script (ISO-03 + ISO-24 + heartbeat), keep.
"""patch_v7_bot_iso03_24_heartbeat.py applied to the ISO-02-patched bot tree must produce EXACTLY the
repo's bot.py, core/ic_markets.py, core/v7_status.py, filters/ai_filter.py at 0d1a2a5; back each up;
be idempotent; write nothing anywhere on an ambiguous anchor.
Run from the repo root:  python3 -m pytest tests/audit/2026-09-05_deploy_v7_bot -q"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPT = REPO / "patch_v7_bot_iso03_24_heartbeat.py"
PRE, EXP = HERE / "fixtures" / "prepatch", HERE / "fixtures" / "expected"
RELS = ("core/ic_markets.py", "core/v7_status.py", "filters/ai_filter.py", "bot.py")


def _stage(tmp_path):
    root = tmp_path / "brother_sniper_v7"; shutil.copytree(PRE, root); return root


def _run(root):
    return subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)


def test_golden_output_is_byte_identical_to_the_repo_tree(tmp_path):
    root = _stage(tmp_path); r = _run(root)
    assert r.returncode == 0, r.stdout + r.stderr
    for rel in RELS:
        assert (root / rel).read_text(encoding="utf-8") == (EXP / rel).read_text(encoding="utf-8"), rel
    assert len(list(root.rglob("*.bak.*"))) == 4 and r.stdout.count("OK patched + compiled") == 4


def test_golden_idempotent_and_abort_writes_nothing_anywhere(tmp_path):
    root = _stage(tmp_path); assert _run(root).returncode == 0
    r = _run(root); assert r.returncode == 0 and r.stdout.count("Already patched") == 4 and len(list(root.rglob("*.bak.*"))) == 4
    root2 = _stage(tmp_path / "b"); f = root2 / "bot.py"
    f.write_text(f.read_text(encoding="utf-8").replace("update_heartbeat(state, equity_guard.to_dict()", "update_heartbeat(state, equity_guard.to_dict( )", 1), encoding="utf-8")
    snap = {rel: (root2 / rel).read_bytes() for rel in RELS}; r = _run(root2)
    assert r.returncode != 0 and "Nothing written anywhere" in (r.stdout + r.stderr)
    assert {rel: (root2 / rel).read_bytes() for rel in RELS} == snap and not list(root2.rglob("*.bak.*"))


def test_golden_patched_client_sends_the_asserted_account_and_measures_the_account(tmp_path, monkeypatch):
    root = _stage(tmp_path); assert _run(root).returncode == 0
    monkeypatch.setenv("EXECUTOR_URL", "http://bridge/execute"); monkeypatch.setenv("V7_MT5_LOGIN", "52834417")
    spec = importlib.util.spec_from_file_location("deploy_v7_bot_ic_markets", root / "core" / "ic_markets.py")
    icm = importlib.util.module_from_spec(spec); spec.loader.exec_module(icm)
    sent = {}
    class _R:
        status_code = 200
        def json(self): return {"status": "ok", "account": 52834417, "balance": 5.0, "trade_mode": 0}
    class _Http:
        @staticmethod
        def get(url, timeout=5): return _R()
        @staticmethod
        def post(url, json=None, timeout=15): sent.update(json); return _R()
    monkeypatch.setattr(icm, "requests", _Http)
    c = icm.ICMarketsClient()
    monkeypatch.setattr(c, "is_market_open", lambda s: True)
    c.open_trade("GOLD", "BUY", 0.05, 2390.0, 2420.0, comment="BS_test")
    assert sent["account_id"] == "52834417" and sent["signal_id"] == "BS_test"                 # ISO-03
    assert c.get_account() == {"login": 52834417, "trade_mode": 0, "balance": 5.0}            # heartbeat item 2
    assert "shadow_only" in (root / "filters" / "ai_filter.py").read_text(encoding="utf-8")   # ISO-24
