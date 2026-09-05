"""W2-02 — EquityGuard.check(None) must BLOCK, never raise. Evidence on the
real guard (pre-patch): update_balance(None) raises TypeError at
risk/equity_guard.py:42. Contract on the proposed ordering: the None guard
runs before update_balance and returns the existing _block shape."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def test_evidence_pre_patch_check_none_raises_typeerror():
    from risk.equity_guard import EquityGuard

    with pytest.raises(TypeError):
        EquityGuard().check(None, 0)


def test_contract_proposed_ordering_blocks_without_touching_state():
    from risk.equity_guard import EquityGuard

    class Proposed(EquityGuard):
        def check(self, bal, consecutive_losses, max_losses=3):
            if bal is None:
                return self._block("unknown", 0, 0, 0, "balance UNKNOWN — bridge unreadable, no execution")
            return super().check(bal, consecutive_losses, max_losses)

    g = Proposed()
    before = g.to_dict()
    res = g.check(None, 0)
    assert res.allowed is False and "UNKNOWN" in res.block_reason
    assert g.to_dict() == before                      # nothing updated from a fabricated number
