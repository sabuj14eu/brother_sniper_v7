# EVIDENCE — Job 3 dual-MT5 isolation fixtures (2026-09-04), keep.
"""Fixtures for the Job 3 isolation suite (spec §45 Job 3, ADR-004/008/009).

Nothing here touches a broker, a terminal, a live checkout or the network:
`FakeMT5` is a stand-in for the `MetaTrader5` module that behaves like ONE
terminal logged into ONE account and records every `order_send`. The bridge
under test (`sniper_executor.py`) is loaded from the repo with that fake
injected, so the tests exercise the real route code byte-for-byte.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

V7_ROOT = Path(__file__).resolve().parents[3]
if str(V7_ROOT) not in sys.path:
    sys.path.insert(0, str(V7_ROOT))

V18_ACCOUNT = 52901228   # CLAUDE.md: v18 executor account
V7_ACCOUNT = 52834417    # CLAUDE.md: v7 bridge account

# The bridge as it was at c1618f5, BEFORE the ISO-01 patch (deployed on the box
# 2026-09-05 00:08:15 box time; repo copy patched the same day). The ISO-01
# reproductions run against this copy so the evidence stays re-runnable.
PREPATCH = Path(__file__).resolve().parent / "fixtures" / "sniper_executor_prepatch_c1618f5.py"


class FakeAccount:
    def __init__(self, login, balance=6000.0):
        self.login = login
        self.balance = balance
        self.equity = balance
        self.margin = 0.0
        self.margin_free = balance
        self.margin_level = 0.0
        self.company = "FakeBroker"
        self.currency = "USD"


class FakeTick:
    def __init__(self, bid=2400.0, ask=2400.3, t=1_700_000_000):
        self.bid, self.ask, self.time = bid, ask, t


class FakePosition:
    def __init__(self, ticket, symbol, ptype=0, volume=0.1, magic=0, comment="",
                 sl=2390.0, tp=2420.0, price_open=2400.0):
        self.ticket, self.symbol, self.type, self.volume = ticket, symbol, ptype, volume
        self.magic, self.comment, self.sl, self.tp = magic, comment, sl, tp
        self.price_open, self.price_current, self.profit = price_open, price_open, 0.0


class FakeResult:
    def __init__(self, retcode=10009, order=1, volume=0.1, price=2400.3, comment="done"):
        self.retcode, self.order, self.volume, self.price, self.comment = retcode, order, volume, price, comment


class FakeMT5(types.ModuleType):
    """One terminal, one account. `initialize()` attaches to whatever account
    the terminal holds — exactly what a path-only `mt5.initialize(path=...)`
    does on a real box. Every order_send is recorded with the account it hit."""

    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT = 2, 3
    ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP = 4, 5
    TRADE_ACTION_DEAL, TRADE_ACTION_PENDING, TRADE_ACTION_SLTP = 1, 5, 6
    ORDER_TIME_GTC, ORDER_FILLING_IOC = 0, 1
    TRADE_RETCODE_DONE = 10009
    TIMEFRAME_M1 = TIMEFRAME_M5 = TIMEFRAME_M15 = TIMEFRAME_M30 = 1
    TIMEFRAME_H1 = TIMEFRAME_H4 = TIMEFRAME_D1 = 2

    def __init__(self, login, balance=6000.0, positions=None):
        super().__init__("MetaTrader5")
        self.account = FakeAccount(login, balance)
        self.positions = list(positions or [])
        self.orders: list[dict] = []          # every order_send request, with the account it hit
        self.init_calls: list[dict] = []
        self._next_ticket = 900001
        self.dead = False                     # simulate a dropped terminal
        self.shutdown_calls = 0
        self.honour_login = False

    # --- terminal link ---
    def initialize(self, path=None, login=None, password=None, server=None, timeout=None):
        self.init_calls.append({"path": path, "login": login, "server": server})
        if self.honour_login and login is not None and int(login) != self.account.login:
            return False
        return True

    def shutdown(self):
        self.shutdown_calls += 1
        self.dead = True

    def account_info(self):
        return None if self.dead else self.account

    def last_error(self):
        return (0, "ok")

    # --- market data ---
    def symbol_select(self, symbol, enable=True):
        return True

    def symbol_info_tick(self, symbol):
        return FakeTick()

    def positions_get(self, symbol=None, ticket=None):
        out = self.positions
        if ticket is not None:
            out = [p for p in out if p.ticket == int(ticket)]
        if symbol is not None:
            out = [p for p in out if p.symbol == symbol]
        return list(out)

    def history_deals_get(self, *a, **k):
        return []

    def copy_rates_from_pos(self, *a, **k):
        return None

    # --- the only thing that matters: where the order lands ---
    def order_send(self, req):
        self.orders.append({"account": self.account.login, **dict(req)})
        t = self._next_ticket
        self._next_ticket += 1
        return FakeResult(order=t, volume=req.get("volume", 0.0))


def load_v7_bridge(fake: FakeMT5, monkeypatch, secret="s3cret", path=None, expected_login=V7_ACCOUNT):
    """Import the REAL sniper_executor.py with `fake` as its MetaTrader5.
    Each call gets a fresh module (module-level init runs against `fake`).
    `path`: an alternative copy of the file (PREPATCH, or a tmp copy).
    `expected_login`: value for V7_MT5_LOGIN (None = variable absent). The
    default is the v7 account, so a patched bridge on a v7 terminal executes."""
    monkeypatch.setenv("WEBHOOK_SECRET", secret)
    if expected_login is None:
        monkeypatch.delenv("V7_MT5_LOGIN", raising=False)
    else:
        monkeypatch.setenv("V7_MT5_LOGIN", str(expected_login))
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    name = f"sniper_executor_under_test_{id(fake)}_{id(path)}"
    spec = importlib.util.spec_from_file_location(name, Path(path) if path else V7_ROOT / "sniper_executor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.app.config["TESTING"] = True
    return mod


@pytest.fixture
def v18_terminal():
    """A terminal logged into the v18 account (52901228) — the WRONG account for v7."""
    return FakeMT5(V18_ACCOUNT, positions=[
        FakePosition(777001, "XAUUSD", magic=180000, comment="v18"),   # a v18-magic position
    ])


@pytest.fixture
def v7_terminal():
    return FakeMT5(V7_ACCOUNT)


@pytest.fixture
def shared_terminal():
    """The v7 account, but the terminal also holds a v18-magic position (a
    shared account, or a v18 order that landed here through ISO-09)."""
    return FakeMT5(V7_ACCOUNT, positions=[
        FakePosition(777001, "XAUUSD", magic=180000, comment="v18"),
    ])
