"""News semantic engine v1 — the laws, pinned. Facts, never signals."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from filters.news_semantic import (agreement, classify, event_fact,
                                   news_context, parse_num, phase_of,
                                   stance_of, surprise)


def _ev(title="Core PCE Price Index m/m", mins_ago=20, currency="USD",
        actual="0.4%", forecast="0.2%"):
    t = datetime.now(timezone.utc) - timedelta(minutes=mins_ago)
    return {"title": title, "date": t.isoformat(), "currency": currency,
            "impact": "High", "actual": actual, "forecast": forecast}


def test_numbers_beat_words():
    # numeric data present -> wording can NEVER set the surprise
    assert surprise("0.4%", "0.2%") == ("HOT", "HIGH")
    assert surprise("0.1%", "0.2%") == ("COOL", "HIGH")
    assert surprise("0.2%", "0.2%") == ("INLINE", "HIGH")
    assert surprise(None, "0.2%") == ("UNKNOWN", "UNKNOWN")
    assert parse_num("210K") == 210000.0 and parse_num("3.1%") == 3.1
    # "cooler" wording loses to a hot number
    st, conf, basis = stance_of("Cooler CPI y/y", "INFLATION", "HOT")
    assert st == "HAWKISH" and conf == "HIGH" and "actual" in basis


def test_inverted_series_polarity():
    # unemployment HIGHER than forecast = weaker economy = DOVISH
    st, conf, _ = stance_of("Unemployment Rate", "EMPLOYMENT", "HOT")
    assert st == "DOVISH" and conf == "HIGH"
    st2, _, _ = stance_of("Non-Farm Employment Change", "EMPLOYMENT", "HOT")
    assert st2 == "HAWKISH"


def test_hot_pce_pressure_map_is_shyams_example():
    f = event_fact(_ev())
    assert f["event_class"] == "INFLATION" and f["surprise"] == "HOT"
    assert f["stance"] == "HAWKISH"
    p = f["pressure"]
    assert p["DXY"] == "BULLISH" and p["YIELDS"] == "BULLISH"
    assert p["GOLD"] == "BEARISH" and p["US100"] == "BEARISH"
    assert f["event_phase"] == "STRUCTURE FORMING"      # 20 min after


def test_non_usd_and_wordless_stay_unknown():
    f = event_fact(_ev(title="ECB Rate Decision", currency="EUR"))
    assert f["pressure"] == "UNKNOWN (non-USD or stance unknown)"
    g = event_fact(_ev(title="Crude Oil Inventories", actual=None, forecast=None))
    assert g["surprise"] == "UNKNOWN" and g["stance"] == "UNKNOWN"


def test_phases_and_normal_regime():
    assert phase_of(-30) == "PRE-EVENT" and phase_of(5) == "INITIAL MOVE"
    assert phase_of(60) == "RETEST" and phase_of(200) == "POST-NEWS"
    assert phase_of(500) == "NORMAL" and phase_of(-120) == "NORMAL"
    assert news_context([_ev(mins_ago=600)], "GOLD") is None  # old news = NORMAL


def test_conflicting_news_forces_no_direction():
    evs = [_ev(mins_ago=20),                                    # HOT PCE hawkish
           _ev(title="Unemployment Rate", mins_ago=25)]         # HOT unemp dovish
    ctx = news_context(evs, "GOLD")
    assert ctx["conflicting"] and ctx["symbol_pressure"] == "UNKNOWN"
    assert "CONFLICTING" in ctx["note"]


def test_price_keeps_the_final_vote():
    assert agreement("BEARISH", "bearish (LH/LL)") == "CONFIRMED"
    assert "CONFLICT" in agreement("BEARISH", "bullish (HH/HL)")
    assert agreement("UNKNOWN", "bullish (HH/HL)") == "UNKNOWN"


def test_scenario_embeds_news_as_context_never_gate():
    from tests.test_auto_live import _rows
    from auto_live import scenario
    now = time.time()
    rows = _rows(now=now)
    rec = scenario("GOLD", rows, 3.0, now=now, events=[_ev(mins_ago=20)])
    assert rec["event_phase"] == "STRUCTURE FORMING"
    assert rec["news"]["note"] == "MACRO PRESSURE, not a trade signal"
    assert rec["news"]["symbol_pressure"] == "BEARISH"
    # HH/HL fixture -> bullish price vs bearish news -> declared CONFLICT,
    # but the state machine still runs on price (news never gates)
    assert "CONFLICT" in rec["news_price_agreement"]
    assert rec["state"] == "🟡 BUY DEVELOPING"
    # no events passed -> UNKNOWN stands, exactly as before
    bare = scenario("GOLD", rows, 3.0, now=now)
    assert "UNKNOWN" in bare["event_phase"]
    # empty calendar -> honest NORMAL
    quiet = scenario("GOLD", rows, 3.0, now=now, events=[])
    assert quiet["event_phase"] == "NORMAL"
