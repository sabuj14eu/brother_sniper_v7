# EVIDENCE — golden fixtures for the v7 BRIDGE deploy script (ISO-03/05/16 + heartbeat item 1), keep.
"""patch_v7_bridge_iso03_05_16.py applied to the ISO-01-patched bridge (main a3640d6) must produce
EXACTLY the repo's sniper_executor.py at 0d1a2a5, back it up, be idempotent, write nothing on an
ambiguous anchor; the patched COPY must refuse a missing account_id and a present stop file.
Run from the repo root:  python3 -m pytest tests/audit/2026-09-05_deploy_v7_bridge -q"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
JOB3 = HERE.parent / "2026-09-04_job3"
if str(JOB3) not in sys.path:
    sys.path.insert(0, str(JOB3))
from conftest import V7_ACCOUNT, FakeMT5, load_v7_bridge  # noqa: E402

SCRIPT = REPO / "patch_v7_bridge_iso03_05_16.py"
PRE = HERE / "fixtures" / "prepatch_a3640d6_sniper_executor.py"
EXPECTED = HERE / "fixtures" / "expected_0d1a2a5_sniper_executor.py"


def _stage(tmp_path):
    root = tmp_path / "Administrator"; root.mkdir(parents=True)
    shutil.copy(PRE, root / "sniper_executor.py")
    return root


def _run(root):
    return subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)


def test_golden_output_is_byte_identical_to_the_repo_bridge(tmp_path):
    root = _stage(tmp_path); r = _run(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / "sniper_executor.py").read_text(encoding="utf-8") == EXPECTED.read_text(encoding="utf-8")
    assert len(list(root.glob("*.bak.*"))) == 1


def test_golden_idempotent_and_abort_writes_nothing(tmp_path):
    root = _stage(tmp_path); assert _run(root).returncode == 0
    r = _run(root); assert r.returncode == 0 and "Already patched" in r.stdout and len(list(root.glob("*.bak.*"))) == 1
    root2 = _stage(tmp_path / "b"); f = root2 / "sniper_executor.py"
    f.write_text(f.read_text(encoding="utf-8").replace('SECRET = os.getenv("WEBHOOK_SECRET", "")', 'SECRET  = os.getenv("WEBHOOK_SECRET", "")', 1), encoding="utf-8")
    snap = f.read_bytes(); r = _run(root2)
    assert r.returncode != 0 and "ABORT" in (r.stdout + r.stderr) and f.read_bytes() == snap and not list(root2.glob("*.bak.*"))


def test_golden_patched_copy_behaves_like_the_repo_bridge(tmp_path, monkeypatch):
    root = _stage(tmp_path); assert _run(root).returncode == 0
    monkeypatch.setenv("GLOBAL_STOP_FILE", str(tmp_path / "GLOBAL_STOP"))
    term = FakeMT5(V7_ACCOUNT)
    ex = load_v7_bridge(term, monkeypatch, path=root / "sniper_executor.py")
    c = ex.app.test_client()
    base = {"secret": "s3cret", "symbol": "GOLD", "direction": "BUY", "lot": 0.05, "sl": 2390.0, "tp": 2420.0, "signal_id": "SS-1"}
    assert c.post("/execute", json=base).status_code == 400                                   # ISO-03: no account_id
    assert c.post("/execute", json={**base, "account_id": "52901228"}).status_code == 403      # ISO-03: wrong account
    ok = c.post("/execute", json={**base, "account_id": str(V7_ACCOUNT)}).get_json()
    assert ok["status"] == "ok" and term.orders[0]["magic"] == 70007                            # ISO-03: magic stamped
    h = c.get("/health").get_json()
    assert h["global_stop"] == "CLEAR" and "trade_mode" in h and h["account"] == V7_ACCOUNT
    (tmp_path / "GLOBAL_STOP").write_text("x")
    assert c.post("/execute", json={**base, "account_id": str(V7_ACCOUNT), "signal_id": "SS-2"}).status_code == 503   # ISO-16
    assert len(term.orders) == 1
