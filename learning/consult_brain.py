#!/usr/bin/env python3
"""
consult_brain.py  --  the read side. The bot imports this LATER (STEP 5), once a
cluster has earned it. Until then it changes nothing.

    from learning.consult_brain import ai_gate
    decision = ai_gate(cluster_key, live_take)   # live_take from a fresh vote, optional

ai_gate returns one of:
    "ALLOW"        -> cluster not proven yet (shadow). Trade as normal. DEFAULT.
    "ALLOW"        -> proven cluster, AI did not veto. Trade.
    "SOFT_VETO"    -> proven cluster + AI veto + trust below HARD threshold. Caller
                      may micro-size. Never silently block.
    "HARD_VETO"    -> proven cluster + AI veto + high trust. Caller may skip.

Fail-open ALWAYS: missing/old/corrupt scorecard -> "ALLOW". The AI can only ever
*remove* risk on clusters it has demonstrably earned, and never blocks A+ blindly
(enforce that in the caller: skip ai_gate for A+ grades).
"""
import json, os, time

BASE      = os.environ.get("BS7_BASE", "/home/shyam/brother_sniper_v7")
CARD      = os.path.join(BASE, "learning", "brain_scorecard.json")
MAX_AGE_S = 6 * 3600          # ignore a stale scorecard
HARD_TRUST = 0.75


def _load():
    try:
        st = os.stat(CARD)
        if time.time() - st.st_mtime > MAX_AGE_S:
            return None
        with open(CARD) as f:
            return json.load(f)
    except Exception:
        return None


def ai_gate(cluster_key, live_take=None):
    card = _load()
    if not card:
        return "ALLOW"
    if card.get("kill_check", "").startswith("NOT_PROVEN"):
        return "ALLOW"                       # engine failed its own kill test
    c = card.get("clusters", {}).get(cluster_key)
    if not c or not c.get("ai_actionable"):
        return "ALLOW"                       # cluster hasn't earned a say
    # only a fresh VETO can remove risk
    take = str(live_take).upper() if live_take is not None else None
    if take not in ("VETO", "FALSE", "0"):
        return "ALLOW"
    return "HARD_VETO" if c.get("trust", 0) >= HARD_TRUST else "SOFT_VETO"


if __name__ == "__main__":
    import sys
    ck = sys.argv[1] if len(sys.argv) > 1 else "ETHUSD|SELL|ASIA|TREND"
    print(ck, "->", ai_gate(ck, "VETO"))
