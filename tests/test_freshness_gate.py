"""Freshness gate v1 (2026-08-22) — DECISION BLOCKED — DATA FRESHNESS.
Pure functions; the wiring patch is tested like the other box patches."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filters.freshness_gate import BLOCKED_STATE, evaluate, gate_from_env  # noqa: E402


def test_fresh_signal_passes():
    out = evaluate(signal_age_s=120)
    assert out["state"] == "OK" and not out["blocked"]


def test_stale_signal_blocks_with_the_named_state():
    out = evaluate(signal_age_s=1800)
    assert out["blocked"] and out["state"] == BLOCKED_STATE
    assert "1800s" in out["reason"]


def test_material_move_blocks_when_inputs_exist():
    # the BTC case: evaluated at 78385, reference now 80000, ATR 600
    out = evaluate(signal_age_s=60, entry=78385, reference_close=80000, atr=600)
    assert out["blocked"] and "ATR" in out["reason"]
    # small move passes
    ok = evaluate(signal_age_s=60, entry=78385, reference_close=78500, atr=600)
    assert not ok["blocked"]


def test_unknown_inputs_never_block_in_v1():
    out = evaluate(signal_age_s=None)
    assert not out["blocked"] and out["checks"]["signal_age"] == "UNKNOWN"
    out2 = evaluate(signal_age_s=60, entry=100, reference_close=None, atr=None)
    assert not out2["blocked"]


def test_env_modes(monkeypatch):
    monkeypatch.setenv("V7_FRESHNESS_GATE", "off")
    assert not gate_from_env(signal_age_s=99999)["blocked"]
    monkeypatch.setenv("V7_FRESHNESS_GATE", "shadow")
    out = gate_from_env(signal_age_s=99999)
    assert out["blocked"] and out["mode"] == "shadow"
    monkeypatch.setenv("V7_FRESHNESS_GATE", "enforce")
    assert gate_from_env(signal_age_s=99999)["mode"] == "enforce"
    # an unknown word falls back to shadow — never silently to enforce/off
    monkeypatch.setenv("V7_FRESHNESS_GATE", "banana")
    assert gate_from_env(signal_age_s=99999)["mode"] == "shadow"
    monkeypatch.setenv("V7_FRESHNESS_GATE", "shadow")
    monkeypatch.setenv("V7_FRESH_MAX_SIGNAL_AGE_S", "60")
    assert gate_from_env(signal_age_s=90)["blocked"]


def test_wiring_patch_script(tmp_path):
    script = (ROOT / "patch_freshness_gate.py").read_text()
    gate_src = (ROOT / "filters" / "freshness_gate.py").read_text()
    anchor = "    lot,_=calc_lot(symbol,entry,inst_sl,balance,effective_risk)\n"
    fake_bot = ("def handler(symbol, direction, entry, inst_sl, balance,\n"
                "            effective_risk, payload, signal_age_seconds_v, log, calc_lot):\n"
                + anchor +
                "    return {\"status\": \"ok\"}\n")

    work = tmp_path / "box"
    (work / "filters").mkdir(parents=True)
    (work / "learning").mkdir()
    (work / "patch_freshness_gate.py").write_text(script)
    (work / "bot.py").write_text(fake_bot)

    # module missing -> abort untouched
    r0 = subprocess.run([sys.executable, "patch_freshness_gate.py"],
                        cwd=work, capture_output=True, text=True)
    assert r0.returncode == 1 and "missing" in r0.stdout
    assert (work / "bot.py").read_text() == fake_bot

    (work / "filters" / "freshness_gate.py").write_text(gate_src)
    r1 = subprocess.run([sys.executable, "patch_freshness_gate.py"],
                        cwd=work, capture_output=True, text=True)
    assert r1.returncode == 0 and "PATCHED bot.py" in r1.stdout, r1.stdout
    patched = (work / "bot.py").read_text()
    assert "gate_from_env" in patched and "DECISION BLOCKED" in patched
    assert "shadow" in r1.stdout                    # says nothing is blocked yet

    r2 = subprocess.run([sys.executable, "patch_freshness_gate.py"],
                        cwd=work, capture_output=True, text=True)
    assert r2.returncode == 0 and "ALREADY PATCHED" in r2.stdout
    assert (work / "bot.py").read_text() == patched
