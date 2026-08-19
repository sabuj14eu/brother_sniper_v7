"""v7's view vs the broker's view — labelled, never corrected (read-only).

Three independent facts exist per market and the desk kept blending them:

    V7 VERDICT   what v7 most recently DECIDED about new signals
    V7 TRACKED   the position v7 believes it is managing (state.json slot)
    BROKER       what is actually open or pending at MT5

They disagree for good reasons far more often than for bad ones, and the
two live examples that prompted this module are both innocent:

  US30   verdict REJECT SELL, broker holds 2 SELLs. A rejection refuses a
         NEW signal; it never closes an existing trade. Positions opened
         before the verdict are simply history. Also: v7 holds at most ONE
         position per asset class, so two on one symbol cannot both be v7's.

  SILVER verdict BUY approved, broker shows a PENDING SELL LIMIT. v7 cannot
         have placed it: the bridge sends TRADE_ACTION_DEAL only
         (sniper_executor.py:215-226) — market orders, never pendings. So
         that order came from somewhere else.

This module LABELS and EXPLAINS. It never cancels, closes, modifies or
adopts anything, and an unexplained state is surfaced for a human rather
than repaired automatically — the last thing an unattended repair loop
should touch is a live position it does not understand.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.order_comment import is_ours, matches

# per-position labels
CONSISTENT = "CONSISTENT"                    # v7 tracks it, sides agree
DIRECTION_MISMATCH = "DIRECTION_MISMATCH"    # v7 tracks it, sides disagree
ORPHAN = "ORPHAN"                            # v7's comment, v7 not tracking it
NOT_PLACED_BY_V7 = "NOT_PLACED_BY_V7"        # provably someone else's
PROVENANCE_UNKNOWN = "PROVENANCE_UNKNOWN"    # no comment field to judge by
# symbol-level extras
GHOST = "GHOST"                              # v7 tracks it, broker has not
FLAT = "FLAT"                                # nothing open, nothing tracked
MIXED_OWNERSHIP = "MIXED_OWNERSHIP"          # some v7's, some not
EXPLAINED_BY_HISTORY = "EXPLAINED_BY_HISTORY"
UNEXPLAINED = "UNEXPLAINED"


def _ts(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v / 1000 if v > 4102444800 else v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _side(v):
    # NB: `v or ""` would erase MT5's integer 0 for BUY. Compare explicitly.
    s = "" if v is None else str(v).strip().upper()
    if s in ("0", "BUY", "POSITION_TYPE_BUY"):
        return "BUY"
    if s in ("1", "SELL", "POSITION_TYPE_SELL"):
        return "SELL"
    return ""


def classify_position(pos: dict, tracked: dict | None) -> dict:
    """One broker position against what v7 thinks it is managing."""
    comment = pos.get("comment")
    # MT5 encodes BUY as integer 0 — falsy — so `type or direction` would
    # silently drop every BUY. Pick the first key that is actually present.
    raw_side = pos["type"] if "type" in pos else pos.get("direction")
    side = _side(raw_side)
    ticket = pos.get("ticket")
    pending = bool(pos.get("pending")) or "LIMIT" in str(pos.get("type", "")).upper() \
        or "STOP" in str(pos.get("type", "")).upper()

    if pending:
        return {"ticket": ticket, "side": side, "label": NOT_PLACED_BY_V7,
                "why": "a resting pending order — v7 sends market orders only "
                       "(TRADE_ACTION_DEAL), so this came from elsewhere"}

    if tracked and (ticket is not None and ticket == tracked.get("order_id")
                    or matches(comment, tracked.get("signal_id"))):
        t_side = _side(tracked.get("direction"))
        if t_side and side and t_side != side:
            return {"ticket": ticket, "side": side, "label": DIRECTION_MISMATCH,
                    "why": f"v7 tracks this ticket as {t_side} but the broker "
                           f"reports {side} — do not act on it, verify by hand"}
        return {"ticket": ticket, "side": side, "label": CONSISTENT,
                "why": "v7 is managing this position"}

    if comment in (None, ""):
        return {"ticket": ticket, "side": side, "label": PROVENANCE_UNKNOWN,
                "why": "no comment reported, so who placed it cannot be told "
                       "from here — UNKNOWN, not 'not ours'"}

    if not is_ours(comment):
        return {"ticket": ticket, "side": side, "label": NOT_PLACED_BY_V7,
                "why": "no v7 order comment — placed by hand or another system"}

    return {"ticket": ticket, "side": side, "label": ORPHAN,
            "why": "carries a v7 comment but v7 is not tracking it — an "
                   "earlier fill v7 lost track of (the timeout lie)"}


def reconcile_symbol(symbol: str, verdict: dict | None, tracked: dict | None,
                     positions: list[dict] | None) -> dict:
    """The three facts for one market, with a label that explains them."""
    positions = [p for p in (positions or []) if isinstance(p, dict)]
    rows = [{**classify_position(p, tracked), "volume": p.get("volume"),
             "entry": p.get("price_open"), "sl": p.get("sl"), "tp": p.get("tp")}
            for p in positions]
    labels = [r["label"] for r in rows]

    v_ts = _ts((verdict or {}).get("ts"))
    v_side = _side((verdict or {}).get("direction"))
    v_stance = (verdict or {}).get("stance")
    opened = _ts((tracked or {}).get("opened_at"))

    out = {"symbol": symbol, "positions": rows,
           "v7_stance": v_stance or "UNKNOWN",
           "v7_gate": (verdict or {}).get("gate"),
           "v7_side": v_side or None,
           "tracked_ticket": (tracked or {}).get("order_id"),
           "ours_n": sum(1 for l in labels if l in (CONSISTENT, ORPHAN, DIRECTION_MISMATCH)),
           "foreign_n": sum(1 for l in labels if l == NOT_PLACED_BY_V7),
           "unknown_n": sum(1 for l in labels if l == PROVENANCE_UNKNOWN)}

    # v7 believes it holds something the broker does not report
    if tracked and not any(r["label"] in (CONSISTENT, DIRECTION_MISMATCH) for r in rows):
        out["label"] = GHOST
        out["why"] = ("v7 is tracking a position the broker does not report — "
                      "closed outside v7, or the feed is stale. Verify before acting.")
        return out

    if not rows:
        out["label"] = FLAT
        out["why"] = "nothing open and nothing tracked"
        return out

    if DIRECTION_MISMATCH in labels:
        out["label"] = DIRECTION_MISMATCH
        out["why"] = "v7's side disagrees with the broker's on a tracked ticket"
        return out

    if ORPHAN in labels:
        out["label"] = ORPHAN
        out["why"] = ("a v7-commented position v7 is not tracking — the "
                      "monitor's SLOT-RECON sweep adopts these when a slot is free")
        return out

    if all(l == NOT_PLACED_BY_V7 for l in labels):
        out["label"] = NOT_PLACED_BY_V7
        out["why"] = ("nothing here was placed by v7 — its stance says nothing "
                      "about these orders")
        return out

    if out["ours_n"] and (out["foreign_n"] or out["unknown_n"]):
        out["label"] = MIXED_OWNERSHIP
        out["why"] = (f"v7 is managing {out['ours_n']} of these; "
                      f"{out['foreign_n'] + out['unknown_n']} came from elsewhere "
                      f"or cannot be attributed — v7 holds at most ONE position "
                      f"per asset class, so the rest are never its own")
        return out

    if PROVENANCE_UNKNOWN in labels:
        out["label"] = PROVENANCE_UNKNOWN
        out["why"] = "some orders here cannot be attributed from the data available"
        return out

    # every position is one v7 tracks; does the newest verdict contradict it?
    if v_side and any(r["side"] and r["side"] != v_side for r in rows):
        if v_stance in ("REJECT", "WAIT") or (opened and v_ts and opened < v_ts):
            out["label"] = EXPLAINED_BY_HISTORY
            out["why"] = ("the position predates the latest verdict — a refused "
                          "or waiting signal declines a NEW trade, it never "
                          "closes an open one")
            return out
        out["label"] = UNEXPLAINED
        out["why"] = ("an open position contradicts v7's latest verdict and the "
                      "timing does not explain it — surface for a human")
        return out

    out["label"] = CONSISTENT
    out["why"] = "v7's view and the broker's agree"
    return out


def reconcile_all(verdicts: dict, tracked_slots: dict,
                  positions: list[dict] | None) -> list[dict]:
    """Every market mentioned by v7 or by the broker.

    `verdicts`      symbol -> latest verdict dict
    `tracked_slots` state.json open_trades (asset_class -> trade or None)
    `positions`     broker rows, each with a `symbol`
    """
    by_symbol: dict = {}
    for p in positions or []:
        if isinstance(p, dict) and p.get("symbol"):
            by_symbol.setdefault(str(p["symbol"]).upper(), []).append(p)
    tracked_by_symbol = {str(t.get("symbol", "")).upper(): t
                         for t in (tracked_slots or {}).values() if t}

    symbols = set(by_symbol) | set(tracked_by_symbol) | {
        str(s).upper() for s in (verdicts or {})}
    out = [reconcile_symbol(s, (verdicts or {}).get(s) or (verdicts or {}).get(s.upper()),
                            tracked_by_symbol.get(s), by_symbol.get(s))
           for s in sorted(symbols)]
    # anything a human should look at floats to the top
    rank = {UNEXPLAINED: 0, DIRECTION_MISMATCH: 1, GHOST: 2, ORPHAN: 3,
            MIXED_OWNERSHIP: 4, PROVENANCE_UNKNOWN: 5, NOT_PLACED_BY_V7: 6,
            EXPLAINED_BY_HISTORY: 7, CONSISTENT: 8, FLAT: 9}
    return sorted(out, key=lambda r: (rank.get(r["label"], 9), r["symbol"]))


def needs_attention(rows: list[dict]) -> list[dict]:
    """The rows a human should actually look at. Deliberately short: an
    alert list that includes normal states is an alert list nobody reads."""
    return [r for r in rows or []
            if r.get("label") in (UNEXPLAINED, DIRECTION_MISMATCH, GHOST)]
