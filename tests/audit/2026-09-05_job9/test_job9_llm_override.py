# EVIDENCE — reproduces finding ISO-24 (an LLM overrides a rule block in v7), keep.
"""Job 9 (spec §45), v7 side — is there an LLM in the decision path?

filters/ai_filter.py:106-119: when the rule score BLOCKS a signal (and the
block is not news-flagged), score_signal asks deepseek_tiebreak() — a live
DeepSeek/Gemini call — and if it answers take=True with confidence >= 60 the
block is REVERSED ("AI OVERRIDE"). docs/V7_SELF_DEPENDENCE_PLAN.md and the
platform CLAUDE.md say "No LLM in the decision path, ever". Whether the API
key is present on the Contabo box is UNKNOWN from the repo (DEEPSEEK_API_KEY /
GEMINI_API_KEY); without it _v is None and no override happens.

Run from the repo root:  python3 -m pytest tests/audit/2026-09-05_job9 -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from filters import ai_filter                      # noqa: E402
from filters import deepseek_vote                  # noqa: E402
from learning.regime_detector import RegimeResult  # noqa: E402

VOLATILE = RegimeResult(regime="VOLATILE", confidence=0.9, atr_multiplier=1.8,
                        score_threshold=68, risk_scale=0.5, description="test")


@pytest.fixture(autouse=True)
def realistic_threshold(monkeypatch):
    """OBSERVATION ISO-25 (P2): with no learning/weights.json the filter's
    threshold is 5/100 (ai_filter.py:10, :23; weight_engine.py:6
    DEFAULT_THRESHOLD=5, "frozen during data collection until 100 trades"),
    so a score of 20 passes and the override branch is never reached. The
    box's weights.json is gitignored: its live threshold is UNKNOWN. These
    tests pin 50 so the block, and therefore the override, is reproducible."""
    monkeypatch.setattr(ai_filter, "_load_weights_if_stale", lambda: None)
    monkeypatch.setattr(ai_filter, "_current_weights",
                        {"session": 1.0, "news": 1.0, "rr": 1.0, "atr_context": 1.0, "trend": 1.0, "volatility": 1.0})
    monkeypatch.setattr(ai_filter, "_current_threshold", 50)


def _blocked_inputs():
    """A signal the rules block on their own: counter-trend, R:R 1:0.5, ATR
    tiny vs stop, news 10 minutes away would be news-flagged so keep it None."""
    return dict(symbol="GOLD", direction="SELL", entry=2400.0, sl_price=2410.0, tp=2395.0,
                regime_result=VOLATILE, atr=0.5, htf_trend="UP", news_minutes=None,
                custom_score=None, signal_id="SS-SELL-TEST")


def test_repro_ISO24_llm_vote_reverses_a_rule_block(monkeypatch):
    """FINDING ISO-24 (P0). With the tiebreak answering (True, 80, ...), a
    signal the rules blocked becomes passed=True and the reason starts with
    "AI OVERRIDE". VERDICT NOW: FAIL (an LLM widens risk in the decision path)."""
    calls = []
    monkeypatch.setattr(deepseek_vote, "deepseek_tiebreak", lambda ctx: calls.append(ctx) or None)
    base = ai_filter.score_signal(**_blocked_inputs())
    if base.passed:
        pytest.skip("NOT RUNNABLE: the chosen inputs are not blocked by the rules on this weight file")
    assert "news" not in base.reason

    monkeypatch.setattr(deepseek_vote, "deepseek_tiebreak", lambda ctx: (True, 80, "[test-llm] go"))
    over = ai_filter.score_signal(**_blocked_inputs())
    assert over.passed is True
    assert over.reason.startswith("AI OVERRIDE")
    assert over.breakdown["deepseek"]["confidence"] == 80


def test_holds_llm_cannot_override_a_news_flagged_block(monkeypatch):
    """ai_filter.py:102-105 [F6] — a news-flagged block is never overridden. PASS."""
    monkeypatch.setattr(deepseek_vote, "deepseek_tiebreak", lambda ctx: (True, 99, "[test-llm] go"))
    r = ai_filter.score_signal(**{**_blocked_inputs(), "news_minutes": 10})
    assert r.passed is False and "news" in r.reason


def test_holds_low_confidence_vote_does_not_override(monkeypatch):
    """ai_filter.py:112 — confidence < 60 keeps the block. PASS."""
    monkeypatch.setattr(deepseek_vote, "deepseek_tiebreak", lambda ctx: (True, 59, "[test-llm] meh"))
    r = ai_filter.score_signal(**_blocked_inputs())
    assert r.passed is False and "AI agreed block" in r.reason


def test_repro_ISO24b_no_api_key_means_no_override_today_but_the_path_is_live(monkeypatch):
    """Without DEEPSEEK_API_KEY / GEMINI_API_KEY the real tiebreak returns None
    (deepseek_vote.py:177) and the block stands — so production behaviour is
    UNKNOWN until the key's presence on the box is measured. The code path
    itself is reachable from score_signal. Documented, not asserted on secrets."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("EYE_MODEL", "deepseek")
    r = ai_filter.score_signal(**_blocked_inputs())
    assert r.passed is False and not r.reason.startswith("AI OVERRIDE")
