# Job 3 — dual-MT5 isolation evidence (v7 arm), 2026-09-04

Re-runnable reproductions of the isolation findings on the v7 arm
(`sniper_executor.py` on Windows :5001, `core/ic_markets.py` and `bot.py`
on Contabo). Fixtures only — no broker, terminal, network or live checkout.
The v18 arm's half lives in `brother-brain-v2/tests/audit/2026-09-04_job3/`;
the cross-arm tests in `brother-developer/tests/audit/2026-09-04_job3/`.

Naming: `test_repro_*` PASSES while the finding is reproducible (green = the
gap is still there); `test_holds_*` is an invariant that holds today.

Run from the repo root (needs pytest + flask + requests):

    python3 -m pytest tests/audit/2026-09-04_job3 -q

Findings reproduced here: ISO-01 misrouted order, ISO-02 fabricated balance,
ISO-03 unknown account executes, ISO-04 anonymous orders (no magic), ISO-05
cross-arm close/modify, ISO-06 no bridge idempotency, ISO-07/08 guards and
dedupe carry no account. Memory records: `brother-developer/brother_developer/
memory/bugs/BUG-2026-09-04-*.json`.
