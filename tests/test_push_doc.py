"""push_doc tests — the secret guard is the one that matters.

Publishing is irreversible: a token that reaches the platform has left this
box for good. So the guard is tested against the shapes a real doc acquires,
including the ones it must NOT block (docs name env vars constantly).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import push_doc as pd  # noqa: E402


# ── the guard must fire ──────────────────────────────────────────────────────

def test_catches_pasted_credentials():
    for bad in [
        "PLATFORM_SECRET=de1c1ce9a8b7c6d5e4f3a2b1c0d9e8f7",
        "api_key: bb_yemsUiwDOGwJRyiROKQtaZLSdnOFLI9swMtJFthxhI4",
        "  password = hunter2hunter2",
        "WEBHOOK_TOKEN=abcd1234efgh5678",
    ]:
        assert pd.scan_secrets(f"# Doc\n\n{bad}\n"), f"guard missed: {bad}"


def test_reports_line_number_and_preview():
    hits = pd.scan_secrets("# Doc\nfine line\nAPI_KEY=0123456789abcdef\n")
    assert hits and hits[0][0] == 3 and "API_KEY" in hits[0][1]


# ── the guard must NOT fire on normal prose ──────────────────────────────────

def test_allows_naming_an_env_var():
    """Docs say this constantly; blocking it would make the tool useless."""
    for ok in [
        "Inert until PLATFORM_URL and PLATFORM_SECRET are both set.",
        "Set BRAIN_AI_WEEKLY_BUDGET_USD to cap spend.",
        "The X-Brain-Secret header authenticates the post.",
        "| secret | never committed |",
        "Rotate the v7 WEBHOOK_SECRET at the finish line.",
    ]:
        assert not pd.scan_secrets(f"# Doc\n\n{ok}\n"), f"false positive: {ok}"


def test_real_work_orders_pass_the_guard():
    """The documents this tool exists to publish must actually be publishable."""
    for rel in pd.DEFAULT_DOCS:
        full = os.path.join(pd.BASE, rel)
        if not os.path.exists(full):
            continue
        with open(full, encoding="utf-8") as f:
            hits = pd.scan_secrets(f.read())
        assert not hits, f"{rel} would be refused: {hits[:2]}"


# ── payload shape ────────────────────────────────────────────────────────────

def test_payload_carries_identity_and_content():
    text = "# TRADE DESK — work order\n\nbody line\n"
    p = pd.build_payload("docs/X.md", text, "abc1234")
    assert p["kind"] == "doc" and p["doc_id"] == "X.md"
    assert p["title"] == "TRADE DESK — work order"
    assert p["markdown"] == text and p["commit"] == "abc1234"
    assert p["bytes"] == len(text.encode("utf-8"))
    assert p["path"] == "docs/X.md" and p["format"] == "markdown"


def test_title_falls_back_to_filename():
    assert pd.build_payload("docs/Y.md", "no heading here\n", "s")["title"] == "Y.md"


def test_missing_file_is_skipped_not_fatal(capsys):
    rc = pd.main(["docs/DOES_NOT_EXIST.md", "--dry-run"])
    out = capsys.readouterr().out
    assert "SKIP" in out and rc == 0


def test_dry_run_sends_nothing(monkeypatch, capsys):
    def explode(*a, **k):
        raise AssertionError("dry run must not POST")
    monkeypatch.setattr(pd, "post", explode)
    pd.main(["--dry-run"])
    assert "DRY RUN" in capsys.readouterr().out


def test_refused_file_is_never_posted(monkeypatch, tmp_path, capsys):
    doc = tmp_path / "leaky.md"
    doc.write_text("# Leaky\n\nPLATFORM_SECRET=0123456789abcdef0123\n")
    monkeypatch.setattr(pd, "_env", lambda k: "https://x" if "URL" in k else "s")
    monkeypatch.setattr(pd, "post", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("refused file must not be posted")))
    rc = pd.main([str(doc)])
    assert rc == 1 and "REFUSED" in capsys.readouterr().out
