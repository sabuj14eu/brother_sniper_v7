#!/usr/bin/env python3
"""
vote_worker.py  --  separate systemd service. Runs OUTSIDE the trade path.

Tails learning/signal_bus.jsonl, calls your EXISTING provider-agnostic voter in
filters/deepseek_vote.py (Gemini and/or DeepSeek via EYE_MODEL), and writes the
verdict to learning/eye_votes.jsonl with the REAL signal_id attached -- the #1 fix.

It does NOT reimplement the LLM call. It reuses your code. If a provider is dead
(DeepSeek "Insufficient Balance"), your fail-safe returns None -> we log take=None
and move on. The bot never waits on any of this.

Crash-safe resume: tracks byte offset in learning/.vote_worker.offset so a restart
doesn't re-vote old signals.
"""
import json, os, time, sys, traceback

BASE   = os.environ.get("BS7_BASE", "/home/shyam/brother_sniper_v7")
BUS    = os.path.join(BASE, "learning", "signal_bus.jsonl")
VOTES  = os.path.join(BASE, "learning", "eye_votes.jsonl")
OFFSET = os.path.join(BASE, "learning", ".vote_worker.offset")
POLL_S = float(os.environ.get("BS7_POLL_S", "2.0"))

# make filters/ importable
sys.path.insert(0, BASE)

# ---------------------------------------------------------------------------
# ADAPTER -- the ONE place to match your real function signature.
# Your handoff says deepseek_vote.py returns (take, confidence, reason).
# Edit the import + call below to match exactly, then never touch it again.
# ---------------------------------------------------------------------------
def _call_oracle(context):
    """Return (take, confidence, reason, provider). Must never raise."""
    try:
        from filters import deepseek_vote as dv
    except Exception as e:
        return (None, 0.0, f"import_fail:{e}", "none")

    provider = os.environ.get("EYE_MODEL", "gemini")
    # Try the most likely entry points in order; keep the first that works.
    for fn_name in ("deepseek_tiebreak", "ai_tiebreak", "vote", "deepseek_vote", "eye_vote", "get_vote"):
        fn = getattr(dv, fn_name, None)
        if not callable(fn):
            continue
        try:
            res = fn(context)                      # <-- if your sig differs, fix HERE
        except TypeError:
            try:
                res = fn(**context)                # fallback: kwargs style
            except Exception as e:
                return (None, 0.0, f"call_fail:{e}", provider)
        except Exception as e:
            return (None, 0.0, f"call_fail:{e}", provider)

        # normalize (take, confidence, reason) tuple OR dict
        if isinstance(res, (list, tuple)) and len(res) >= 1:
            take = res[0]
            conf = res[1] if len(res) > 1 else None
            reason = res[2] if len(res) > 2 else ""
            return (take, conf, reason, provider)
        if isinstance(res, dict):
            return (res.get("take"), res.get("confidence"),
                    res.get("reason", ""), res.get("provider", provider))
        return (res, None, "", provider)
    return (None, 0.0, "no_vote_fn_found", provider)


def _read_offset():
    try:
        return int(open(OFFSET).read().strip())
    except Exception:
        return 0


def _write_offset(n):
    try:
        with open(OFFSET, "w") as f:
            f.write(str(n))
    except Exception:
        pass


def _append_vote(rec):
    with open(VOTES, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def process_line(line):
    line = line.strip()
    if not line:
        return
    try:
        sig = json.loads(line)
    except json.JSONDecodeError:
        return
    sid = sig.get("signal_id")
    ctx = sig.get("context", {})
    if sid is not None and isinstance(ctx, dict):
        ctx["signal_id"] = sid   # so the AI's own _log_vote row carries the real sid
    take, conf, reason, prov = _call_oracle(ctx)
    _append_vote({
        "signal_id": sid,
        "provider":  prov,
        "take":      take,
        "confidence": conf,
        "reason":    reason,
        "ts":        int(time.time()),
        "context":   ctx,            # carried so scorer can cluster without bot.py
    })
    print(f"[VOTE] {sid} {prov} take={take} conf={conf}", flush=True)


def main():
    os.makedirs(os.path.dirname(VOTES), exist_ok=True)
    print(f"[vote_worker] up. bus={BUS}", flush=True)
    while True:
        try:
            if os.path.exists(BUS):
                off = _read_offset()
                size = os.path.getsize(BUS)
                if size < off:            # file rotated/truncated -> restart
                    off = 0
                if size > off:
                    with open(BUS, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(off)
                        for line in f:
                            process_line(line)
                        _write_offset(f.tell())
        except Exception:
            traceback.print_exc()
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
