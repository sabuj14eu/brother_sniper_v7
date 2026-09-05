# EVIDENCE — reproduces finding ISO-02 (fabricated balance), keep.
"""Job 3 test 9 — "missing margin = NO EXECUTION" on the v7 arm.

The bot's balance reader invents a number when the bridge cannot answer.
That number then passes the fail-closed margin gate and sizes the lot.
"""
from __future__ import annotations

import os
import sys

import pytest

from conftest import V7_ROOT


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._p


def _client(monkeypatch, get):
    import core.ic_markets as icm
    monkeypatch.setenv("EXECUTOR_URL", "http://bridge/execute")
    monkeypatch.setattr(icm.requests, "get", get)
    return icm.ICMarketsClient()


def test_golden_ISO02a_bridge_503_mt5_disconnected_is_unknown(monkeypatch):
    """FINDING ISO-02 (P0), FIXED 2026-09-05. At c1618f5 core/ic_markets.py:62
    turned the bridge's own 503 into balance 1000.0 (reproduced in this
    test's git history). Now it is None = UNKNOWN."""
    c = _client(monkeypatch, lambda *a, **k: _Resp(503, {"status": "error", "msg": "mt5 disconnected"}))
    assert c.get_balance() is None


def test_golden_ISO02b_bridge_unreachable_is_unknown_whatever_the_env_says(monkeypatch):
    """core/ic_markets.py:63-66 at c1618f5 returned ACCOUNT_BALANCE (6000.0 on
    the box). Now None, and ACCOUNT_BALANCE is dead config."""
    def boom(*a, **k):
        raise ConnectionError("bridge down")
    monkeypatch.delenv("ACCOUNT_BALANCE", raising=False)
    assert _client(monkeypatch, boom).get_balance() is None
    monkeypatch.setenv("ACCOUNT_BALANCE", "25000")
    assert _client(monkeypatch, boom).get_balance() is None


@pytest.fixture
def bot_module(monkeypatch, tmp_path):
    """Import the REAL bot.py in a scratch cwd (state.json lands in tmp), with
    the required env present and the network unreachable."""
    for k, v in {"XTB_USER": "1", "XTB_PASS": "x", "WEBHOOK_SECRET": "testsecret",
                 "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                 "EXECUTOR_URL": "http://127.0.0.1:9/execute",
                 "TRUSTED_IPS": "127.0.0.1"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("bot", None)
    try:
        import bot  # noqa: F401
    except Exception as e:  # pragma: no cover
        pytest.skip(f"NOT RUNNABLE: bot.py not importable here ({type(e).__name__}: {e})")
    monkeypatch.setattr(bot, "send_telegram", lambda *a, **k: None)
    yield bot
    sys.modules.pop("bot", None)


class _Stop(Exception):
    pass


def test_golden_ISO02c_unknown_balance_stops_at_the_margin_gate(bot_module, monkeypatch):
    """At c1618f5 the bridge's 503 became 1000.0, passed the fail-closed gate
    (bot.py:829-836) and reached the equity guard and lot sizing (reproduced
    in this test's git history). Now the gate refuses on None and the guard
    is never called."""
    bot = bot_module
    import core.ic_markets as icm
    monkeypatch.setattr(icm.requests, "get",
                        lambda *a, **k: _Resp(503, {"status": "error", "msg": "mt5 disconnected"}))
    seen = {}

    def spy(balance, losses, max_losses=3):
        seen["balance"] = balance
        raise _Stop()
    monkeypatch.setattr(bot.equity_guard, "check", spy)
    monkeypatch.setattr(bot, "is_news_blocking", lambda: (False, "", None))

    payload = {"secret": "testsecret", "symbol": "GOLD", "direction": "BUY",
               "entry": 2400.0, "sl": 2390.0, "tp": 2420.0,
               "signal_id": "SS-BUY-20260904120500", "system": "BSv9"}
    r = bot.handle_signal(payload)
    assert r == {"status": "skipped", "msg": "margin floor / balance unreadable"}
    assert seen == {}                      # the guard never saw a number


def test_golden_ISO02e_health_and_status_report_unknown_not_a_number(bot_module, monkeypatch):
    """bot.py /health and /status with the bridge down: balance null,
    balance_state UNKNOWN, health 503 (Iron Rule 6), summary says UNKNOWN."""
    bot = bot_module
    import core.ic_markets as icm
    monkeypatch.setattr(icm.requests, "get",
                        lambda *a, **k: _Resp(503, {"status": "error", "msg": "mt5 disconnected"}))
    c = bot.app.test_client()
    h = c.get("/health")
    assert h.status_code == 503
    body = h.get_json()
    assert body["balance"] is None and body["balance_state"] == "UNKNOWN" and body["status"] == "degraded"
    s = c.get("/status?secret=testsecret").get_json()
    assert s["balance"] is None and s["balance_state"] == "UNKNOWN" and "Equity: UNKNOWN" in s["equity"]


def test_note_calc_lot_is_linear_in_balance_which_is_why_unknown_must_never_reach_it(bot_module):
    """bot.py calc_lot(balance=...) is pure arithmetic on whatever number it is
    handed; 1000.0 vs 6000.0 changes the lot 6x. That is the reason the gate
    above must stop None before sizing (it now does)."""
    bot = bot_module
    lot_fake_small, _ = bot.calc_lot("GOLD", 2400.0, 2390.0, 1000.0, 0.01)
    lot_fake_big, _ = bot.calc_lot("GOLD", 2400.0, 2390.0, 6000.0, 0.01)
    assert lot_fake_small > 0 and lot_fake_big > 0
    assert lot_fake_big >= 5 * lot_fake_small
