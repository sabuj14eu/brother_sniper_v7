"""Audit round 2 (2026-09-02): C1 dedup collision + A1 unverified-never-a-loss.
Both tests drive the PATCHED bot.py text itself — extracted verbatim and
exec'd — so what is pinned is the deployed logic, not a copy of it."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _patched_bot(*scripts):
    d = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "bot.py", d / "bot.py")
    for s in scripts:
        shutil.copy(ROOT / s, d / s)
        r = subprocess.run([sys.executable, s], cwd=d,
                           capture_output=True, text=True)
        assert r.returncode == 0, (s, r.stdout, r.stderr)
    return (d / "bot.py").read_text()


def _make_sid_from(src):
    start = src.index("def _make_sid(")
    end = src.index("def _is_dup(")
    ns = {"hashlib": __import__("hashlib")}
    exec(src[start:end], ns)
    return ns["_make_sid"]


def test_c1_two_symbols_same_pine_id_both_trade():
    src = _patched_bot("patch_dedup_symbol.py")
    sid = _make_sid_from(src)
    gold = sid({"symbol": "GOLD", "signal_id": "SS-BUY-1756700000"})
    silver = sid({"symbol": "SILVER", "signal_id": "SS-BUY-1756700000"})
    assert gold != silver                       # both trade — no collision
    # same symbol, same id -> identical key -> still refused as duplicate
    assert sid({"symbol": "GOLD", "signal_id": "SS-BUY-1756700000"}) == gold
    # no-id fallback unchanged: symbol+direction+entry hash
    a = sid({"symbol": "GOLD", "direction": "BUY", "entry": 100})
    b = sid({"symbol": "SILVER", "direction": "BUY", "entry": 100})
    assert a != b and len(a) == 16


def test_a1_unverified_close_increments_no_loss():
    src = _patched_bot("patch_truth_guards.py", "patch_unverified_not_loss.py")
    # extract the accounting branch verbatim and drive it
    key = '                    if won: state["consecutive_losses"]=0;'
    start = src.index(key)
    end = src.index("\n", src.index("LOSS ${net:.2f}", start)) + 1
    block = "\n".join(l[20:] for l in src[start:end].splitlines())

    def run(won, deal, net=0.0):
        state = {"consecutive_losses": 3, "total_losses": 5, "total_wins": 2}
        ns = {"state": state, "won": won, "deal": deal, "net": net}
        exec(block, ns)
        return state, ns["tag"]

    st, tag = run(won=False, deal=None)          # the unverified fallback
    assert st["consecutive_losses"] == 3         # streak untouched
    assert st["total_losses"] == 5               # no loss counted
    assert "UNVERIFIED" in tag
    st2, tag2 = run(won=False, deal={"found": True}, net=-4.2)
    assert st2["consecutive_losses"] == 4 and st2["total_losses"] == 6
    st3, _ = run(won=True, deal={"found": True}, net=3.0)
    assert st3["consecutive_losses"] == 0 and st3["total_wins"] == 3
