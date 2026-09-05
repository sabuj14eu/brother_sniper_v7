"""W2-02 / ISO-02 — EquityGuard.check(None) BLOCKS, never raises, and touches
no state. Pre-patch evidence (git history of this file): update_balance(None)
raised TypeError at risk/equity_guard.py:42. Patched 2026-09-05."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def test_golden_check_none_blocks_without_touching_state():
    from risk.equity_guard import EquityGuard

    g = EquityGuard()
    g.update_balance(6000.0)
    before = g.to_dict()
    res = g.check(None, 0)
    assert res.allowed is False and "UNKNOWN" in res.block_reason and res.risk_pct == 0.0
    assert res.tier_hit == "unknown"
    assert g.to_dict() == before                      # nothing updated from a fabricated number


def test_golden_update_balance_none_is_a_no_op():
    from risk.equity_guard import EquityGuard

    g = EquityGuard()
    g.update_balance(6000.0)
    before = g.to_dict()
    g.update_balance(None)
    assert g.to_dict() == before


def test_golden_status_summary_none_says_unknown_not_zero():
    from risk.equity_guard import EquityGuard

    g = EquityGuard()
    g.update_balance(6000.0)
    s = g.status_summary(None)
    assert "Equity: UNKNOWN" in s and "Day PnL: UNKNOWN" in s and "Week PnL: UNKNOWN" in s
    assert "$0" not in s and "Risk: 0%" in s
    assert g.eq.peak_balance == 6000.0                 # peak still the last MEASURED value


def test_holds_measured_balance_path_unchanged():
    from risk.equity_guard import EquityGuard

    g = EquityGuard()
    r = g.check(6000.0, 0)
    assert r.allowed is True and r.risk_pct == 0.01 and g.eq.peak_balance == 6000.0
