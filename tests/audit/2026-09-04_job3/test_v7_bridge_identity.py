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

from conftest import PREPATCH, V18_ACCOUNT, V7_ACCOUNT, FakeMT5, FakePosition, load_v7_bridge

SIGNAL = {"secret": "s3cret", "symbol": "GOLD", "direction": "BUY",
          "lot": 0.05, "sl": 2390.0, "tp": 2420.0, "signal_id": "SS-BUY-20260904120000",
          "account_id": str(V7_ACCOUNT)}          # ISO-03: required since 2026-09-05


# ─── Job 3 test 1: "A cannot execute on B" ─────────────────────────────────
def test_repro_ISO01_v7_bridge_executes_on_whatever_account_the_terminal_holds(v18_terminal, monkeypatch):
    """FINDING ISO-01 (P0, ADR-004) — MISROUTED ORDER.

    sniper_executor.py:64 and :76 call `mt5.initialize(path=V7_MT5_PATH, ...)`
    with NO login, NO server and NO post-attach identity check (:68-72, :79-83
    only log `acc.login`). The account is inferred from a file path. If the
    terminal at that path is logged into 52901228 (v18's account) the v7 arm
    trades v18's money and nothing in the code can notice.
    VERDICT at c1618f5: FAIL. Runs against the PREPATCH fixture; the repo
    file carries the ISO-01 patch since 2026-09-05 (golden fixtures in
    test_v7_iso01_patch_golden.py)."""
    ex = load_v7_bridge(v18_terminal, monkeypatch, path=PREPATCH)
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
    bridge's account to an expected one. VERDICT NOW: FAIL on the bot side
    (core/ic_markets.py is unpatched); the PREPATCH bridge supplies the 200."""
    ex = load_v7_bridge(v18_terminal, monkeypatch, path=PREPATCH)
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
def test_repro_ISO03_prepatch_bridge_ignored_account_id_and_placed_anonymous_orders(v7_terminal, monkeypatch):
    """FINDING ISO-03 (P0, ADR-004) as it was at c1618f5 (PREPATCH fixture): the
    /execute contract had no account field and the MT5 request had no magic."""
    ex = load_v7_bridge(v7_terminal, monkeypatch, path=PREPATCH, expected_login=None)
    r = ex.app.test_client().post("/execute", json={**SIGNAL, "account_id": "99999999"})
    assert r.get_json()["status"] == "ok"
    assert v7_terminal.orders[0]["account"] == V7_ACCOUNT
    assert "magic" not in v7_terminal.orders[0]


def test_golden_ISO03_unknown_or_missing_account_id_is_no_execution(v7_terminal, monkeypatch):
    """FIXED 2026-09-05: the request must name the account this bridge asserts."""
    ex = load_v7_bridge(v7_terminal, monkeypatch)
    c = ex.app.test_client()
    r = c.post("/execute", json={**SIGNAL, "account_id": "99999999"})
    assert r.status_code == 403 and r.get_json()["msg"] == "account_mismatch"
    r = c.post("/execute", json={k: v for k, v in SIGNAL.items() if k != "account_id"})
    assert r.status_code == 400 and r.get_json()["msg"] == "no_account_id"
    assert v7_terminal.orders == []


def test_golden_ISO03_right_account_executes_with_v7_magic(v7_terminal, monkeypatch):
    monkeypatch.setenv("V7_MAGIC_NUMBER", "70007")
    ex = load_v7_bridge(v7_terminal, monkeypatch)
    r = ex.app.test_client().post("/execute", json=SIGNAL)
    assert r.get_json()["status"] == "ok"
    assert v7_terminal.orders[0]["account"] == V7_ACCOUNT and v7_terminal.orders[0]["magic"] == 70007
    rows = ex.app.test_client().get("/positions").get_json()
    assert rows["count"] == 0 or all("magic" in p and "ours" in p for p in rows["positions"])


# ─── cross-arm management: v7 can close / modify a v18 position ────────────
def test_repro_ISO05_prepatch_close_and_modify_acted_on_any_ticket(shared_terminal, monkeypatch):
    """FINDING ISO-05 (P0) as it was at c1618f5 (PREPATCH fixture): /close and
    /modify sent the order with no ownership check."""
    ex = load_v7_bridge(shared_terminal, monkeypatch, path=PREPATCH, expected_login=None)
    c = ex.app.test_client()
    assert c.post("/modify", json={"secret": "s3cret", "ticket": 777001, "sl": 2395.0}).get_json()["status"] == "ok"
    assert c.post("/close", json={"secret": "s3cret", "ticket": 777001}).get_json()["status"] == "ok"
    assert [o["action"] for o in shared_terminal.orders] == [FakeMT5.TRADE_ACTION_SLTP, FakeMT5.TRADE_ACTION_DEAL]


def test_golden_ISO05_close_and_modify_refuse_positions_that_are_not_v7s(shared_terminal, monkeypatch):
    """FIXED 2026-09-05: a v18-magic position (magic 180000, comment 'v18') on
    the same account is refused with not_ours; nothing is sent."""
    ex = load_v7_bridge(shared_terminal, monkeypatch)
    c = ex.app.test_client()
    r = c.post("/modify", json={"secret": "s3cret", "ticket": 777001, "sl": 2395.0})
    assert r.status_code == 403 and r.get_json()["msg"] == "not_ours"
    r = c.post("/close", json={"secret": "s3cret", "ticket": 777001})
    assert r.status_code == 403 and r.get_json()["msg"] == "not_ours"
    assert shared_terminal.orders == []


def test_golden_ISO05_legacy_bs_comment_and_v7_magic_positions_stay_manageable(monkeypatch):
    """Positions opened before ISO-03 carry magic 0 and a BS_ comment; new ones
    carry V7_MAGIC. Both are v7's."""
    monkeypatch.setenv("V7_MAGIC_NUMBER", "70007")
    term = FakeMT5(V7_ACCOUNT, positions=[
        FakePosition(777002, "XAUUSD", magic=0, comment="BS_ab12cd34"),
        FakePosition(777003, "XAUUSD", magic=70007, comment="BS_ffffffff"),
    ])
    ex = load_v7_bridge(term, monkeypatch)
    c = ex.app.test_client()
    assert c.post("/modify", json={"secret": "s3cret", "ticket": 777002, "sl": 2395.0}).get_json()["status"] == "ok"
    assert c.post("/close", json={"secret": "s3cret", "ticket": 777003}).get_json()["status"] == "ok"
    assert len(term.orders) == 2
    rows = ex.app.test_client().get("/positions").get_json()["positions"]
    assert all(p["ours"] is True for p in rows)


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
