"""post_outlook.py — the permanent outlook poster (2026-08-21).
Pure payload-builder tests; no network."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from post_outlook import build_payload, parse_scenario  # noqa: E402


def test_scenario_parses_and_keeps_colons_in_reading():
    s = parse_scenario("above:4600:bullish acceptance: continuation")
    assert s == {"when": "above", "level": 4600.0,
                 "reading": "bullish acceptance: continuation"}


def test_scenario_refusals():
    for bad in ("sideways:4600:x", "above:notanum:x", "above:4600:",
                "above:4600"):
        with pytest.raises(SystemExit):
            parse_scenario(bad)


def test_confidence_never_leaves_the_script():
    with pytest.raises(SystemExit):
        parse_scenario("above:4600:high confidence breakout")
    with pytest.raises(SystemExit):
        build_payload("GOLD", "weekly", "70% probability of a rally",
                      "Shyam", [], None)


def test_payload_matches_the_wire_contract():
    body = build_payload("gold", "weekly", "Dollar softening.", "Shyam",
                         ["above:4600:acceptance", "below:4460:shelf lost"],
                         200)
    assert body["symbol"] == "GOLD" and body["horizon"] == "weekly"
    assert body["valid_hours"] == 200 and len(body["scenarios"]) == 2
    assert set(body) == {"symbol", "horizon", "thesis", "source",
                         "scenarios", "valid_hours"}
    # omitted valid_hours stays omitted so the server defaults apply
    assert "valid_hours" not in build_payload(
        "GOLD", "monthly", "t", "s", [], None)


def test_blank_thesis_and_source_refused():
    with pytest.raises(SystemExit):
        build_payload("GOLD", "weekly", "  ", "Shyam", [], None)
    with pytest.raises(SystemExit):
        build_payload("GOLD", "weekly", "t", "", [], None)
    with pytest.raises(SystemExit):
        build_payload("GOLD", "daily", "t", "s", [], None)
