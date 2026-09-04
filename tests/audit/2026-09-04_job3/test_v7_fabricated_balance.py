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


def test_repro_ISO02a_bridge_503_mt5_disconnected_becomes_balance_1000(monkeypatch):
    """FINDING ISO-02 (P0). core/ic_markets.py:62 —
    `float(r.json().get("balance", 1000.0))`. The bridge's own "mt5
    disconnected" reply (sniper_executor.py:105, HTTP 503, no balance key)
    parses as JSON, so no exception fires and the DEFAULT 1000.0 is returned
    as if it were the account balance. VERDICT NOW: FAIL."""
    c = _client(monkeypatch, lambda *a, **k: _Resp(503, {"status": "error", "msg": "mt5 disconnected"}))
    assert c.get_balance() == 1000.0


def test_repro_ISO02b_bridge_unreachable_becomes_env_or_6000(monkeypatch):
    """core/ic_markets.py:63-66 — any exception returns ACCOUNT_BALANCE
    (default 6000.0) labelled a "conservative fallback". An unreachable
    bridge therefore reports a SIX THOUSAND dollar account. VERDICT NOW: FAIL."""
    def boom(*a, **k):
        raise ConnectionError("bridge down")
    monkeypatch.delenv("ACCOUNT_BALANCE", raising=False)
    assert _client(monkeypatch, boom).get_balance() == 6000.0
    monkeypatch.setenv("ACCOUNT_BALANCE", "25000")
    assert _client(monkeypatch, boom).get_balance() == 25000.0


@pytest.fixture
def bot_module(monkeypatch, tmp_path):
    """Import the REAL bot.py in a scratch cwd (state.json lands in tmp), with
    the required env present and the network unreachable."""
    for k, v in {"XTB_USER": "1", "XTB_PASS": "x", "WEBHOOK_SECRET": "testsecret",
                 "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                 "EXECUTOR_URL": "http://127.0.0.1:9/execute"}.items():
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


def test_repro_ISO02c_fabricated_balance_passes_the_fail_closed_margin_gate(bot_module, monkeypatch):
    """The gate at bot.py:829-836 is written fail-closed ("no balance or
    below floor -> skip") and the guard call at :839-841 feeds the balance to
    lot sizing. Both consume `xtb.get_balance()`, so with the bridge answering
    HTTP 503 the gate sees 1000.0 (> MARGIN_FLOOR 500.0) and lets the signal
    through, and the equity guard / calc_lot receive a number the broker never
    said. VERDICT NOW: FAIL (missing margin ≠ no execution)."""
    bot = bot_module
    import core.ic_markets as icm
    monkeypatch.setattr(icm.requests, "get",
                        lambda *a, **k: _Resp(503, {"status": "error", "msg": "mt5 disconnected"}))
    seen = {}

    def spy(balance, losses, max_losses=3):
        seen["balance"] = balance
        raise _Stop()                      # stop before any downstream machinery
    monkeypatch.setattr(bot.equity_guard, "check", spy)
    monkeypatch.setattr(bot, "is_news_blocking", lambda: (False, "", None))

    payload = {"secret": "testsecret", "symbol": "GOLD", "direction": "BUY",
               "entry": 2400.0, "sl": 2390.0, "tp": 2420.0,
               "signal_id": "SS-BUY-20260904120500", "system": "BSv9"}
    with pytest.raises(_Stop):
        bot.handle_signal(payload)
    assert seen["balance"] == 1000.0       # a balance the broker never reported reached the risk path


def test_repro_ISO02d_calc_lot_sizes_on_the_invented_balance(bot_module):
    """bot.py:328-338 — calc_lot(balance=...) is pure arithmetic on whatever
    number it is handed; 1000.0 vs 6000.0 changes the lot 6x. Nothing marks
    the number as UNKNOWN. VERDICT NOW: FAIL."""
    bot = bot_module
    lot_fake_small, _ = bot.calc_lot("GOLD", 2400.0, 2390.0, 1000.0, 0.01)
    lot_fake_big, _ = bot.calc_lot("GOLD", 2400.0, 2390.0, 6000.0, 0.01)
    assert lot_fake_small > 0 and lot_fake_big > 0
    assert lot_fake_big >= 5 * lot_fake_small
