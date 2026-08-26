"""Auto-weekly outlook generator (2026-08-26) — measured facts only."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from post_outlook import BANNED, build_payload
from post_weekly_outlooks import WEEK_BARS, build_symbol_outlook


def _rows(n=120, base=100.0, step=0.1, now=None):
    now = now or time.time()
    start = now - n * 240 * 60
    return [{"time": start + i * 240 * 60, "h": base + i * step + 1,
             "l": base + i * step - 1, "c": base + i * step} for i in range(n)]


def test_thesis_is_measured_and_scenarios_are_traded_extremes():
    now = time.time()
    rows = _rows(now=now)
    args, why = build_symbol_outlook(rows, {"n": 50, "expectancy_r": 0.4}, now=now)
    assert why is None
    week = rows[-WEEK_BARS:]
    hi = max(r["h"] for r in week)
    lo = min(r["l"] for r in week)
    assert f"above:{hi:g}:" in args["scenarios"][0]
    assert f"below:{lo:g}:" in args["scenarios"][1]
    assert "n=50" in args["thesis"] and "+0.40R" in args["thesis"]
    for w in BANNED:                       # never a confidence word
        assert w not in args["thesis"].lower()
    # and the full payload passes the real contract builder
    body = build_payload("GOLD", "weekly", args["thesis"],
                         "bot box auto-weekly-v1", args["scenarios"], None)
    assert len(body["scenarios"]) == 2 and body["source"] == "bot box auto-weekly-v1"


def test_stale_or_thin_candles_skip_never_invent():
    now = time.time()
    old = _rows(now=now - 5 * 240 * 60)    # newest bar 5 bars old -> stale
    args, why = build_symbol_outlook(old, {"n": 0}, now=now)
    assert args is None and "stale" in why
    args2, why2 = build_symbol_outlook(_rows(n=20, now=now), {"n": 0}, now=now)
    assert args2 is None and "closed 4h bars" in why2


def test_unknown_profile_stays_unknown():
    now = time.time()
    args, _ = build_symbol_outlook(_rows(now=now), {"n": 3}, now=now)
    assert "UNKNOWN" in args["thesis"]


def test_forming_bar_excluded():
    now = time.time()
    rows = _rows(now=now)
    rows.append({"time": now - 60, "h": 999999, "l": 0.1, "c": 1})  # forming
    args, why = build_symbol_outlook(rows, {"n": 0}, now=now)
    assert why is None
    assert "999999" not in args["scenarios"][0]   # forming high never a level
