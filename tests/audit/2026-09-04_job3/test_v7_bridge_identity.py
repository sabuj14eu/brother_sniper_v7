# EVIDENCE — reproduces findings ISO-01 (misrouted order), ISO-03, ISO-04, ISO-05, keep.
"""Job 3 — v7 bridge (`sniper_executor.py`, Windows :5001) account isolation.

Naming contract for this suite:
  test_repro_*  — the test PASSES when the FINDING is reproduced. A green
                  repro means the isolation gap is STILL THERE. When a fix
                  lands, the repro must go red and be replaced by a golden
                  fixture (Job 10) with the inverted expectation.
  test_holds_*  — an invariant that holds today (verdict PASS).

Verdict vocabulary: PASS / FAIL / NOT RUNNABLE / UNKNOWN — never invented.
"""
from __future__ import annotations

from conftest import V18_ACCOUNT, V7_ACCOUNT, FakeMT5, FakePosition, load_v7_bridge

SIGNAL = {"secret": "s3cret", "symbol": "GOLD", "direction": "BUY",
          "lot": 0.05, "sl": 2390.0, "tp": 2420.0, "signal_id": "SS-BUY-20260904120000"}


# ─── Job 3 test 1: "A cannot execute on B" ─────────────────────────────────
def test_repro_ISO01_v7_bridge_executes_on_whatever_account_the_terminal_holds(v18_terminal, monkeypatch):
    """FINDING ISO-01 (P0, ADR-004) — MISROUTED ORDER.

    sniper_executor.py:64 and :76 call `mt5.initialize(path=V7_MT5_PATH, ...)`
    with NO login, NO server and NO post-attach identity check (:68-72, :79-83
    only log `acc.login`). The account is inferred from a file path. If the
    terminal at that path is logged into 52901228 (v18's account) the v7 arm
    trades v18's money and nothing in the code can notice.
    VERDICT NOW: FAIL (isolation broken)."""
    ex = load_v7_bridge(v18_terminal, monkeypatch)
    # the module attached by PATH only: no login was ever asserted
    assert all(c["login"] is None for c in v18_terminal.init_calls), v18_terminal.init_calls
    r = ex.app.test_client().post("/execute", json=SIGNAL)
    body = r.get_json()
    assert r.status_code == 200 and body["status"] == "ok", body
    assert len(v18_terminal.orders) == 1
    assert v18_terminal.orders[0]["account"] == V18_ACCOUNT      # the WRONG account took the order
    assert v18_terminal.orders[0]["symbol"] == "XAUUSD"


def test_repro_ISO01b_v7_health_reports_the_foreign_account_and_bot_client_accepts_it(v18_terminal, monkeypatch):
    """core/ic_markets.py:20-32 `connect()` sets `_login_ok=True` on ANY HTTP 200
    and only LOGS `data.get('account')` (:28). The bot never compares the
    bridge's account to an expected one. VERDICT NOW: FAIL."""
    ex = load_v7_bridge(v18_terminal, monkeypatch)
    h = ex.app.test_client().get("/health").get_json()
    assert h["account"] == V18_ACCOUNT                            # the bridge SAYS it is on 52901228 ...
    import core.ic_markets as icm
    monkeypatch.setenv("EXECUTOR_URL", "http://bridge/execute")

    class _R:
        status_code = 200
        def json(self): return h
    monkeypatch.setattr(icm.requests, "get", lambda *a, **k: _R())
    c = icm.ICMarketsClient()
    c.connect()
    assert c.login() is True                                      # ... and the bot calls that "logged in"


