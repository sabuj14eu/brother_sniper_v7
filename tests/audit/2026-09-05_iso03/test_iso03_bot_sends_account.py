# EVIDENCE — golden fixture for ISO-03 on the bot side, keep.
"""ISO-03: the bot names the account with every order. core/ic_markets.py
open_trade() sends account_id = V7_MT5_LOGIN; when the env is missing the
field is empty and the bridge answers no_account_id (fail closed)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Resp:
    status_code = 200
    headers = {"content-type": "application/json"}

    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


def _client(monkeypatch, capture, reply):
    import core.ic_markets as icm
    monkeypatch.setenv("EXECUTOR_URL", "http://bridge/execute")
    monkeypatch.setattr(icm.requests, "post", lambda url, json, timeout: capture.update(url=url, payload=json) or _Resp(reply))
    c = icm.ICMarketsClient()
    monkeypatch.setattr(c, "is_market_open", lambda symbol: True)   # the fixture is not about the calendar
    return c


def test_golden_ISO03_bot_sends_its_asserted_account_with_every_order(monkeypatch):
    monkeypatch.setenv("V7_MTC_UNUSED", "x")
    monkeypatch.setenv("V7_MT5_LOGIN", "52834417")
    cap = {}
    c = _client(monkeypatch, cap, {"status": "ok", "order_id": 1, "volume": 0.05})
    r = c.open_trade("GOLD", "BUY", 0.05, 2390.0, 2420.0, comment="BS_test")
    assert r["status"] is True
    assert cap["payload"]["account_id"] == "52834417" and cap["payload"]["signal_id"] == "BS_test"


def test_golden_ISO03_missing_env_sends_empty_account_and_the_bridge_refusal_is_reported(monkeypatch):
    monkeypatch.delenv("V7_MT5_LOGIN", raising=False)
    cap = {}
    c = _client(monkeypatch, cap, {"status": "error", "msg": "no_account_id"})
    r = c.open_trade("GOLD", "BUY", 0.05, 2390.0, 2420.0, comment="BS_test")
    assert cap["payload"]["account_id"] == ""
    assert r["status"] is False and r["errorDescr"] == "no_account_id"
