"""C2 (audit 2026-09-01): Pine sends htf_align (verified in the v18.13
source — no htf_agree key exists anywhere in Pine); core/signal_memory.py
read htf_agree, so the stored flag was False on every record ever written.
RED before the fix, GREEN after."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.signal_memory as sm  # noqa: E402


def _rec(monkeypatch, payload):
    monkeypatch.setattr(sm, "_maybe_persist", lambda: None)   # no disk writes
    return sm.record_signal({"symbol": "GOLD", "signal": "BUY",
                             "system": "BSv18", "entry": 1, "sl": 0.9,
                             "tp": 1.2, **payload})


def test_htf_align_is_stored(monkeypatch):
    assert _rec(monkeypatch, {"htf_align": True})["htf_agree"] is True
    assert _rec(monkeypatch, {"htf_align": False})["htf_agree"] is False


def test_legacy_htf_agree_still_read(monkeypatch):
    assert _rec(monkeypatch, {"htf_agree": True})["htf_agree"] is True
