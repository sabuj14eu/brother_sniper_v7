#!/usr/bin/env python3
"""
eye_scoreboard.py  --  score the swappable "eye" overrides PER MODEL (v7).

Read-only. Answers: of the BLOCKED signals each agent rescued (block -> take),
how many won, and what was the net PnL / profit factor. This is the
Gemini-vs-DeepSeek A/B. (The Claude arm lives in v18 -- see note at the end;
this script never touches v18.)

It reads two files, both under the v7 bot dir:
  learning/trades.jsonl      -- the joined trade log (outcome + breakdown)
  learning/eye_votes.jsonl   -- every eye vote, model-tagged (incl. declines)

An "override that executed" = a trades.jsonl row whose breakdown carries an eye
result (the eye only fires on blocked signals, and a row in trades.jsonl means
it executed -> therefore the eye flipped block->take). The model is read from the
"[model-name] ..." prefix the eye writes into the reason string; if that is
missing we fall back to joining on signal_id from eye_votes.jsonl.

Field names in trades.jsonl differ between builds, so PnL/outcome are detected
defensively and the detected keys are printed so you can sanity-check.
"""

import os
import re
import json
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
TRADES = os.path.join(HERE, "learning", "trades.jsonl")
VOTES = os.path.join(HERE, "learning", "eye_votes.jsonl")

PNL_KEYS = ["pnl_net", "pnl", "net_pnl", "profit", "net", "pl", "result_pnl"]
WIN_KEYS = ["outcome", "result", "status", "win"]
MODEL_TAG = re.compile(r"^\[([^\]]+)\]")


def load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def first_key(d, keys):
    for k in keys:
        if k in d and d[k] is not None:
            return k, d[k]
    return None, None


def get_pnl(row):
    _, v = first_key(row, PNL_KEYS)
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def is_win(row, pnl):
    k, v = first_key(row, WIN_KEYS)
    if v is not None:
        s = str(v).strip().lower()
        if s in ("win", "won", "tp", "true", "1", "profit", "w"):
            return True
        if s in ("loss", "lost", "sl", "false", "0", "l"):
            return False
    if pnl is not None:
        return pnl > 0
    return None


def find_eye_breakdown(row):
    """Return the eye result dict from a trade row, or None.
    breakdown may be at row['breakdown'] and the eye key is 'deepseek'
    (kept for hook compatibility) or 'eye'."""
    bd = row.get("breakdown")
    if not isinstance(bd, dict):
        return None
    for key in ("deepseek", "eye", "ai", "tiebreak"):
        v = bd.get(key)
        if isinstance(v, dict) and ("reason" in v or "take" in v or "confidence" in v):
            return v
    return None


def model_from_reason(reason):
    if not isinstance(reason, str):
        return None
    m = MODEL_TAG.match(reason.strip())
    return m.group(1) if m else None


def get_signal_id(row):
    for k in ("signal_id", "id", "sig_id"):
        if row.get(k):
            return row[k]
    return None


def fmt_money(x):
    return ("+" if x >= 0 else "") + ("%.2f" % x)


def main():
    trades = load_jsonl(TRADES)
    votes = load_jsonl(VOTES)

    # signal_id -> model, from the vote log (fallback when reason has no tag)
    vote_model = {}
    for v in votes:
        sid = v.get("signal_id")
        if sid and v.get("model"):
            vote_model[sid] = v["model"]

    print("=" * 64)
    print(" EYE OVERRIDE SCOREBOARD  (v7, per-model)")
    print("=" * 64)
    print("trades.jsonl rows: %d   eye_votes.jsonl rows: %d" %
          (len(trades), len(votes)))

    # show detected schema on a sample executed override
    sample_shown = False

    buckets = {}   # model -> dict(n, wins, losses, unknown, gross_win, gross_loss)

    for row in trades:
        eye = find_eye_breakdown(row)
        if not eye:
            continue
        # eye fired on this trade and the trade executed => it was an override
        reason = eye.get("reason", "")
        model = model_from_reason(reason) or vote_model.get(get_signal_id(row)) or "untagged"

        pnl = get_pnl(row)
        win = is_win(row, pnl)

        if not sample_shown:
            pk, pv = first_key(row, PNL_KEYS)
            wk, wv = first_key(row, WIN_KEYS)
            print("\n[schema check on first override row]")
            print("  detected PnL key   :", pk, "=", pv)
            print("  detected outcome key:", wk, "=", wv)
            print("  parsed model       :", model)
            print("  (verify these look right before trusting the table)\n")
            sample_shown = True

        b = buckets.setdefault(model, dict(n=0, wins=0, losses=0, unknown=0,
                                           gross_win=0.0, gross_loss=0.0,
                                           net=0.0, no_pnl=0))
        b["n"] += 1
        if pnl is None:
            b["no_pnl"] += 1
        else:
            b["net"] += pnl
            if pnl > 0:
                b["gross_win"] += pnl
            else:
                b["gross_loss"] += pnl
        if win is True:
            b["wins"] += 1
        elif win is False:
            b["losses"] += 1
        else:
            b["unknown"] += 1

    if not buckets:
        print("\nNo executed eye-overrides found yet.")
        print("Either the eye has not rescued any trade, or no key is set.")
        _print_vote_summary(votes)
        return

    print("-" * 64)
    print("%-22s %4s %4s %4s %8s %7s" %
          ("MODEL", "N", "W", "L", "NET", "PF"))
    print("-" * 64)
    for model, b in sorted(buckets.items()):
        decided = b["wins"] + b["losses"]
        wr = (100.0 * b["wins"] / decided) if decided else 0.0
        pf = (b["gross_win"] / abs(b["gross_loss"])) if b["gross_loss"] else float("inf")
        pf_s = "inf" if pf == float("inf") else "%.2f" % pf
        print("%-22s %4d %4d %4d %8s %7s   WR %.0f%%" %
              (model, b["n"], b["wins"], b["losses"], fmt_money(b["net"]), pf_s, wr))
        if b["no_pnl"]:
            print("    (%d rows had no readable PnL)" % b["no_pnl"])
    print("-" * 64)

    _print_vote_summary(votes)

    print("\nCLAUDE ARM (v18, reference only -- DO NOT run from here):")
    print("  On the Contabo box, in a SEPARATE shell:")
    print("    cd /home/shyam/brain-v2/brain && python3 truth_layer.py 2>&1 | head -25")
    print("  Compare its council_live WR / PnL to the Gemini & DeepSeek rows above.")
    print("  (Apples-to-oranges: v18 council is a full approver; the v7 eye only")
    print("   rescues near-miss blocks. Treat it as direction, not a clean A/B.)")


def _print_vote_summary(votes):
    if not votes:
        return
    by_model = {}
    for v in votes:
        m = v.get("model", "unknown")
        s = by_model.setdefault(m, dict(calls=0, took=0, declined=0, errors=0))
        s["calls"] += 1
        if v.get("error"):
            s["errors"] += 1
        elif v.get("take") is True:
            s["took"] += 1
        elif v.get("take") is False:
            s["declined"] += 1
    print("\nVOTE ACTIVITY (all eye calls, incl. declines & errors):")
    for m, s in sorted(by_model.items()):
        print("  %-22s calls=%d  took=%d  declined=%d  errors=%d" %
              (m, s["calls"], s["took"], s["declined"], s["errors"]))


if __name__ == "__main__":
    main()
