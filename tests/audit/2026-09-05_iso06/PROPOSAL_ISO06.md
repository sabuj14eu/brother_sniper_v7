# ISO-06 — v7 bridge idempotency: same (account_id, signal_id) twice = ONE fill. PROPOSAL, NOT APPLIED.

Finding: `sniper_executor.py` `/execute` (`:242` onward) has no memory of what it has already
placed. Dedupe exists only in the bot process (`bot.py:284-300`, key `symbol:signal_id`, no
account). A retried or duplicated POST — nginx retry, bot restart mid-request, a replayed
webhook — is two fills. Repro kept green on the live file:
`tests/audit/2026-09-04_job3/test_v7_bridge_identity.py::test_repro_ISO06_*`. Risk P1 (ADR-004).

**BEFORE** — `/execute` validates secret, account, global stop, sizes, direction, terminal, then
builds `req` and calls `mt5.order_send(req)` (`:318-337`). Nothing between the two requests
knows they are the same signal.

**WHY WRONG** — ADR-004: uniqueness is `(account_id, signal_id)`. The bot's key holds only
while one bot process talks to one bridge and never restarts mid-flight; the bridge, which
is the last thing before the broker, trusts every POST. Iron Rule 6: only tickets tell the
truth, and a duplicate ticket is a real position with real risk.

**AFTER** (`fixtures/proposed_sniper_executor_iso06.py`, hunks in `proposal_hunks.py`) —
- a small JSON store `V7_SEEN_FILE` (default beside the service file, TTL 6h like v18's
  `signal_ids.json`), keyed `"<account>:<signal_id>"`, atomic write, lock-guarded;
- after every existing validation and immediately BEFORE `order_send`: no `signal_id` → 400
  `no_signal_id`; store unreadable → 503 `seen_store_unknown`; key present → 409
  `duplicate_signal` with the first record (state, ticket); otherwise mark `in_flight`;
- after `order_send`: DONE → `filled` + ticket; other retcode → un-mark (broker said no, a
  retry is legitimate); `None` result → `ambiguous`, kept (may have filled).
No other line of the accepted path changes; the `req` dict and `order_send` call are
byte-identical.

**WHY CORRECT** — the mark sits at the last instant before the broker, so a duplicate that
arrives while the first is mid-flight is refused too; a definitive rejection frees the id so a
legitimate retry still works; every ambiguous state fails closed and leaves the reconciler
(the `BS_` comment / magic 70007 sweep) to settle it. Missing store = UNKNOWN = refuse, never a
default. The key carries the account, so the same Pine id for the two arms never collides.

**WHAT COULD BREAK** —
1. A caller that omits `signal_id` is refused (400). The bot always sends `BS_<sid>`
   (`core/ic_markets.py:185`, `bot.py:1025`); anything else was never ours.
2. An `order_send` that raised mid-flight leaves `in_flight` for 6h; the bot's retry is
   refused with 409 and the bot logs it. Acceptable: a 6h hold on one id versus a double fill.
3. The store file must be writable by the service user (`C:\Users\Administrator`); if not,
   every order is 503 until it is. Deliberate: visible, not silent.
4. Two bridges pointed at the same store would share keys — they must not (one file per
   service, per account).

**HOW TESTED** — `test_iso06_idempotency.py` on the proposed copy (never the live file): same
signal twice = one order + 409; different ids = two orders; store keyed by account
(`_seen_check_and_mark`); broker rejection frees the id; `None` result keeps it; missing
`signal_id` = 400 and no order; unreadable store = 503 and no order; the mark survives a
process restart; TTL expiry frees the id; the hunks apply cleanly to the current source and
reproduce the proposed copy byte-for-byte. Regression: full v7 suite. Replay: n/a (no accepted
path change). Box + human approval: the release gate.