# ─── Job 3 test 8: "unknown account = NO EXECUTION" ────────────────────────
def test_repro_ISO03_v7_bridge_ignores_account_id_and_executes_for_unknown_account(v7_terminal, monkeypatch):
    """FINDING ISO-03 (P0, ADR-004). The /execute contract (sniper_executor.py:178-199)
    reads secret/symbol/direction/lot/sl/tp/signal_id. `account_id` is not a
    field: an order tagged for an account that does not exist is executed on
    whatever the terminal holds. VERDICT NOW: FAIL."""
    ex = load_v7_bridge(v7_terminal, monkeypatch)
    r = ex.app.test_client().post("/execute", json={**SIGNAL, "account_id": "99999999"})
    assert r.get_json()["status"] == "ok"
    assert v7_terminal.orders[0]["account"] == V7_ACCOUNT
    assert "account_id" not in v7_terminal.orders[0]
    assert "magic" not in v7_terminal.orders[0]                   # ISO-04: the order is anonymous, no magic


# ─── cross-arm management: v7 can close / modify a v18 position ────────────
def test_repro_ISO05_v7_close_and_modify_act_on_any_ticket_including_v18_magic(v18_terminal, monkeypatch):
    """FINDING ISO-05 (P0). /close (sniper_executor.py:299-323) and /modify
    (:372-386) look the ticket up with `positions_get(ticket=...)` and send the
    order with no magic / comment / account check. On a shared terminal v7
    closes v18's position with one POST. VERDICT NOW: FAIL."""
    ex = load_v7_bridge(v18_terminal, monkeypatch)
    c = ex.app.test_client()
    r = c.post("/modify", json={"secret": "s3cret", "ticket": 777001, "sl": 2395.0})
    assert r.get_json()["status"] == "ok"
    r = c.post("/close", json={"secret": "s3cret", "ticket": 777001})
    assert r.get_json()["status"] == "ok"
    acts = [o["action"] for o in v18_terminal.orders]
    assert acts == [FakeMT5.TRADE_ACTION_SLTP, FakeMT5.TRADE_ACTION_DEAL]
    assert all(o["account"] == V18_ACCOUNT for o in v18_terminal.orders)
    assert all(o.get("position") == 777001 for o in v18_terminal.orders)


# ─── Job 3 test 3: "same signal + same account = one execution" ────────────
def test_repro_ISO06_v7_bridge_has_no_idempotency_same_signal_id_twice_is_two_orders(v7_terminal, monkeypatch):
    """FINDING ISO-06 (P1). The bridge has no (account_id, signal_id) memory —
    dedupe exists only in the bot process (bot.py:284-300, keyed
    `symbol:signal_id`, no account). A retried/duplicated POST is two fills.
    VERDICT NOW: FAIL at the bridge; the bot-level key holds (see
    test_v7_guards_per_process.py)."""
    ex = load_v7_bridge(v7_terminal, monkeypatch)
    c = ex.app.test_client()
    assert c.post("/execute", json=SIGNAL).get_json()["status"] == "ok"
    assert c.post("/execute", json=SIGNAL).get_json()["status"] == "ok"
    assert len(v7_terminal.orders) == 2


# ─── Job 3 test 10: "invalid signature = NO EXECUTION" (v7 has a shared secret, not a signature) ─
def test_holds_v7_bridge_rejects_wrong_secret(v7_terminal, monkeypatch):
    """sniper_executor.py:184-185 — wrong `secret` is a 403 and no order.
    Verdict PASS, with the caveat that this is a static shared secret, not
    an Ed25519 signature: anyone holding it can execute (see ISO-01)."""
    ex = load_v7_bridge(v7_terminal, monkeypatch)
    r = ex.app.test_client().post("/execute", json={**SIGNAL, "secret": "wrong"})
    assert r.status_code == 403 and v7_terminal.orders == []


def test_holds_v7_bridge_refuses_when_terminal_is_dead(v7_terminal, monkeypatch):
    """sniper_executor.py:211-213 — no account_info → 503, no order. PASS."""
    ex = load_v7_bridge(v7_terminal, monkeypatch)
    v7_terminal.dead = True
    r = ex.app.test_client().post("/execute", json=SIGNAL)
    assert r.status_code == 503 and v7_terminal.orders == []
