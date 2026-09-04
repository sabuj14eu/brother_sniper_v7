# EVIDENCE — Job 3 tests 3/4/6/7 on the v7 arm, keep.
"""Which v7 guard objects carry an account identity, and which are merely
"one per process" — the property that only holds while one process == one
account, which the box flags (not this repo) decide."""
from __future__ import annotations

import inspect

from risk.equity_guard import EquityGuard, EquityState


# ─── Job 3 tests 6 + 7: daily loss isolates per object ─────────────────────
def test_holds_two_equity_guards_do_not_share_state():
    """risk/equity_guard.py:29-34 — each EquityGuard owns its EquityState; a
    hard stop on one leaves the other allowed. PASS at object level."""
    a, b = EquityGuard(), EquityGuard()
    a.update_balance(6000.0)
    b.update_balance(6000.0)
    a.eq.hard_stopped = True
    assert a.check(6000.0, 0).allowed is False
    assert b.check(6000.0, 0).allowed is True


def test_repro_ISO07_equity_guard_carries_no_account_identity():
    """FINDING ISO-07 (P1, ADR-004/009). EquityState (risk/equity_guard.py:18-22)
    has no account field: the daily-loss counter is per PROCESS, persisted in
    state.json (bot.py:208) which also has no account key. If the bridge is
    repointed at another account the counter silently carries over.
    VERDICT NOW: FAIL (identity missing), PASS (isolation by process)."""
    fields = set(EquityState.__dataclass_fields__)
    assert not {"account_id", "account", "login"} & fields, fields
    assert "day_open_balance" in fields and "peak_balance" in fields
    assert EquityState().peak_balance == 1000.0          # a default balance, not a measured one


# ─── Job 3 tests 3 + 4: dedupe key ──────────────────────────────────────────
def test_repro_ISO08_bot_dedupe_key_is_symbol_signal_id_without_account():
    """FINDING ISO-08 (P1, ADR-004: uniqueness is (account_id, signal_id)).
    bot.py:284-288 `_make_sid` → f"{symbol}:{signal_id}". Read from source so
    the test needs no bot import. VERDICT NOW: FAIL (key lacks account)."""
    from conftest import V7_ROOT
    src = (V7_ROOT / "bot.py").read_text(encoding="utf-8")
    i = src.index("def _make_sid(p):")
    body = src[i:i + 500]
    assert 'f"{p.get(\'symbol\',\'\')}:{p[\'signal_id\']}"' in body
    assert "account" not in body
