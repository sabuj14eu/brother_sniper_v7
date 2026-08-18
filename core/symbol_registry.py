"""Config-driven symbol registry — one file per instrument instead of ten dicts.

Before this module, adding an instrument meant hand-editing ~10 hard-coded
dicts across bot.py, core/sl_engine.py, core/ic_markets.py and the Windows
bridge. Now config/symbols.json holds one entry per symbol and apply_registry()
OVERLAYS those entries onto the existing dicts at startup.

SAFETY CONTRACT:
  * The existing dicts are the fallback truth. A missing, empty or corrupt
    config file applies NOTHING and the bot boots byte-identical to before.
    Rollback = delete config/symbols.json (or set an entry "enabled": false).
  * Entries with "enabled": false are NOT registered: their aliases stay
    unknown, so signals for them are rejected upstream ("unsupported") exactly
    as today. This is the bench for new symbols awaiting broker verification.
  * This module never raises into the caller. A bad entry is logged, skipped.
  * The registry only ADDS or OVERRIDES per-symbol parameters. It cannot touch
    risk sizing, slots, gates or any strategy rule (Iron Rule 7).

Entry schema (all keys optional except aliases; absent = existing fallbacks):
{
  "SOLANA": {
    "enabled": false,               # false = bench-listed, not tradeable
    "aliases": ["SOLUSD", "SOL"],  # TradingView names -> this canonical name
    "mt5": "SOLUSD",               # broker symbol for the bridge leg
    "asset_class": "crypto",       # slot: metals|crypto|forex|other
    "digits": 2,                    # price rounding
    "price_range": [5, 2000],      # entry sanity band
    "always_open": true,            # crypto 24/7 (else FX weekend rules)
    "fakeout_pad": 0.0,
    "min_sl_pct": 0.015, "max_sl_pct": 0.10, "atr_est_pct": 0.03,
    "demo_max_lot": 1.0, "min_lot": 0.01,
    "spec": {"tickSize":0.01,"tickValue":0.01,"lotMin":0.01,
             "lotMax":100.0,"lotStep":0.01}
  }
}
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("sniper.symbols")

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(_BASE, "config", "symbols.json")


def load_registry(path: str | None = None) -> dict:
    """Read config/symbols.json. Missing/empty/corrupt -> {} (fallback mode)."""
    path = path or CONFIG_FILE
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            log.warning("[SYMBOLS] registry root is not an object — ignored")
            return {}
        return data
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning(f"[SYMBOLS] registry unreadable ({e}) — fallback dicts only")
        return {}


def enabled_entries(registry: dict) -> dict:
    """Canonical -> entry for entries explicitly enabled. Bad shapes skipped."""
    out = {}
    for canon, entry in (registry or {}).items():
        if str(canon).startswith("_"):
            continue  # _README and friends — documentation keys, not symbols
        if not isinstance(entry, dict):
            log.warning(f"[SYMBOLS] {canon}: entry is not an object — skipped")
            continue
        if entry.get("enabled") is not True:
            continue  # bench-listed until a human flips it after broker verify
        out[str(canon).upper()] = entry
    return out


def apply_registry(*, symbol_map: dict, allowed: set, px_digits: dict,
                   safe_specs: dict, price_ranges: dict, asset_class_map: dict,
                   path: str | None = None) -> list:
    """Overlay enabled registry entries onto the live config dicts.

    Mutates the passed-in bot.py dicts plus core.sl_engine and
    core.ic_markets module tables. Returns the list of canonical symbols
    applied (for the startup log). Never raises.
    """
    applied = []
    try:
        entries = enabled_entries(load_registry(path))
        if not entries:
            return applied
        from core import ic_markets, sl_engine
        for canon, e in entries.items():
            try:
                symbol_map[canon] = canon
                for alias in e.get("aliases") or []:
                    symbol_map[str(alias).upper()] = canon
                allowed.add(canon)
                if e.get("digits") is not None:
                    px_digits[canon] = int(e["digits"])
                if isinstance(e.get("spec"), dict):
                    spec = dict(e["spec"])
                    spec["_source"] = "registry"
                    safe_specs[canon] = spec
                pr = e.get("price_range")
                if isinstance(pr, (list, tuple)) and len(pr) == 2:
                    price_ranges[canon] = (float(pr[0]), float(pr[1]))
                if e.get("asset_class"):
                    asset_class_map[canon] = str(e["asset_class"])
                if e.get("mt5"):
                    ic_markets.SYMBOL_MAP_CT[canon] = str(e["mt5"])
                if e.get("always_open"):
                    if canon not in ic_markets.CRYPTO_247:
                        ic_markets.CRYPTO_247.append(canon)
                if e.get("demo_max_lot") is not None:
                    ic_markets.DEMO_MAX_LOT[canon] = float(e["demo_max_lot"])
                if e.get("min_lot") is not None:
                    ic_markets.MIN_LOT[canon] = float(e["min_lot"])
                if e.get("fakeout_pad") is not None:
                    sl_engine.FAKEOUT_PAD[canon] = float(e["fakeout_pad"])
                if e.get("min_sl_pct") is not None:
                    sl_engine.MIN_SL_PCT[canon] = float(e["min_sl_pct"])
                if e.get("max_sl_pct") is not None:
                    sl_engine.MAX_SL_PCT[canon] = float(e["max_sl_pct"])
                if e.get("atr_est_pct") is not None:
                    sl_engine.ATR_EST_PCT[canon] = float(e["atr_est_pct"])
                applied.append(canon)
            except Exception as ee:
                log.warning(f"[SYMBOLS] {canon}: bad entry ({ee}) — skipped")
        if applied:
            log.info(f"[SYMBOLS] registry applied: {', '.join(sorted(applied))}")
    except Exception as e:  # pragma: no cover - defensive
        log.warning(f"[SYMBOLS] apply_registry failed (non-fatal): {e}")
    return applied
