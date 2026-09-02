"""NVDA phase 1: v7 must refuse NVDA by construction until a human enables it.
bot.py rejects any symbol outside ALLOWED_SYMBOLS (= SYMBOL_MAP values) with
"unsupported" before any trade path. This pins that NVDA is not in the map."""
from __future__ import annotations

import ast
from pathlib import Path

BOT = Path(__file__).resolve().parents[1] / "bot.py"


def _symbol_map():
    tree = ast.parse(BOT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SYMBOL_MAP" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("SYMBOL_MAP literal not found in bot.py")


def test_nvda_is_not_a_v7_symbol():
    m = _symbol_map()
    assert "NVDA" not in m and "NVDA" not in set(m.values())
    assert not any("NVDA" in k or "NVDA" in v for k, v in m.items())


def test_unsupported_gate_precedes_trading():
    src = BOT.read_text(encoding="utf-8")
    assert src.index('if symbol not in ALLOWED_SYMBOLS: return {"status":"error","msg":f"unsupported: {sym_raw}"}') \
        < src.index("[ASSET-GATE 08-01]")
