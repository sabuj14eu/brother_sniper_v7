"""2026-09-03: the v7 heartbeat + decision emitter is back on the deploy branch."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PATCH = "patch_v7_status_hooks.py"
MARK = "[V7-STATUS 2026-09-03]"


def test_repo_bot_carries_both_hooks_in_order():
    src = (ROOT / "bot.py").read_text(encoding="utf-8")
    assert src.count(MARK) >= 3
    i_sweep = src.index('log.warning(f"[SLOT-RECON] sweep failed: {_re2}")')
    i_hb = src.index("from core.v7_status import update_heartbeat")
    i_any = src.index("if not any_open_trade(): continue", i_hb)
    assert i_sweep < i_hb < i_any                      # heartbeat runs every cycle
    i_rt = src.index('log.warning(f"[REJECT-TELEMETRY] skipped (non-fatal): {_re}")')
    i_rd = src.index("from core.v7_status import record_decision")
    i_ret = src.index("return jsonify(result)", i_rd)
    assert i_rt < i_rd < i_ret                         # every verdict is recorded
    assert "_bridge_ok=True" in src and "_bridge_ok=False" in src


def test_patch_is_idempotent_on_the_repo_copy():
    d = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "bot.py", d / "bot.py")
    shutil.copy(ROOT / PATCH, d / PATCH)
    r = subprocess.run([sys.executable, PATCH], cwd=d, capture_output=True, text=True)
    assert r.returncode == 0 and "ALREADY PATCHED" in r.stdout


def test_push_accepts_either_env_pair(monkeypatch):
    from core import v7_status as vs
    started = []
    monkeypatch.setattr(threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda self: started.append(k.get("target"))})())
    for k in ("PLATFORM_URL", "PLATFORM_SECRET", "PLATFORM_WEBHOOK_URL", "PLATFORM_WEBHOOK_SECRET"):
        monkeypatch.delenv(k, raising=False)
    vs._push({"kind": "x"}, "/p")
    assert started == []                                # inert without a target
    monkeypatch.setenv("PLATFORM_WEBHOOK_URL", "https://example.invalid")
    monkeypatch.setenv("PLATFORM_WEBHOOK_SECRET", "s")
    vs._push({"kind": "x"}, "/p")
    assert len(started) == 1                            # deploy-branch names work
    monkeypatch.setenv("PLATFORM_URL", "https://example.invalid")
    monkeypatch.setenv("PLATFORM_SECRET", "s")
    vs._push({"kind": "x"}, "/p")
    assert len(started) == 2                            # trade-desk names still work
