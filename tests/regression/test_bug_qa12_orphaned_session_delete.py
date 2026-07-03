"""Regression: orphaned session manifest blocks start but can't be deleted.

Bug QA-012: When a session manifest exists on disk (.forge/sessions/<name>/)
but the session is missing from the global index (~/.forge/sessions/index.json),
`forge session start <name>` fails with "already exists" but
`forge session delete <name>` fails with "not found".

Root cause: start_session checks both index AND disk; delete only checks index.

Fix: CLI delete command detects orphaned manifest directories and removes them.
"""

import json

import pytest

pytestmark = pytest.mark.regression


@pytest.fixture
def forge_env(tmp_path, monkeypatch):
    """Set up isolated FORGE_HOME and CLAUDE_HOME with empty index."""
    forge_home = tmp_path / ".forge"
    claude_home = tmp_path / ".claude"
    sessions_dir = forge_home / "sessions"
    sessions_dir.mkdir(parents=True)

    index = {"version": 1, "sessions": {}}
    (sessions_dir / "index.json").write_text(json.dumps(index))

    monkeypatch.setenv("FORGE_HOME", str(forge_home))
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    return tmp_path


def test_delete_cleans_orphaned_manifest(forge_env, monkeypatch):
    """delete removes orphaned .forge/sessions/<name>/ when not in index."""
    from click.testing import CliRunner

    from forge.cli.session_manage import delete

    worktree = forge_env / "workspace"
    worktree.mkdir()
    monkeypatch.chdir(worktree)

    # Create orphaned manifest on disk (no index entry)
    session_dir = worktree / ".forge" / "sessions" / "orphan-session"
    session_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "name": "orphan-session",
        "intent": {},
        "confirmed": {},
    }
    (session_dir / "forge.session.json").write_text(json.dumps(manifest))

    assert session_dir.is_dir()

    runner = CliRunner()
    result = runner.invoke(delete, ["orphan-session"], input="y\n")

    assert result.exit_code == 0
    assert "orphaned" in result.output.lower()
    assert not session_dir.exists()


def _create_orphan(forge_env, monkeypatch):
    """Helper: create an orphaned session dir and return (worktree, session_dir)."""
    worktree = forge_env / "workspace"
    worktree.mkdir(exist_ok=True)
    monkeypatch.chdir(worktree)

    session_dir = worktree / ".forge" / "sessions" / "orphan-session"
    session_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "name": "orphan-session",
        "intent": {},
        "confirmed": {},
    }
    (session_dir / "forge.session.json").write_text(json.dumps(manifest))
    return worktree, session_dir


def test_delete_orphan_prompts_without_force(forge_env, monkeypatch):
    """delete prompts for confirmation when no --force on orphaned session."""
    from click.testing import CliRunner

    from forge.cli.session_manage import delete

    _, session_dir = _create_orphan(forge_env, monkeypatch)
    assert session_dir.is_dir()

    runner = CliRunner()
    result = runner.invoke(delete, ["orphan-session"], input="y\n")

    assert result.exit_code == 0
    assert "orphaned" in result.output.lower()
    assert not session_dir.exists()


def test_delete_orphan_cancelled_without_force(forge_env, monkeypatch):
    """delete respects user cancellation on orphan without --force."""
    from click.testing import CliRunner

    from forge.cli.session_manage import delete

    _, session_dir = _create_orphan(forge_env, monkeypatch)
    assert session_dir.is_dir()

    runner = CliRunner()
    result = runner.invoke(delete, ["orphan-session"], input="n\n")

    assert result.exit_code == 0
    assert session_dir.exists()


def test_delete_orphan_yes_flag_skips_prompt(forge_env, monkeypatch):
    """--yes flag skips confirmation for orphaned sessions."""
    from click.testing import CliRunner

    from forge.cli.session_manage import delete

    _, session_dir = _create_orphan(forge_env, monkeypatch)
    assert session_dir.is_dir()

    runner = CliRunner()
    result = runner.invoke(delete, ["orphan-session", "--yes"])

    assert result.exit_code == 0
    assert "orphaned" in result.output.lower()
    assert not session_dir.exists()


def test_delete_still_errors_when_truly_missing(forge_env, monkeypatch):
    """delete reports 'not found' when session is in neither index nor disk."""
    from click.testing import CliRunner

    from forge.cli.session_manage import delete

    worktree = forge_env / "workspace"
    worktree.mkdir()
    monkeypatch.chdir(worktree)

    runner = CliRunner()
    result = runner.invoke(delete, ["nonexistent", "--force"])

    assert result.exit_code != 0
    assert "not found" in result.output.lower()
