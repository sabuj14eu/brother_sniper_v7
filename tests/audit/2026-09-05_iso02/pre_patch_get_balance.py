"""EVIDENCE — verbatim copy of core/ic_markets.py:59-66 (ICMarketsClient.get_balance)
at commit c1618f5, kept so the ISO-02 reproduction survives the patch. Keep.
`requests`, `os`, `log` are module attributes so the fixture can inject fakes
without the real dependency."""
import logging
import os

requests = None            # injected by the test
log = logging.getLogger("iso02.pre_patch")


class PrePatchClient:
    executor_url = "http://bridge/execute"

    def get_balance(self):
        try:
            url = self.executor_url.replace("/execute","/health")
            r = requests.get(url, timeout=5)
            return float(r.json().get("balance", 1000.0))
        except Exception as e:
            fb = float(os.getenv("ACCOUNT_BALANCE","6000.0"))
            log.warning(f"[CT] get_balance FAILED ({type(e).__name__}) - using conservative fallback {fb}")
            return fb
