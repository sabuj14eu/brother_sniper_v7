"""auto-live-v1 (2026-08-30) — the earned engine, pinned by test.
Pure candidate logic; no network, no webhook, no orders."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_live import LOOKBACK, MIN_RR, SL_ATR, atr, candidate, structure_state


def _rows(n=100, base=100.0, step=0.02, now=None, last_low=None, last_high=None):
    """Uptrending closed 15m rows WITH swings (a pure ramp has no local
    extremes and structure_state correctly refuses it — same reason the
    platform's own fixtures use a sawtooth). 5-bar saw on a rising base
    -> rising swing highs AND rising swing lows -> HH/HL."""
    now = now or time.time()
    start = now - (n + 1) * 900          # every bar fully closed
    out = []
    for i in range(n):
        c = base + i * step + (i % 5) * 0.2
        out.append({"time": start + i * 900, "o": c, "h": c + 0.3,
                    "l": c - 0.3, "c": c})
    if last_low is not None:
        out[-1]["l"] = last_low
    if last_high is not None:
        out[-1]["h"] = last_high
    return out


def test_ported_math_matches_platform_semantics():
    rows = _rows()
    assert structure_state(rows) == "HH/HL"          # rising highs and lows
    a = atr(rows)
    assert a is not None and a > 0


def test_fires_only_on_touch_with_structure_intact():
    now = time.time()
    rows = _rows(now=now)
    r_low = min(r["l"] for r in rows[-LOOKBACK:])
    # newest bar does NOT reach the structural low -> WAIT, never a trade
    c, why = candidate(rows, 3.0, now=now)
    assert c is None and "not touched" in why

    # newest bar dips to the level -> the paper limit's fill moment -> FIRE
    rows2 = _rows(now=now, last_low=r_low - 0.01)
    r_low2 = min(r["l"] for r in rows2[-LOOKBACK:])
    c2, why2 = candidate(rows2, 3.0, now=now)
    assert why2 is None and c2["direction"] == "BUY"
    a = atr([r for r in rows2 if r["time"] + 900 <= now])
    assert abs(c2["entry"] - r_low2) < 1e-6
    assert abs(c2["sl"] - (r_low2 - SL_ATR * a)) < 1e-6
    assert c2["rr"] >= MIN_RR and c2["entry_dist_atr"] <= 3.0


def test_far_levels_are_never_tracked():
    """Price far above the structural low = the measured far bucket.
    The newest bar is never a swing point, so lifting it leaves the
    HH/HL structure intact — only the distance rule can refuse, and
    it refuses before the touch check."""
    now = time.time()
    rows = _rows(now=now)
    rows[-1]["c"] += 10.0
    rows[-1]["h"] += 10.3
    c, why = candidate(rows, 3.0, now=now)
    assert c is None and "far bucket" in why


def test_stale_candles_block_with_the_freshness_state():
    now = time.time()
    rows = _rows(now=now - 5 * 900)                  # newest bar 5 bars old
    c, why = candidate(rows, 3.0, now=now)
    assert c is None and "DATA FRESHNESS" in why


def test_forming_bar_never_counts():
    now = time.time()
    rows = _rows(now=now)
    forming = {"time": now - 60, "o": 1, "h": 99999.0, "l": 0.001, "c": 1}
    c_with = candidate(rows + [forming], 3.0, now=now)
    c_without = candidate(rows, 3.0, now=now)
    assert c_with == c_without                       # identical decision


def test_mixed_structure_refuses():
    now = time.time()
    rows = _rows(now=now)
    for i in range(0, len(rows), 7):                 # chop the trend
        rows[i]["h"] += 3.0
        rows[i]["l"] -= 3.0
    c, why = candidate(rows, 3.0, now=now)
    assert c is None

# ── Week-2: scenario record (the decision even when it is WAIT) ──

from auto_live import FRESH_BLOCK, WAIT, scenario


def test_scenario_agrees_with_candidate_on_ready():
    now = time.time()
    rows = _rows(now=now)
    r_low = min(r["l"] for r in rows[-LOOKBACK:])
    rows2 = _rows(now=now, last_low=r_low - 0.01)
    rec = scenario("SILVER", rows2, 3.0, now=now)
    c, why = candidate(rows2, 3.0, now=now)
    assert rec["state"] == "🟢 BUY READY" and why is None
    assert rec["entry"] == c["entry"] and rec["sl"] == c["sl"]
    assert rec["pine_dependency"] == "NONE"


def test_scenario_developing_when_not_touched():
    now = time.time()
    rec = scenario("SILVER", _rows(now=now), 3.0, now=now)
    assert rec["state"] == "🟡 BUY DEVELOPING"
    assert rec["missing_confirmation"] and rec["invalidation"]
    assert candidate(_rows(now=now), 3.0, now=now)[0] is None


def test_scenario_wait_states_carry_reasons():
    now = time.time()
    stale = scenario("GOLD", _rows(now=now - 5 * 900), 3.0, now=now)
    assert stale["state"] == FRESH_BLOCK and stale["freshness"] != "OK"
    rows = _rows(now=now)
    rows[-1]["c"] += 10.0
    rows[-1]["h"] += 10.3
    far = scenario("GOLD", rows, 3.0, now=now)
    assert far["state"] == WAIT and "far" in far["current_state"]
    assert far["next_thing_to_watch"]
    short = scenario("GOLD", _rows(n=10, now=now), 3.0, now=now)
    assert short["state"] == WAIT and "history" in short["missing_confirmation"][0]
    # UNKNOWN stays UNKNOWN — never manufactured
    assert "UNKNOWN" in far["macro_context"] and "UNKNOWN" in far["event_phase"]


def test_scenario_carries_its_own_clock():
    """as_of = last closed bar's close, ISO UTC — the platform rejects a
    state without it by name (Freshness Law)."""
    now = time.time()
    rows = _rows(now=now)
    rec = scenario("SILVER", rows, 3.0, now=now)
    closed_end = max(float(r["time"]) for r in rows
                     if float(r["time"]) + 900 <= now) + 900
    assert rec["as_of"] == time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                                         time.gmtime(closed_end))
    short = scenario("SILVER", [], 3.0, now=now)
    assert short["as_of"]                        # even empty states carry a clock
