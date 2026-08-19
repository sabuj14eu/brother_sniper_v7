#!/usr/bin/env python3
"""Which of v7's closed trades did the platform NOT store as closed?

The backfill sent 202 closes and every post answered 2xx, but the platform DB
reports 175 closed. Orphan closes (no matching open row) account for only 9 of
the 27, so the rest are somewhere else — most likely stored under a DIFFERENT
STATUS, because a handler that dedupes on signal_id would keep the "approved"
row it already had and quietly ignore the later "closed" post.

This prints SQL; it changes nothing. Pipe it into the platform's psql:

    python3 platform_gap_sql.py > /tmp/v7q.sql
    cd /srv/brotherbot && docker compose exec -T db psql -U brotherbot \\
        -d brotherbot < /tmp/v7q.sql

Read the result like this:
  * every id back as `closed`            -> nothing is missing, recount
  * a pile still `approved`              -> the handler ignores status updates
                                            on an existing signal_id (their fix)
  * ids absent from the table entirely   -> those posts were dropped on ingest
"""
from __future__ import annotations

import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
TRADES = os.path.join(BASE, "learning", "trades.jsonl")
PREFIX = "v7-"          # the mirror's id namespace


def closed_ids(path: str = TRADES) -> list:
    """Signal ids v7 considers CLOSED — the same rule backfill_v7_closes uses."""
    ids, opens = set(), set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            sid = r.get("signal_id")
            if not sid:
                continue
            is_close = (r.get("_type") == "close" or
                        r.get("net_profit") is not None)
            (ids if is_close else opens).add(str(sid))
    return sorted(ids), sorted(ids - opens)


def sql_literal(sid: str) -> str:
    return "'" + PREFIX + sid.replace("'", "''") + "'"


def main() -> int:
    ids, orphans = closed_ids()
    lst = ",".join(sql_literal(s) for s in ids)
    print(f"-- v7 closed trades in the journal: {len(ids)} "
          f"({len(orphans)} of them orphan closes with no open row)")
    print("-- 1) where did they actually land?")
    print(f"SELECT status, count(*) FROM signals WHERE signal_id IN ({lst}) "
          "GROUP BY status ORDER BY 2 DESC;")
    print("-- 2) how many are not in the table at all?")
    print(f"SELECT {len(ids)} - count(DISTINCT signal_id) AS missing_entirely "
          f"FROM signals WHERE signal_id IN ({lst});")
    print("-- 2b) NAME them — these never reached the platform under any id,")
    print("--     which makes them a sender-side question, not an ingest one.")
    vals = ",".join("(" + sql_literal(s) + ")" for s in ids)
    print(f"SELECT sid AS never_arrived FROM (VALUES {vals}) AS t(sid) "
          "EXCEPT SELECT signal_id FROM signals ORDER BY 1;")
    print("-- 3) a few that are stored but NOT closed — the ones to explain")
    print(f"SELECT signal_id, status, symbol FROM signals WHERE signal_id IN "
          f"({lst}) AND status <> 'closed' ORDER BY signal_id LIMIT 15;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
