# EVIDENCE — heartbeat work order (brother-developer/docs/HEARTBEAT_WORK_ORDER_2026-09-05.md), v7 half, keep.
"""account_login + trade_mode in the v7 heartbeat: MEASURED from the bridge's
/health (asserted login since ISO-01), dropped when UNKNOWN, never guessed.
Append-only: no existing key renamed. Run from the repo root:
    python3 -m pytest tests/audit/2026-09-05_heartbeat -q"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.v7_status as vs  # noqa: E402

STATE = {"paused": False, "consecutive_losses": 0, "open_trades": {}}


def test_golden_heartbeat_carries_both_keys_when_supplied():
    hb = vs.build_heartbeat(STATE, {}, bridge_ok=True, account_login=52834417, trade_mode=0)
    assert hb["account_login"] == 52834417 and hb["trade_mode"] == 0
    assert hb["kind"] == "v7_heartbeat" and hb["bridge_ok"] is True      # nothing renamed


def test_golden_heartbeat_carries_neither_key_when_unknown():
    hb = vs.build_heartbeat(STATE, {}, bridge_ok=False)
    assert "account_login" not in hb and "trade_mode" not in hb           # UNKNOWN is absent, not 0 or ""


def test_golden_trade_mode_zero_is_kept_login_alone_is_kept():
    hb = vs.build_heartbeat(STATE, {}, account_login=52834417, trade_mode=None)
    assert hb["account_login"] == 52834417 and "trade_mode" not in hb     # an old bridge: login measured, mode unknown
    assert vs.build_heartbeat(STATE, {}, account_login=1, trade_mode=0)["trade_mode"] == 0   # 0 (demo) is a value


class _Resp:
    def __init__(self, code, body): self.status_code, self._b = code, body
    def json(self): return self._b


def _client(monkeypatch, code=200, body=None, exc=None):
    import core.ic_markets as icm
    monkeypatch.setenv("EXECUTOR_URL", "http://bridge/execute")
    class _Http:
        @staticmethod
        def get(url, timeout=5):
            if exc: raise exc
            return _Resp(code, body)
    monkeypatch.setattr(icm, "requests", _Http)
    return icm.ICMarketsClient()


def test_golden_get_account_measured_from_health(monkeypatch):
    c = _client(monkeypatch, 200, {"status": "ok", "account": 52834417, "balance": 11639.38, "equity": 11640.0, "trade_mode": 0})
    assert c.get_account() == {"login": 52834417, "trade_mode": 0, "balance": 11639.38}


def test_golden_get_account_is_unknown_on_503_missing_account_or_exception(monkeypatch):
    assert _client(monkeypatch, 503, {"status": "error", "msg": "mt5 disconnected"}).get_account() is None
    assert _client(monkeypatch, 200, {"status": "ok"}).get_account() is None
    assert _client(monkeypatch, exc=ConnectionError("down")).get_account() is None


def test_golden_old_bridge_without_trade_mode_gives_login_only(monkeypatch):
    a = _client(monkeypatch, 200, {"status": "ok", "account": 52834417, "balance": 1.0}).get_account()
    assert a["login"] == 52834417 and a["trade_mode"] is None


def test_golden_bot_call_site_passes_both_and_bridge_health_reports_trade_mode():
    bot = (ROOT / "bot.py").read_text(encoding="utf-8")
    i = bot.index("update_heartbeat(state, equity_guard.to_dict()")
    assert 'account_login=_acct.get("login")' in bot[i:i + 400] and 'trade_mode=_acct.get("trade_mode")' in bot[i:i + 400]
    assert "xtb.get_account()" in bot[i - 300:i]
    ex = (ROOT / "sniper_executor.py").read_text(encoding="utf-8")
    assert '"trade_mode":getattr(acc,"trade_mode",None)' in ex                  # work order item 1 (in the bridge since f8aaf5f)
