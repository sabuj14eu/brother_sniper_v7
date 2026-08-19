"""Load the repo's .env for hand-run and cron scripts.

sniper-bot.service gets its environment from systemd's EnvironmentFile, and
bot.py calls load_dotenv() itself. A standalone analytics script run by hand
or by cron inherits NEITHER — so os.getenv("EXECUTOR_URL") came back empty
and the bridge looked unreachable when it was fine. Every CLI entry point
calls load_env() first.
"""
from __future__ import annotations

import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env(path: str | None = None) -> bool:
    """True if a .env was found and applied. Never raises: a missing file or
    a missing python-dotenv must not stop an analytics run."""
    try:
        from dotenv import load_dotenv
        return bool(load_dotenv(path or os.path.join(BASE, ".env")))
    except Exception:
        return False
