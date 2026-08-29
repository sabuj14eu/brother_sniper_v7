"""Week-2 autonomy tools (2026-08-31): replay bounds, state audit, scorecard.
All read-only over synthetic fixtures — nothing trades."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mgmt_replay import breakeven_1r, entry_only  # noqa: E402


def g(mae_r, mfe_r, tp_r=2.0):
    return {"mae_r": mae_r, "mfe_r": mfe_r, "tp_r": tp_r}


def test_replay_entry_only_bounds():
    assert entry_only(g(0.3, 2.5)) == (2.0, 2.0, "TP")
    assert entry_only(g(1.2, 0.5)) == (-1.0, -1.0, "STOPPED")
    b, w, tag = entry_only(g(1.2, 2.5))          # both extremes -> order unknown
    assert (b, w) == (2.0, -1.0) and "AMBIGUOUS" in tag
    assert entry_only(g(0.3, 0.5))[0] is None    # undecided


def test_replay_breakeven_never_worse_than_minus_one_and_saves_when_armed():
    # BE armed (mfe>=1), TP unreached, stop untouched -> scratched at ~0
    assert breakeven_1r(g(0.4, 1.3)) == (0.0, 0.0, "BE EXIT (armed, TP unreached)")
    # BE armed but stop level also reached -> bounded 0..-1, never invented
    b, w, tag = breakeven_1r(g(1.5, 1.3))
    assert (b, w) == (0.0, -1.0) and "AMBIGUOUS" in tag
    # BE never armed -> identical to entry-only
    assert breakeven_1r(g(1.2, 0.5)) == entry_only(g(1.2, 0.5))


def _run(script, cwd):
    return subprocess.run([sys.executable, str(script)], cwd=cwd,
                          capture_output=True, text=True)


def _fixture_box(tmp_path, opens, closes, state):
    box = tmp_path / "box"
    (box / "learning").mkdir(parents=True)
    (box / "logs").mkdir()
    with open(box / "learning" / "trades.jsonl", "w") as f:
        for r in opens + closes:
            f.write(json.dumps(r) + "\n")
    (box / "signal_memory.json").write_text("{}")
    (box / "state.json").write_text(json.dumps(state))
    guard = ('_tighter=(_dir=="BUY" and _be>_cur_sl) or '
             '(_dir=="SELL" and _be<_cur_sl)')
    (box / "bot.py").write_text(f"# fake\n{guard}\n")
    (box / "audit_mgmt_state.py").write_text(
        (ROOT / "audit_mgmt_state.py").read_text())
    return box


def test_audit_clean_box_is_zero():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        box = _fixture_box(
            Path(td),
            opens=[{"signal_id": "S1", "entry": 10, "sl": 9, "direction": "BUY"}],
            closes=[{"signal_id": "S1", "won": True, "mae": 0.2, "mfe": 1.4}],
            state={"open_trades": {"metals": None}})
        r = _run("audit_mgmt_state.py", box)
        assert r.returncode == 0, r.stdout
        assert "0 violation" in r.stdout
        saved = json.loads((box / "logs" / "mgmt_audit_last.json").read_text())
        assert saved["violations"] == 0


def test_audit_catches_the_required_zeros():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        box = _fixture_box(
            Path(td),
            opens=[],
            closes=[{"signal_id": "S1", "won": True, "mae": -0.5, "mfe": 1.0,
                     "partial_done": True},
                    {"signal_id": "S1", "won": False, "net_profit": -3}],
            state={"open_trades": {"metals": {
                "signal_id": "S1", "entry": 10, "sl": 11, "direction": "BUY"}}})
        r = _run("audit_mgmt_state.py", box)
        assert r.returncode == 1
        for inv in ("double_close", "partial_fired", "closed_reactivated",
                    "sl_wrong_side", "negative_excursion"):
            assert inv in r.stdout


def test_scorecard_counts_the_bots_own_words(tmp_path, monkeypatch):
    import auto_live
    import autonomy_scorecard as asc
    day = time.strftime("%Y-%m-%d", time.gmtime())
    now = time.time()
    scen = tmp_path / "scen.jsonl"
    dry = tmp_path / "dry.jsonl"
    rows = [
        {"ts": now, "state": "🟢 BUY READY", "pine_dependency": "NONE",
         "entry": 1, "sl": 0.9, "tp": 1.2, "rr": 2.0, "freshness": "OK",
         "missing_confirmation": []},
        {"ts": now, "state": "🟡 SELL DEVELOPING", "pine_dependency": "NONE",
         "freshness": "OK", "missing_confirmation": ["touch"]},
        {"ts": now, "state": "⚪ WAIT", "pine_dependency": "NONE",
         "current_state": "NEITHER CONFIRMED", "freshness": "OK"},
        {"ts": now, "state": "⛔ DATA FRESHNESS", "pine_dependency": "NONE",
         "current_state": "DECISION BLOCKED — DATA FRESHNESS", "freshness": "STALE >3 bars"},
    ]
    with open(scen, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with open(dry, "w") as f:
        f.write(json.dumps({"posted_at": now, "pine_dependency": "NONE"}) + "\n")
    monkeypatch.setattr(asc, "SCEN_LOG", str(scen))
    monkeypatch.setattr(asc, "DRY_LOG", str(dry))
    monkeypatch.setattr(asc, "TRADES", str(tmp_path / "none.jsonl"))
    monkeypatch.setattr(asc, "AUDIT", str(tmp_path / "none.json"))
    sc = asc.scorecard(day)
    assert sc["PINE-INDEPENDENT DECISIONS"] == 5
    assert sc["PINE-DEPENDENT DECISIONS"] == 0
    assert sc["CONFIRMED SETUPS"] == 1 and sc["CONDITIONAL SETUPS"] == 1
    assert sc["COMPLETE DECISIONS"] == 1
    assert sc["WAIT WITH REASON"] == 2
    assert sc["STALE-DATA VIOLATIONS"] == 0        # blocks are correct, not violations
    assert sc["STATE VIOLATIONS"] == "NOT RUN"
    assert "MUST = 0" not in asc.render(sc)        # flag only fires when nonzero
