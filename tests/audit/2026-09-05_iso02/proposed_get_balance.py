"""PROPOSED (not applied) replacement for core/ic_markets.py:59-66.
UNKNOWN is None. Never a number the broker did not say (ADR-005 spirit,
Freshness Law: a missing balance is NO EXECUTION, never a default)."""
import logging

requests = None            # injected by the test; the real module in core/
log = logging.getLogger("iso02.proposed")


class ProposedClient:
    executor_url = "http://bridge/execute"

    def get_balance(self):
        """Returns float or None. None means UNKNOWN: every caller must
        refuse to size, gate or grade on it."""
        try:
            url = self.executor_url.replace("/execute","/health")
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                log.warning(f"[CT] get_balance: bridge answered {r.status_code} — balance UNKNOWN")
                return None
            bal = r.json().get("balance")
            if bal is None:
                log.warning("[CT] get_balance: 200 without a balance field — UNKNOWN")
                return None
            return float(bal)
        except Exception as e:
            log.warning(f"[CT] get_balance FAILED ({type(e).__name__}) — balance UNKNOWN, no fallback")
            return None
