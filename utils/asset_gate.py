"""[ASSET-GATE 08-01] per-symbol enable/disable + size multiplier. OFF BY DEFAULT.

The dial that lets GOLD be sized down or benched without code edits — but only
after the weekend review approves it (Evidence Law). While ASSET_GATE_ENABLED
is false (the default), this module always answers (False, 1.0): zero effect.

.env switches (all optional):
    ASSET_GATE_ENABLED=false          # master flag — the one-line switch
    ASSET_GATE_DISABLE=GOLD           # comma list of benched symbols
    ASSET_GATE_SIZE=GOLD:0.5          # comma list of SYMBOL:multiplier

Evidence to flip (from CLAUDE.md + lifetime journal):
  - size-down GOLD:0.5  if GOLD PF < 0.9 at n>=30 lifetime AND last-30d net < 0
  - bench GOLD (DISABLE) if GOLD PF < 0.7 at n>=30
Rationale logged here per Iron Rule 7 (no silent risk change): flipping the
flag is an explicit human act recorded in .env + the weekly review notes.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("sniper.asset_gate")


def _enabled() -> bool:
    return os.getenv("ASSET_GATE_ENABLED", "false").lower() in ("1", "true", "yes")


def _disabled_set() -> set:
    raw = os.getenv("ASSET_GATE_DISABLE", "")
    return {s.strip().upper() for s in raw.split(",") if s.strip()}


def _size_map() -> dict:
    """Parse 'GOLD:0.5,SILVER:1.0' -> {'GOLD': 0.5, 'SILVER': 1.0}. Bad entries ignored."""
    out = {}
    raw = os.getenv("ASSET_GATE_SIZE", "")
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        sym, _, mult = part.partition(":")
        try:
            m = float(mult)
        except (TypeError, ValueError):
            log.warning(f"[ASSET-GATE] bad multiplier {part!r} ignored")
            continue
        # sanity: a multiplier only ever REDUCES or keeps size (Iron Rule 7:
        # never widen risk silently) — values above 1.0 are clamped to 1.0.
        out[sym.strip().upper()] = max(0.0, min(m, 1.0))
    return out


def asset_gate_check(symbol: str) -> tuple:
    """Return (blocked: bool, size_mult: float) for this symbol.

    Flag off (default) -> always (False, 1.0). Never raises.
    """
    try:
        if not _enabled():
            return False, 1.0
        sym = str(symbol or "").upper()
        if sym in _disabled_set():
            return True, 0.0
        return False, _size_map().get(sym, 1.0)
    except Exception as e:
        log.warning(f"[ASSET-GATE] check failed (fail-open, no effect): {e}")
        return False, 1.0
