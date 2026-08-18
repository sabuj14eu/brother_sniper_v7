"""Tests for core/symbol_registry.py — config overlay with dict fallbacks."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import ic_markets, sl_engine, symbol_registry as sr


def _fresh_targets():
    return dict(symbol_map={"XAUUSD": "GOLD"}, allowed={"GOLD"},
                px_digits={"GOLD": 2}, safe_specs={}, price_ranges={},
                asset_class_map={})


def _snapshot():
    return (dict(ic_markets.SYMBOL_MAP_CT), list(ic_markets.CRYPTO_247),
            dict(ic_markets.DEMO_MAX_LOT), dict(ic_markets.MIN_LOT),
            dict(sl_engine.FAKEOUT_PAD), dict(sl_engine.MIN_SL_PCT),
            dict(sl_engine.MAX_SL_PCT), dict(sl_engine.ATR_EST_PCT))


def _restore(snap):
    (ic_markets.SYMBOL_MAP_CT, ic_markets.CRYPTO_247, ic_markets.DEMO_MAX_LOT,
     ic_markets.MIN_LOT, sl_engine.FAKEOUT_PAD, sl_engine.MIN_SL_PCT,
     sl_engine.MAX_SL_PCT, sl_engine.ATR_EST_PCT) = \
        (snap[0], snap[1], snap[2], snap[3], snap[4], snap[5], snap[6], snap[7])


def test_missing_file_is_noop(tmp_path):
    t = _fresh_targets()
    before = {k: (set(v) if isinstance(v, set) else dict(v)) for k, v in t.items()}
    applied = sr.apply_registry(path=str(tmp_path / "absent.json"), **t)
    assert applied == []
    assert t["symbol_map"] == before["symbol_map"] and t["allowed"] == before["allowed"]


def test_corrupt_and_wrong_shape_files_are_noop(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert sr.apply_registry(path=str(bad), **_fresh_targets()) == []
    bad.write_text('["a", "list"]')
    assert sr.apply_registry(path=str(bad), **_fresh_targets()) == []


def test_disabled_entry_stays_benched(tmp_path):
    cfg = tmp_path / "symbols.json"
    cfg.write_text(json.dumps({"SOLANA": {"enabled": False,
                                          "aliases": ["SOLUSD"]}}))
    t = _fresh_targets()
    assert sr.apply_registry(path=str(cfg), **t) == []
    assert "SOLANA" not in t["allowed"] and "SOLUSD" not in t["symbol_map"]


def test_enabled_entry_overlays_everything(tmp_path):
    snap = _snapshot()
    try:
        cfg = tmp_path / "symbols.json"
        cfg.write_text(json.dumps({"SOLANA": {
            "enabled": True, "aliases": ["SOLUSD", "SOL"], "mt5": "SOLUSD",
            "asset_class": "crypto", "digits": 2, "price_range": [5, 2000],
            "always_open": True, "fakeout_pad": 0.0, "min_sl_pct": 0.015,
            "max_sl_pct": 0.10, "atr_est_pct": 0.03, "demo_max_lot": 1.0,
            "min_lot": 0.01,
            "spec": {"tickSize": 0.01, "tickValue": 0.01, "lotMin": 0.01,
                     "lotMax": 100.0, "lotStep": 0.01}}}))
        t = _fresh_targets()
        assert sr.apply_registry(path=str(cfg), **t) == ["SOLANA"]
        assert t["symbol_map"]["SOLUSD"] == "SOLANA"
        assert t["symbol_map"]["SOLANA"] == "SOLANA"      # canonical self-map
        assert "SOLANA" in t["allowed"]
        assert t["px_digits"]["SOLANA"] == 2
        assert t["safe_specs"]["SOLANA"]["_source"] == "registry"
        assert t["price_ranges"]["SOLANA"] == (5.0, 2000.0)
        assert t["asset_class_map"]["SOLANA"] == "crypto"
        assert ic_markets.SYMBOL_MAP_CT["SOLANA"] == "SOLUSD"
        assert "SOLANA" in ic_markets.CRYPTO_247
        assert ic_markets.DEMO_MAX_LOT["SOLANA"] == 1.0
        assert sl_engine.MIN_SL_PCT["SOLANA"] == 0.015
        assert sl_engine.ATR_EST_PCT["SOLANA"] == 0.03
        # existing symbols untouched
        assert t["symbol_map"]["XAUUSD"] == "GOLD" and "GOLD" in t["allowed"]
    finally:
        _restore(snap)


def test_bad_entry_skipped_good_applied(tmp_path):
    snap = _snapshot()
    try:
        cfg = tmp_path / "symbols.json"
        cfg.write_text(json.dumps({
            "BROKEN": {"enabled": True, "digits": "not-an-int"},
            "CARDANO": {"enabled": True, "aliases": ["ADAUSD"],
                        "asset_class": "crypto"}}))
        t = _fresh_targets()
        applied = sr.apply_registry(path=str(cfg), **t)
        assert applied == ["CARDANO"]
        assert "ADAUSD" in t["symbol_map"]
    finally:
        _restore(snap)


def test_repo_config_is_valid_and_all_benched():
    """The committed config/symbols.json must parse, and every entry must be
    bench-listed (enabled != true) until broker specs are human-verified."""
    reg = sr.load_registry()
    assert isinstance(reg, dict)
    assert sr.enabled_entries(reg) == {}
