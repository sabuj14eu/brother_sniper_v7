"""Round 3 (2026-09-02): A2 header-carried secret + incident poster id keys.
The A2 tests drive the PATCHED bot.py text itself (round-2 pattern): what is
pinned is the deployed logic, not a copy of it."""
from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from post_incident import build_payload  # noqa: E402

PATCH = "patch_webhook_header_secret.py"


def _apply(d: Path, script: str):
    shutil.copy(ROOT / script, d / script)
    return subprocess.run([sys.executable, script], cwd=d,
                          capture_output=True, text=True)


def _patched_bot() -> tuple[Path, str]:
    d = Path(tempfile.mkdtemp())
    # start from the UNPATCHED text so the patch itself is what is tested
    src = (ROOT / "bot.py").read_text()
    if "[A2 2026-09-02]" in src:
        src = _strip_a2(src)
    (d / "bot.py").write_text(src)
    r = _apply(d, PATCH)
    assert r.returncode == 0, (r.stdout, r.stderr)
    return d, (d / "bot.py").read_text()


def _strip_a2(src: str) -> str:
    start = src.index("# [A2 2026-09-02] the nginx mirror")
    end = src.index('@app.route("/webhook"')
    src = src[:start] + src[end:]
    return src.replace(
        '    payload=_header_secret(payload,request.headers)  # [A2 2026-09-02]\n', "")


def _header_secret_from(src: str):
    start = src.index("def _header_secret(")
    end = src.index('@app.route("/webhook"')
    ns = {"log": logging.getLogger("test")}
    exec(src[start:end], ns)
    return ns["_header_secret"]


def test_a2_header_fills_missing_secret_only():
    _, src = _patched_bot()
    hs = _header_secret_from(src)
    # header fills a missing secret
    assert hs({"system": "BSv18"}, {"X-Webhook-Secret": "s3cret"})["secret"] == "s3cret"
    # a body secret is never overridden by the header
    assert hs({"secret": "body"}, {"X-Webhook-Secret": "s3cret"})["secret"] == "body"
    # no header, no secret -> untouched; handle_signal refuses it downstream
    assert "secret" not in hs({"system": "X"}, {})
    # a blank header is not a secret
    assert "secret" not in hs({}, {"X-Webhook-Secret": "   "})
    # a non-dict payload passes through without raising
    assert hs(None, {"X-Webhook-Secret": "s3cret"}) is None


def test_a2_patch_idempotent_and_call_precedes_handle_signal():
    d, src = _patched_bot()
    assert src.index("_header_secret(payload,request.headers)") \
        < src.index("result=handle_signal(payload,raw)")
    again = _apply(d, PATCH)
    assert again.returncode == 0 and "ALREADY PATCHED" in again.stdout


def test_a2_applied_to_repo_copy():
    # round-2 rule: the pushed branch shows what the box runs
    assert "[A2 2026-09-02]" in (ROOT / "bot.py").read_text()


def test_incident_poster_sends_both_id_keys():
    ns = argparse.Namespace(incident_id="INC-0001", root_cause="rc",
                            fix_ref="fr", tests="t", status="investigating")
    p = build_payload(ns)
    assert p["incident_id"] == p["public_id"] == "INC-0001"
    assert p["kind"] == "incident_update" and p["status"] == "investigating"
