"""Bridge read-key tests.

sniper_executor.py imports MetaTrader5 and only runs on Windows, so the guard
is tested by extracting its source and exercising it against a fake `request`
— the logic under test is the comparison and the refusal, neither of which
needs MT5. The AST checks below then assert the guard is actually WIRED into
the routes, because a correct helper nobody calls is the exact failure mode
this project has been bitten by before.
"""
import ast
import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SRC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "sniper_executor.py")
with open(SRC_PATH, encoding="utf-8") as f:
    SRC = f.read()
TREE = ast.parse(SRC)

# Unconditionally gated (no live caller). /candles is gated only on live=1 —
# see test_candles_gate_is_live_only for why that is the correct boundary.
GATED = ("spread_route", "symbolspec_route")
UNGATED = ("health", "positions")


def _load_guard(key: str, header: str):
    """Rebuild _key_ok/_denied with a stub request carrying `header`."""
    mod = types.ModuleType("guard")
    mod.BRIDGE_KEY = key
    mod.request = types.SimpleNamespace(
        headers={"X-Bridge-Key": header} if header is not None else {})
    mod.jsonify = lambda d: d
    src = re.search(r"def _key_ok\(\).*?return jsonify\(\{[^}]*\}\), 401",
                    SRC, re.S).group(0)
    exec(compile(src, "guard", "exec"), mod.__dict__)
    return mod


# ── the comparison ───────────────────────────────────────────────────────────

def test_unset_key_means_auth_off():
    """Default deploy must behave exactly as before — nothing breaks on ship."""
    assert _load_guard("", "")._key_ok() is True
    assert _load_guard("", None)._key_ok() is True


def test_correct_key_passes():
    assert _load_guard("s3cret-value", "s3cret-value")._key_ok() is True


def test_wrong_or_missing_key_is_refused():
    for supplied in ("", None, "wrong", "s3cret-valu", "s3cret-value "):
        assert _load_guard("s3cret-value", supplied)._key_ok() is False


def test_refusal_never_echoes_the_key():
    g = _load_guard("s3cret-value", "wrong")
    body, code = g._denied()
    assert code == 401
    assert "s3cret-value" not in str(body) and "wrong" not in str(body)


def test_comparison_is_constant_time():
    """hmac.compare_digest, not ==: a timing oracle on a shared key is free
    to exploit and free to prevent."""
    assert "compare_digest" in SRC


# ── the wiring (a helper nobody calls protects nothing) ──────────────────────

def _fn(name):
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"route {name} not found")


def _calls_guard(node) -> bool:
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_key_ok"
               for n in ast.walk(node))


def test_market_data_routes_are_gated():
    for name in GATED:
        assert _calls_guard(_fn(name)), f"{name} does not check _key_ok"


def test_trading_path_routes_are_not_gated():
    """Locking /positions would put a key in the trading path to protect
    public market data — a bad trade, and an outage waiting to happen."""
    for name in UNGATED:
        assert not _calls_guard(_fn(name)), f"{name} must stay open"


def test_candles_gate_is_live_only():
    """The key must guard the FORMING-bar path and nothing else.

    Closed bars are read by the trading bot itself (bot.py fetch_atr), by
    analyst_eye and by the status dashboard — none of which send a key. A
    guard that ignored `live` would starve live ATR silently, because
    fetch_atr fails safe to None: no error, no alert, just slightly different
    trading. This asserts the condition still mentions `live`."""
    node = _fn("candles")
    for n in ast.walk(node):
        if not isinstance(n, ast.If):
            continue
        if any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_key_ok"
               for c in ast.walk(n.test)):
            names = {x.id for x in ast.walk(n.test) if isinstance(x, ast.Name)}
            assert "live" in names, "candles gate must be conditional on live=1"
            return
    raise AssertionError("candles has no _key_ok gate at all")


def test_trading_bot_never_asks_for_the_forming_bar():
    """If bot.py ever requests live=1 it lands on the authenticated path and
    would need a key — this fires first so that is a decision, not an outage."""
    with open(os.path.join(os.path.dirname(SRC_PATH), "bot.py"),
              encoding="utf-8") as f:
        bot = f.read()
    fetch = bot[bot.index("def fetch_atr("):]
    fetch = fetch[:fetch.index("\ndef ")]
    assert "live" not in fetch, "bot.py fetch_atr now uses the keyed path"


def test_guard_runs_before_any_mt5_work():
    """The refusal must be the first thing in the route, not after a broker
    call — otherwise an unauthenticated request still costs an MT5 round trip."""
    for name in GATED:
        node = _fn(name)
        stmts = [n for n in ast.walk(node)
                 if isinstance(n, ast.Call) and
                 getattr(getattr(n.func, "value", None), "id", "") == "mt5"]
        guard_line = min(n.lineno for n in ast.walk(node)
                         if isinstance(n, ast.Call) and
                         getattr(n.func, "id", "") == "_key_ok")
        for call in stmts:
            assert guard_line < call.lineno, f"{name}: mt5 work before the guard"


# ── the caller keeps working when the key is on ──────────────────────────────

def test_analytics_caller_sends_the_header():
    with open(os.path.join(os.path.dirname(SRC_PATH), "v7_counterfactual.py"),
              encoding="utf-8") as f:
        caller = f.read()
    assert "X-Bridge-Key" in caller and "BRIDGE_KEY" in caller
