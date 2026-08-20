"""Front-contract resolver tests.

The failure this prevents is the one that has bitten this system repeatedly:
a symbol name that resolves to something the broker no longer serves returns
NOTHING, and nothing looks exactly like a quiet market. DXY_U6 expires in
September; without a resolver the dollar leg would go dark and every macro
row would read UNKNOWN with no one able to say why.

MT5 and flask aren't importable here, so the pure decision functions are
extracted from the source and exercised directly — the live lookup is only a
wrapper that feeds them names and expirations.
"""
import ast
import os
import re
import sys
import types
from datetime import datetime

SRC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "sniper_executor.py")
with open(SRC_PATH, encoding="utf-8") as f:
    SRC = f.read()
TREE = ast.parse(SRC)


def _load():
    mod = types.ModuleType("front")
    mod.re, mod.datetime = re, datetime
    src = re.search(r"_MONTH_CODES = .*?(?=\ndef _macro_front)", SRC, re.S).group(0)
    exec(compile(src, "front", "exec"), mod.__dict__)
    return mod


F = _load()
NOW = (datetime(2026, 8, 20) - datetime(1970, 1, 1)).total_seconds()


def ts(y, m, d=1):
    return (datetime(y, m, d) - datetime(1970, 1, 1)).total_seconds()


# ── reading the contract code ────────────────────────────────────────────────

def test_parses_cme_month_codes():
    assert F.parse_contract_expiry("DXY_U6", NOW) == ts(2026, 10)      # Sep -> ends Oct 1
    assert F.parse_contract_expiry("UST10Y_Z6", NOW) == ts(2027, 1)    # Dec -> next year
    assert F.parse_contract_expiry("DXY_F7", NOW) == ts(2027, 2)       # Jan 2027


def test_two_digit_years():
    assert F.parse_contract_expiry("DXY_U26", NOW) == ts(2026, 10)


def test_single_digit_year_rolls_into_the_future():
    """In 2029 a _H0 contract is March 2030, not March 2020."""
    later = (datetime(2029, 6, 1) - datetime(1970, 1, 1)).total_seconds()
    assert F.parse_contract_expiry("DXY_H0", later) == ts(2030, 4)


def test_ignores_anything_that_is_not_a_contract():
    for name in ("XAUUSD", "DXY", "DXY_SPOT", "DXY_CASH", "", None, "UST10Y_"):
        assert F.parse_contract_expiry(name, NOW) is None


# ── picking the front month ──────────────────────────────────────────────────

def test_picks_the_nearest_unexpired_contract():
    cands = [("DXY_U6", ts(2026, 9, 15)), ("DXY_Z6", ts(2026, 12, 15)),
             ("DXY_H7", ts(2027, 3, 15))]
    assert F.pick_front(cands, NOW) == "DXY_U6"


def test_skips_the_expired_one_after_the_roll():
    """The whole point: September passes, U6 dies, Z6 takes over silently."""
    after_roll = ts(2026, 9, 20)
    cands = [("DXY_U6", ts(2026, 9, 15)), ("DXY_Z6", ts(2026, 12, 15))]
    assert F.pick_front(cands, after_roll) == "DXY_Z6"


def test_all_expired_returns_none_not_a_dead_series():
    cands = [("DXY_U6", ts(2026, 9, 15)), ("DXY_M6", ts(2026, 6, 15))]
    assert F.pick_front(cands, ts(2027, 1, 5)) is None


def test_falls_back_to_the_code_when_broker_gives_no_expiration():
    """expiration_time == 0 must not read as 'expired at epoch'."""
    cands = [("DXY_U6", 0), ("DXY_Z6", 0)]
    assert F.pick_front(cands, NOW) == "DXY_U6"
    assert F.pick_front(cands, ts(2026, 10, 5)) == "DXY_Z6"


def test_empty_and_junk_are_handled():
    assert F.pick_front([], NOW) is None
    assert F.pick_front(None, NOW) is None
    assert F.pick_front([("NOTACONTRACT", 0)], NOW) is None


# ── the invariant that keeps this out of the order path ──────────────────────

def _fn(name):
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _calls(node, fname):
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == fname
               for n in ast.walk(node))


def test_execute_never_uses_the_resolver():
    """A resolver written for analytics must not change where orders go. If
    someone ever 'helpfully' routes /execute through it, a rolled contract
    would start redirecting real orders to a different instrument."""
    assert not _calls(_fn("execute"), "_resolve_symbol"), \
        "/execute must resolve through SYMBOL_MAP only"


def test_read_paths_do_use_the_resolver():
    for name in ("candles", "symbolspec_route", "_tick_spread"):
        assert _calls(_fn(name), "_resolve_symbol"), f"{name} bypasses the resolver"
