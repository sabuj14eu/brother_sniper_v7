# Multi-session coordination — READ BEFORE TOUCHING A CHECKOUT

**The problem this solves (recurring, real):** several Claude sessions work
these repos at once, but each BOX has ONE git checkout with ONE HEAD. Whoever
runs `git checkout` last silently changes what every other session's "git
pull" means and what the SERVICES load on their next restart. This has already
caused: "Already up to date" while the wanted commit sat on another branch,
missing files after a successful pull, and one deploy that copied a stale
file over a fixed one.

## Branch ownership (update this table when it changes)
| Branch | Owner session | Carries |
|---|---|---|
| `claude/brain-platform-mirror-fcacwl` | bot-side session | mirrors, bias, cost controls, backfills, bridge endpoints |
| `claude/trade-desk-architecture-review-hp9xnb` | trade-desk session | v7 heartbeat + decision contract (INTEGRATION_V7.md) — **live on the v7 box checkout** |
| `main` | convergence target | everything, eventually |

## The rules
1. **Never `git checkout <branch>` on a box whose services are running from
   the current checkout.** The service keeps old code in memory until restart
   — then loads YOUR branch, silently dropping the other session's work.
2. **Need one file from another branch? Take the file, not the branch:**
       git fetch origin <branch>
       git checkout origin/<branch> -- path/to/file.py
   This adds/overwrites only that path and moves nothing else.
3. **Push your work to `main` as well as your working branch** once it is
   deploy-ready. `main` is where other sessions look first, and where box
   checkouts will eventually converge.
4. **A pull that says "Already up to date" while the fetch line shows the
   remote branch moving is the fingerprint of this problem** — check
   `git branch --show-current` before concluding anything is broken.
5. **Deployed ≠ committed.** The Windows executors run from `C:\...` copies
   and TradingView alerts freeze Pine at creation. Verify what RUNS from its
   own mouth (journal `pine_ver`, service endpoints), never from the repo.

## ⚠ FORKED CONTRACT — two v7 emitters exist, only one is deployed (08-19)

Found while chasing one trade the platform never received
(`SS-BUY-20260819104500`, ETHEREUM, opened 13:00 and closed 14:43 with the
journal proving both). It is not a dropped post. There are **two independent
v7 → platform emitters, and they disagree on both the endpoint and the id**:

| | endpoint | signal_id | wired into deployed bot.py? |
|---|---|---|---|
| `core/v7_status.record_decision` (trade-desk) | `/webhooks/brain/decision` | RAW `SS-BUY-...` | **YES — the only one running** |
| `learning/platform_mirror.mirror_v7*` (bot-side) | `/webhooks/brain/signal` | `v7-SS-BUY-...` | no (calls exist only on the bot branch) |

Consequences, all of which we have now seen:
- Live verdicts reach `/decision` under a bare id; the `signals` table's `v7-`
  rows came from the BACKFILL. A query for `v7-<id>` therefore "proves" a live
  trade is missing when it may simply be under the other namespace — that is
  exactly what the two "never arrived" ids looked like.
- Whichever emitter a box happens to run decides what the desk can show.

**Do not fix this by adding the second emitter.** Two writers of one desk is
how a page ends up showing a trade twice, or twice with different statuses.
At convergence pick ONE emitter and ONE id namespace (recommendation: keep
`v7-<pine_signal_id>` everywhere, since `pine_signal_id` is already the agreed
join key between both arms) and delete the loser. Until then, any query about
"did the platform get X" must search BOTH namespaces:

    SELECT signal_id, system, status FROM signals WHERE signal_id LIKE '%<id>%';

## Where things run (two boxes, and the mistakes that follow)

**`probe_symbol_specs.py` runs from CONTABO, not Windows.** It is an HTTP
client: it asks the bridge at `164.68.126.105:5001` and never imports MT5.
A "file not found" from Contabo means the single-file checkout was skipped
(this box lives on another branch — see the rules above), NOT that the probe
belongs on the Windows box. Running it there would need python, the repo and
the venv on a box that has none of them. It needs `BRIDGE_KEY` in `.env` now
that `/symbolspec` is key-gated, or every symbol reports `HTTP 401`, which the
output would otherwise render as "the broker does not list it".

    git checkout origin/claude/brain-platform-mirror-fcacwl -- probe_symbol_specs.py
    python3 probe_symbol_specs.py UST10Y_U6 USDX DXY_U6

**⚠ The candle reporter is UNVERSIONED.** It runs as a Windows NSSM service
and exists in no repository on either branch — it cannot be reviewed,
diffed, restored after a disk loss, or safely edited by anyone who cannot
see it. Anything that needs a symbol added to the platform's candle feed is
therefore blocked on reading a file that only one machine has. It should be
committed here at the next opportunity; until then, treat every change to it
as a deploy with no rollback.

**CORRECTION 2026-09-02 (measured in git, bot boss session):** the reporter
IS versioned — `Sniper-System/agents/mt5_reporter/mt5_reporter.py`,
`REPORTER_VERSION = "1.6.0"`, committed 2026-08-22 (platform v4.58, commit
5260ce9). The warning above was true when written (08-19). What remains
unversioned is whatever `C:\brotherbot\mt5_reporter.py` runs if it differs
from that file — `Get-FileHash` both before trusting either. Same shape,
found the same day, then corrected within the hour (a partial read again —
lesson C1): the DXY/US10Y/US30Y front-contract resolver IS pushed, on
`claude/brain-platform-mirror-fcacwl` (fc5bd6f, 2026-08-20, with
`tests/test_front_contract.py` and `probe_symbol_specs.py`) — but NOT on
the deploy branch. The two branches have diverged 34/41 commits from base
88fe2d8 (69 files). The Windows bridge was A1-patched in place, so which
bridge it runs is a measurement, not a branch name:
`Select-String C:\Users\Administrator\sniper_executor.py -Pattern "_macro_front"`
(a hit = mirror-branch bridge with the resolver). Convergence of the two
branches is the top structural open item — until then the deploy branch's
`sniper_executor.py` must never be copied over the box's.

## Shared contracts already agreed (do not fork these)
- Platform mirror: `learning/platform_mirror.py` (v7) / `brain/src/platform_mirror.py`
  — `pine_signal_id` join key, `rejected_by` structured, spread-at-decision,
  `rr_in_grade`, status `approved|rejected|closed`.
- Candidate id: minted once as `SC-<SIDE>-<UTCstamp>`, shared by artifact and
  brain payload — exact join, no tolerance matching for new rows.
- Outcome truth: executor `outcomes.jsonl` by ticket (brain journal backfill);
  v7 `learning/trades.jsonl` open+close by signal_id (platform backfill).
- Freshness law: every re-posted datum carries its true `as_of`; nothing is
  ever repainted fresh.

## Endgame
When the current wave of work settles: every session merges to `main`, every
box checks out `main`, this table shrinks to one row, and the single-file
trick becomes history.
