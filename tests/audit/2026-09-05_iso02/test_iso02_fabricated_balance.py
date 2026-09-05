"""ISO-02 golden fixtures (BUG-2026-09-04-ISO02-fabricated-balance, P0).

EVIDENCE tests run against the pre-patch copy and PASS today: they prove
the fabrication. CONTRACT tests run against the proposed function and
state the required behaviour. A source-pin test names the exact bot.py
lines the patch removes; it FAILS once the patch lands, which is the
signal to delete the pin, never the fixture. Expected verdicts are
explicit — nothing here is inferred."""
import re
from pathlib import Path
from types import SimpleNamespace

import pre_patch_get_balance as pre
import proposed_get_balance as prop

ROOT = Path(__file__).resolve().parents[3]


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _http(status=200, body=None, raise_exc=None):
    def get(url, timeout=5):
        if raise_exc:
            raise raise_exc
        return _Resp(status, body if body is not None else {})
    return SimpleNamespace(get=get)


# ── EVIDENCE: what the running code does ────────────────────────────────

def test_evidence_bridge_503_becomes_1000(monkeypatch):
    """The bridge's own 'mt5 disconnected' 503 carries no balance; the
    pre-patch client returns 1000.0 and calls it a balance."""
    pre.requests = _http(503, {"status": "error", "msg": "mt5 disconnected"})
    assert pre.PrePatchClient().get_balance() == 1000.0     # FABRICATED


def test_evidence_exception_becomes_env_account_balance(monkeypatch):
    monkeypatch.setenv("ACCOUNT_BALANCE", "6000.0")
    pre.requests = _http(raise_exc=ConnectionError("bridge unreachable"))
    assert pre.PrePatchClient().get_balance() == 6000.0     # FABRICATED, from .env


def test_evidence_200_without_balance_becomes_1000():
    pre.requests = _http(200, {"status": "ok"})
    assert pre.PrePatchClient().get_balance() == 1000.0     # FABRICATED


def test_evidence_the_fabricated_number_passes_the_margin_gate():
    """bot.py:832-836 — MARGIN_FLOOR 500.0; 1000.0 and 6000.0 both pass, so a
    dead bridge never trips the fail-closed gate."""
    src = (ROOT / "bot.py").read_text()
    m = re.search(r"MARGIN_FLOOR = ([0-9.]+)", src)
    assert m and 1000.0 >= float(m.group(1)) and 6000.0 >= float(m.group(1))


# ── CONTRACT: what the proposed code must do ─────────────────────────────

def test_contract_503_is_unknown():
    prop.requests = _http(503, {"status": "error", "msg": "mt5 disconnected"})
    assert prop.ProposedClient().get_balance() is None


def test_contract_exception_is_unknown_never_env(monkeypatch):
    monkeypatch.setenv("ACCOUNT_BALANCE", "6000.0")
    prop.requests = _http(raise_exc=ConnectionError("bridge unreachable"))
    assert prop.ProposedClient().get_balance() is None


def test_contract_200_without_balance_is_unknown():
    prop.requests = _http(200, {"status": "ok"})
    assert prop.ProposedClient().get_balance() is None


def test_contract_200_with_balance_is_the_balance():
    prop.requests = _http(200, {"status": "ok", "balance": 11639.38, "account": 52834417})
    assert prop.ProposedClient().get_balance() == 11639.38


def test_contract_the_margin_gate_already_handles_none():
    """bot.py:833-836 — `if _bal_gate is None or _bal_gate < MARGIN_FLOOR: skip`.
    With None from the patched client, the first gate refuses. PASS today."""
    src = (ROOT / "bot.py").read_text()
    assert "_bal_gate is None or _bal_gate < MARGIN_FLOOR" in src


# ── GOLDEN PIN (patch landed 2026-09-05): the fabrication lines are GONE ──
def test_golden_fabrication_lines_are_gone():
    """Inverse of the pre-patch pin (its text is in git history). At c1618f5 the
    fallbacks lived at core/ic_markets.py:62, :64 and bot.py:840, :595, :1278,
    :1309, :1319, :1385. None of them may come back."""
    ic = (ROOT / "core" / "ic_markets.py").read_text()
    bot = (ROOT / "bot.py").read_text()
    assert 'get("balance", 1000.0)' not in ic
    assert 'os.getenv("ACCOUNT_BALANCE"' not in ic
    assert "except Exception: balance=1000.0" not in bot
    assert "except Exception: bal=1000.0" not in bot
    assert "except Exception: bal=0" not in bot
    assert "balance=_bal_gate" in bot                       # the guard reuses the gate's measured number


# ── CONTRACT ON THE REAL CLIENT (was: on proposed_get_balance.py) ─────────
def _real_client(monkeypatch, http):
    import core.ic_markets as icm
    monkeypatch.setenv("EXECUTOR_URL", "http://bridge/execute")
    monkeypatch.setattr(icm, "requests", http)
    return icm.ICMarketsClient()


def test_golden_real_client_503_is_unknown(monkeypatch):
    assert _real_client(monkeypatch, _http(503, {"status": "error", "msg": "mt5 disconnected"})).get_balance() is None


def test_golden_real_client_exception_is_unknown_never_env(monkeypatch):
    monkeypatch.setenv("ACCOUNT_BALANCE", "6000.0")
    assert _real_client(monkeypatch, _http(raise_exc=ConnectionError("down"))).get_balance() is None


def test_golden_real_client_200_without_balance_is_unknown(monkeypatch):
    assert _real_client(monkeypatch, _http(200, {"status": "ok"})).get_balance() is None


def test_golden_real_client_200_with_balance_is_the_balance(monkeypatch):
    assert _real_client(monkeypatch, _http(200, {"status": "ok", "balance": 11639.38, "account": 52834417})).get_balance() == 11639.38
