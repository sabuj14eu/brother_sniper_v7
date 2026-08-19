#!/usr/bin/env python3
"""One evidence file for the desks to display (batch, read-only, $0).

The desk pages must not recompute v7's evidence — two implementations of
one statistic eventually disagree, and then nobody knows which page is
lying. So the analytics run HERE, once, and write a single JSON that any
number of pages read verbatim:

    v7_counterfactual  -> what the refused signals would have done
    gate_effectiveness -> which gates earn their keep (validate half only)
    mae_recompute      -> true excursions, stop headroom

Intended as a nightly cron beside nightly_edge.py:
    0 2 * * *  cd /home/shyam/brother_sniper_v7 && python3 v7_counterfactual.py \\
               && python3 mae_recompute.py && python3 v7_evidence_report.py

Every section carries its own sample size and PROVISIONAL flag, so a page
cannot show a number without showing how much evidence stands behind it.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(BASE, "learning", "evidence.json")
SCHEMA = "v7-evidence-1"


def build(cf_rows=None, unified=None, mae_rows=None) -> dict:
    import gate_effectiveness as ge
    import mae_recompute as mr
    import v7_counterfactual as cf

    cf_rows = ge.load_cf() if cf_rows is None else cf_rows
    if unified is None:
        try:
            from learning.telemetry import load_unified
            unified = load_unified()
        except Exception:
            unified = []
    if mae_rows is None:
        mae_rows = _read_jsonl(mr.OUT_FILE)

    rep = ge.report(cf_rows, unified)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counterfactual": cf.summarize(cf_rows),
        "kept_lane": rep["kept_lane"],
        "gates": rep["gates"],
        "by_session": rep["by_session"],
        "by_symbol": rep["by_symbol"],
        "by_grade": rep["by_grade"],
        "by_strategy": rep["by_strategy"],
        # Combination cuts (symbol x side x session ...). Separate key so a
        # page that only knows the 1-D views keeps working unchanged, and
        # UNAVAILABLE rather than fatal if the module is absent — one optional
        # section must never cost the desk its whole evidence file.
        "setup_edge": _setup_edge(unified),
        "excursions": {"understatement": mr.understatement(mae_rows),
                       "headroom": mr.stop_headroom(mae_rows)},
        "min_n": rep["min_n"], "train_ratio": rep["train_ratio"],
        "note": ("Every figure is measured from v7's own journals. Buckets "
                 "with n below min_n are PROVISIONAL — n<20 is luck. Gate "
                 "verdicts read the VALIDATE half of a 70/30 time split. "
                 "Nothing here changes a rule; it is evidence for a human."),
    }


def _setup_edge(unified) -> dict:
    """The combination cuts, or an honest UNAVAILABLE block. setup_edge.py is
    copied onto the box by hand (it lives on a different branch), so a missing
    file is a realistic Tuesday — and it must cost this section only, never
    the whole report."""
    try:
        import setup_edge as se
        return se.setup_edge(unified)
    except Exception as e:
        return {"state": "UNAVAILABLE", "families": [],
                "reason": f"{type(e).__name__}: {e}"}


def _read_jsonl(path: str) -> list:
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
    except FileNotFoundError:
        pass
    return rows


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    from core.env_boot import load_env
    load_env()          # cron/CLI runs inherit no systemd environment
    rep = build()
    path = argv[argv.index("--out") + 1] if "--out" in argv else OUT_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

    # Mirror it to the platform so ONE page can show everything (the status
    # dashboard reads the file locally; app.signalmesh.dev cannot). Same
    # contract and same env gate as every other v7 push — inert until
    # PLATFORM_URL and PLATFORM_SECRET are set, and a failure here can never
    # affect the report that is already safely on disk.
    if "--no-push" not in argv:
        try:
            from core.v7_status import _push
            _push({**rep, "kind": "v7_evidence", "title": "v7 evidence report",
                   "generated_at": rep.get("generated_at")},
                  "/webhooks/brain/artifact")
        except Exception as e:  # pragma: no cover - defensive
            print(f"  (platform mirror skipped: {type(e).__name__})")

    # the file is already safely on disk; a summary line must never be the
    # thing that fails the job
    c = rep.get("counterfactual") or {}
    k = rep.get("kept_lane") or {}
    gates = rep.get("gates") or []
    print(f"wrote {path}")
    print(f"  kept lane   n={k.get('n')} WR={k.get('win_rate')} "
          f"PF={k.get('pf')} exp={k.get('expectancy_r')}R")
    print(f"  killed lane n={c.get('n_resolved')} resolved of {c.get('n_total')} "
          f"(WR {c.get('win_rate')} · exp {c.get('expectancy_r')}R)")
    print(f"  gates {len(gates)} · proven "
          f"{sum(1 for g in gates if g.get('verdict') != 'UNPROVEN')}")
    fams = (rep.get("setup_edge") or {}).get("families") or []
    print(f"  setup edge  {len(fams)} families · "
          f"{sum(len(f.get('rows') or []) for f in fams)} rows shown · "
          f"{sum(f.get('proven') or 0 for f in fams)} proven "
          f"(python3 setup_edge.py for the tables)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
