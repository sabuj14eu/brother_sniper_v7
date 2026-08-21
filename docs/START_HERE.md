# START HERE — bot-box handover (written 2026-08-21)

A new session needs no chat history. Read `CLAUDE.md` first (the constitution),
then this file. Everything below is measured or verified, not remembered.

## Where you are

| | |
|---|---|
| Repo | `sabuj14eu/brother_sniper_v7` |
| Bot-side branch | `claude/brain-platform-mirror-fcacwl` ← this session's work |
| Trade-desk branch | `claude/trade-desk-architecture-review-hp9xnb` ← **what the boxes are checked out on** |
| Contabo | v7 bot (`/home/shyam/brother_sniper_v7`), v18 brain (`/home/shyam/brain-v2`), platform (`/srv/brotherbot`) |
| Windows VPS `164.68.126.105` | MT5 terminals + `sniper_executor.py` (bridge :5001) + `C:\brotherbot\mt5_reporter.py` |

**The boxes run another session's branch.** Never `git checkout <branch>` there.
Take single files: `git checkout origin/<branch> -- path/to/file.py`.
Full rules in `docs/SESSION_COORDINATION.md`.

## What is live and verified

- **Bridge** (`sniper_executor.py`, deployed on Windows): closed bars by default,
  `?live=1` opts into the forming bar (flagged); `BRIDGE_KEY` gates `live=1`,
  `/spread`, `/symbolspec` — **not** closed `/candles`, which `bot.py fetch_atr`
  needs; front-contract resolver for DXY/US10Y/US30Y (read paths only —
  `/execute` still uses `SYMBOL_MAP`, and a test enforces that).
- **Reporter** (Windows service): per-bar DST conversion in v1.5.0 —
  **not yet deployed**, waiting on the wipe-and-rebuild. `BB_BROKER_UTC_OFFSET=3`
  is pinned at service level meanwhile.
- **Analytics**: `setup_edge.py` (combination edge), `v7_evidence_report.py`,
  `v7_counterfactual.py`, `mae_recompute.py` — nightly cron 03:25.
- **Relays**: `push_doc.py` sends docs/code to the platform as `kind:"doc"`
  artifacts with a sha256 of the bytes sent; `platform_gap_sql.py` audits what
  the platform actually stored.

## Open work — bot side (yours)

1. **`entry_dist_atr` into v7 telemetry.** Pine already emits it (v18.12);
   `learning/telemetry.py` has no such field, so `setup_edge` cannot cut by it.
   This is the blocking dependency for any Location-Gate max-distance decision.
   Touches `bot.py` (live trading file) — deliberate session only.
2. **BOT-P0-2** — Pine's `signal_id` as the single canonical id across both arms.
3. **Windows updater** (`update.ps1`) — blocked until the platform serves
   `sniper_executor.py` at `/downloads` with its hash (file already relayed).
4. **Convergence** — all branches to `main`, boxes onto `main`.

## Open questions — answered honestly, do not "resolve" them

- **Do Pine grades predict?** UNKNOWN. The collection week ran, C/D signals
  fired (16 `C ok`, 13 `D` in `logs/bot.log`), but the AI/score filter blocked
  them downstream for being **counter-trend** — the #1 documented loss driver.
  Decision taken: leave the Pine toggle ON, relax nothing. C/D data accrues
  only when every other filter agrees. That is slow and correct.
- **Does entry distance kill edge?** The platform's paper lanes say
  `>3 ATR → −0.19R (n=620)`, with-trend `−0.643R (n=368)`. **One population.**
  Nothing moves until v7's own filled trades agree — see item 1.
- **Which assets bleed?** Re-derived 2026-08-21 on v7's own journal:
  SILVER n=48 EV_lcb −0.00 · GOLD n=33 **−0.50** · ETHEREUM n=22 **−0.48**.
  Independently confirms the constitution's oldest asset claim. Actionable
  when someone chooses to change one organ.

## Incident in progress — candle timestamps

A manual backfill on 2026-08-20 23:50 detected the wrong broker offset (+2
instead of +3) and wrote ~30,209 provably mis-stamped rows across GOLD,
SILVER, BTC, ETH (4h/1d). Platform owns the repair: wipe → rebuild with
per-bar conversion → purge → re-audit. **GOLD, ETH, SILVER rebuilt; BTC
pending.** Do not treat EMA200 / MTF trend / long-term outlook on those four
symbols' 4h/1d as trustworthy until their audit reads clean. A 37 MB backup
exists platform-side and stays until then.

## What this week actually taught (all paid for)

1. **Probe before trusting an alias.** `DXY→USDX` pointed at a symbol the
   terminal does not list; every read failed invisibly. Same shape as
   `RIPPLE` dying at MT5. An alias is a claim about a name existing somewhere
   else, and nothing checks it until something tries.
2. **Render the reason, never the absence.** A panel that shows nothing is
   indistinguishable from a broken one. Say "no 15m candles in the NY window",
   never render empty.
3. **Build to the wire, not to the spec.** The bridge sends `rows`/`time`; a
   reader expecting `candles`/`ts` showed an empty chart with no error.
4. **A scalar offset cannot convert a multi-year series** (DST), and
   **internal consistency is not correctness** — a uniformly-wrong series
   passes every grid test.
5. **Check the distribution, not the mode.** "The dailies are at 21:00, so
   history is clean" was wrong: the mode was right and 30k rows were not.
6. **Config that is accepted is not config that is applied.** `BB_PUSH_CANDLES`
   defaulted off; machine env vars were overridden by the service's registry
   block; `nssm set` failed silently on UTF-16 output. Only data proves data.

Every one of these failed **without an error**. That is the family to look for.

## The one rule that outranks the rest

Nothing here changes a trading rule. Evidence proposes; v7's own filled
trades justify; two independent populations, a validate split and n≥20–30
before promotion is even a conversation. Iron Rules 1, 5 and 7 stand above
anything written in this file.
