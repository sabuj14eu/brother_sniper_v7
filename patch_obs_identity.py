#!/usr/bin/env python3
"""OBS identity (2026-09-02): /health gains git_commit + service_version —
append-only, powers the platform Git<->Production MATCH light.
    python3 patch_obs_identity.py
"""
import ast, os, shutil, sys, time

BOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")
ROUTE = '@app.route("/health",methods=["GET"])'
IDENT = ('''# [OBS 2026-09-02] deployed-commit identity, read once at start
def _deploy_commit():
    try:
        import subprocess as _sp
        return _sp.run(["git", "-C", os.path.dirname(os.path.abspath(__file__)),
                        "rev-parse", "--short", "HEAD"],
                       capture_output=True, text=True, timeout=5).stdout.strip() or "untracked"
    except Exception:
        return "untracked"


_GIT_COMMIT = _deploy_commit()


''')
FIELD_OLD = '        "discipline":discipline.status_dict(),"uptime_since":_start,'
FIELD_NEW = ('        "discipline":discipline.status_dict(),"uptime_since":_start,\n'
             '        "git_commit":_GIT_COMMIT,"service_version":"v7-bot",')


def main():
    src = open(BOT, encoding="utf-8").read()
    if "[OBS 2026-09-02]" in src:
        print("ALREADY PATCHED — nothing to do")
        return 0
    for name, a in (("route", ROUTE), ("field", FIELD_OLD)):
        if src.count(a) != 1:
            print(f"ABORT: anchor \'{name}\' found {src.count(a)}x, need 1 — untouched")
            return 1
    bak = f"{BOT}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(BOT, bak)
    out = src.replace(ROUTE, IDENT + ROUTE).replace(FIELD_OLD, FIELD_NEW)
    open(BOT, "w", encoding="utf-8").write(out)
    try:
        ast.parse(out)
    except SyntaxError as e:
        shutil.copy2(bak, BOT)
        print(f"ABORT: compile failed ({e}) — RESTORED")
        return 1
    print(f"PATCHED bot.py — /health carries git_commit (backup {os.path.basename(bak)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
