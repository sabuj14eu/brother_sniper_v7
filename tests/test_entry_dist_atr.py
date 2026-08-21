"""entry_dist_atr into v7 telemetry (2026-08-21) — the second population
for the >3 ATR distance question. Log-only; nothing here gates a trade."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import learning.telemetry as tm  # noqa: E402


def test_schema_carries_entry_dist_atr():
    row = tm.blank_row()
    assert "entry_dist_atr" in row and row["entry_dist_atr"] is None


def test_open_row_captures_pine_value_verbatim():
    row = tm.build_open_row(signal_id="s1", symbol="GOLD", entry_dist_atr=3.42)
    assert row["entry_dist_atr"] == 3.42
    # absent stays None — never computed here, never guessed
    assert tm.build_open_row(signal_id="s2")["entry_dist_atr"] is None


def test_reject_rows_capture_it_too():
    captured = {}
    orig = tm.write_row
    tm.write_row = lambda r: captured.update(r)
    try:
        tm.capture_reject({"signal_id": "r1", "symbol": "GOLD",
                           "entry_dist_atr": 4.1}, "rejected", "score")
    finally:
        tm.write_row = orig
    assert captured["entry_dist_atr"] == 4.1 and captured["_type"] == "reject"


def test_load_unified_surfaces_the_column(tmp_path):
    p = tmp_path / "telemetry.jsonl"
    p.write_text('{"signal_id": "u1", "symbol": "GOLD", "entry_dist_atr": 3.4}\n')
    rows = tm.load_unified(telemetry_path=str(p), trades=[])
    assert rows[0]["entry_dist_atr"] == 3.4


def test_box_patch_script_is_idempotent_and_anchor_safe(tmp_path):
    """The box runs another branch's bot.py, so deployment is the anchor-safe
    patch script — prove it: (a) patches a pristine tree, (b) refuses to run
    twice, (c) aborts without changes on an ambiguous anchor."""
    script = (ROOT / "patch_entry_dist_atr.py").read_text()
    cur_bot = (ROOT / "bot.py").read_text()
    cur_tel = (ROOT / "learning" / "telemetry.py").read_text()
    # reconstruct the pre-patch files by removing exactly what we added
    pristine_bot = "\n".join(
        l for l in cur_bot.splitlines()
        if "entry_dist_atr" not in l and "scalp payload; captured verbatim" not in l
        and "so the column means ONE thing). Log-only" not in l
        and "field in this block — the trade is already placed." not in l
        and "08-21 entry_dist_atr: Pine v18.12 appends" not in l) + "\n"
    pristine_tel_lines = []
    skip = False
    for l in cur_tel.splitlines():
        if "# 08-21 APPEND-ONLY: Pine v18.12 emits entry_dist_atr" in l:
            skip = True
        if not skip and "entry_dist_atr" not in l:
            pristine_tel_lines.append(l)
        if skip and '"entry_dist_atr"],' in l:
            skip = False
            pristine_tel_lines.append('               "dxy", "oil", "us10y", "vix", "volatility"],')
    pristine_tel = "\n".join(pristine_tel_lines) + "\n"

    work = tmp_path / "box"
    (work / "learning").mkdir(parents=True)
    (work / "patch_entry_dist_atr.py").write_text(script)
    (work / "bot.py").write_text(pristine_bot)
    (work / "learning" / "telemetry.py").write_text(pristine_tel)

    r1 = subprocess.run([sys.executable, "patch_entry_dist_atr.py"],
                        cwd=work, capture_output=True, text=True)
    assert r1.returncode == 0 and "PATCHED bot.py" in r1.stdout, r1.stdout + r1.stderr
    patched = (work / "bot.py").read_text()
    assert 'entry_dist_atr=payload.get("entry_dist_atr"),' in patched
    assert '"entry_dist_atr"],' in (work / "learning" / "telemetry.py").read_text()

    # (b) second run: refuses, changes nothing
    r2 = subprocess.run([sys.executable, "patch_entry_dist_atr.py"],
                        cwd=work, capture_output=True, text=True)
    assert r2.returncode == 0 and "ALREADY PATCHED" in r2.stdout
    assert (work / "bot.py").read_text() == patched

    # (c) ambiguous anchor: duplicate the bot.py anchor -> abort, untouched
    dup = pristine_bot + '\n# decoy\n#                    us10y=payload.get("yield_dir"),\n'
    dup = pristine_bot.replace(
        '                    us10y=payload.get("yield_dir"),\n',
        '                    us10y=payload.get("yield_dir"),\n', 1) \
        + '\nif False:\n    _cap(\n                    us10y=payload.get("yield_dir"),\n                    zone=None)\n'
    (work / "bot.py").write_text(dup)
    (work / "learning" / "telemetry.py").write_text(pristine_tel)
    r3 = subprocess.run([sys.executable, "patch_entry_dist_atr.py"],
                        cwd=work, capture_output=True, text=True)
    assert r3.returncode == 1 and "ABORT" in r3.stdout
    assert (work / "bot.py").read_text() == dup            # nothing changed


def test_mirror_close_patch_script(tmp_path):
    """patch_mirror_close.py: splices the close mirror into a pristine
    bot.py, refuses to run twice, and aborts when the mirror module is
    missing or predates mirror_v7_close."""
    script = (ROOT / "patch_mirror_close.py").read_text()
    anchor = '                    equity_guard.record_trade(net, tracked["symbol"])\n'
    fake_bot = ("def close_path(tracked, net, won, cp, _hold, equity_guard, log):\n"
                "    if True:\n"
                "        if True:\n"
                "            if True:\n"
                "                if True:\n"
                + anchor +
                "                    pass\n")

    work = tmp_path / "box"
    (work / "learning").mkdir(parents=True)
    (work / "patch_mirror_close.py").write_text(script)
    (work / "bot.py").write_text(fake_bot)

    # (a) module missing -> abort, untouched
    r0 = subprocess.run([sys.executable, "patch_mirror_close.py"],
                        cwd=work, capture_output=True, text=True)
    assert r0.returncode == 1 and "does not exist" in r0.stdout
    assert (work / "bot.py").read_text() == fake_bot

    # (b) module too old (no mirror_v7_close) -> abort, untouched
    (work / "learning" / "platform_mirror.py").write_text("def mirror_v7(p): pass\n")
    r1 = subprocess.run([sys.executable, "patch_mirror_close.py"],
                        cwd=work, capture_output=True, text=True)
    assert r1.returncode == 1 and "predates" in r1.stdout
    assert (work / "bot.py").read_text() == fake_bot

    # (c) module current -> patches, compiles
    (work / "learning" / "platform_mirror.py").write_text(
        "def mirror_v7_close(tracked, net, won, close_price=None, hold_seconds=None):\n    pass\n")
    r2 = subprocess.run([sys.executable, "patch_mirror_close.py"],
                        cwd=work, capture_output=True, text=True)
    assert r2.returncode == 0 and "PATCHED bot.py" in r2.stdout, r2.stdout
    patched = (work / "bot.py").read_text()
    assert "mirror_v7_close(tracked, net, won, close_price=float(cp), hold_seconds=_hold)" in patched

    # (d) second run refuses, changes nothing
    r3 = subprocess.run([sys.executable, "patch_mirror_close.py"],
                        cwd=work, capture_output=True, text=True)
    assert r3.returncode == 0 and "ALREADY PATCHED" in r3.stdout
    assert (work / "bot.py").read_text() == patched
