"""Regression: --force should bypass schema validation on session delete.

Bug: `forge session delete <name> --force` raises ManifestCorruptedError when
the manifest has an unsupported schema version. Force-delete should always
succeed so users can clean up stale sessions.

Root cause: manager.delete_session() called store.read() unconditionally;
ManifestCorruptedError was not caught even when force=True.

Fix: Wrap store.read() in try/except; re-raise only when force=False.
"""

import json

import pytest

from forge.session.identity import make_scoped_key
from forge.session.models import SCHEMA_VERSION

pytestmark = pytest.mark.regression


@pytest.fixture
def forge_env(tmp_path, monkeypatch):
    """Set up isolated FORGE_HOME and CLAUDE_HOME with a session using a future schema."""
    forge_home = tmp_path / ".forge"
    sessions_dir = forge_home / "sessions"
    sessions_dir.mkdir(parents=True)

    worktree = tmp_path / "workspace"
    worktree.mkdir()
    monkeypatch.chdir(worktree)

    # Create index with the session registered (scoped key format)
    scoped_key = make_scoped_key("stale-session", str(worktree))
    index = {
        "version": 1,
        "sessions": {
            scoped_key: {
                "worktree_path": str(worktree),
                "project_root": str(worktree),
                "last_accessed_at": "2026-01-01T00:00:00Z",
                "is_fork": False,
                "is_incognito": False,
                "parent_session": None,
                "claude_session_id": None,
                "forge_root": str(worktree),
                "checkout_root": str(worktree),
                "relative_path": ".",
            }
        },
    }
    (sessions_dir / "index.json").write_text(json.dumps(index))

    # Create manifest with unsupported future schema version
    session_dir = worktree / ".forge" / "sessions" / "stale-session"
    session_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 999,
        "name": "stale-session",
        "created_at": "2026-01-01T00:00:00Z",
        "last_accessed_at": "2026-01-01T00:00:00Z",
        "intent": {},
        "overrides": {},
        "confirmed": {},
    }
    (session_dir / "forge.session.json").write_text(json.dumps(manifest))

    monkeypatch.setenv("FORGE_HOME", str(forge_home))
    monkeypatch.setenv("CLAUDE_HOME", str(worktree / ".claude"))
    return tmp_path


def test_delete_without_force_fails_on_schema_mismatch(forge_env):
    """delete without --force should raise on unsupported schema version."""
    from click.testing import CliRunner

    from forge.cli.session_manage import delete

    runner = CliRunner()
    result = runner.invoke(delete, ["stale-session"], input="y\n")

    assert result.exit_code != 0
    assert "incompatible schema version" in result.output.lower() or result.exception


def test_delete_with_force_succeeds_on_schema_mismatch(forge_env):
    """delete --yes --force should succeed even with unsupported schema version."""
    from click.testing import CliRunner

    from forge.cli.session_manage import delete

    runner = CliRunner()
    result = runner.invoke(delete, ["stale-session", "--yes", "--force"])

    assert result.exit_code == 0

    # Session directory should be cleaned up
    worktree = forge_env / "workspace"
    session_dir = worktree / ".forge" / "sessions" / "stale-session"
    assert not session_dir.exists()


def test_delete_with_force_succeeds_on_missing_required_fields(forge_env):
    """--yes --force should succeed even with structurally incomplete manifest."""
    from click.testing import CliRunner

    from forge.cli.session_manage import delete

    # Rewrite manifest with missing required fields (triggers ManifestValidationError)
    worktree = forge_env / "workspace"
    session_dir = worktree / ".forge" / "sessions" / "stale-session"
    manifest = {"schema_version": SCHEMA_VERSION}  # missing name, timestamps, intent, overrides
    (session_dir / "forge.session.json").write_text(json.dumps(manifest))

    runner = CliRunner()
    result = runner.invoke(delete, ["stale-session", "--yes", "--force"])

    assert result.exit_code == 0
    assert not session_dir.exists()


def test_delete_force_still_works_with_valid_schema(forge_env, monkeypatch):
    """Sanity check: --yes --force with a valid schema still works normally."""
    from click.testing import CliRunner

    from forge.cli.session_manage import delete

    # Rewrite manifest with valid schema
    worktree = forge_env / "workspace"
    session_dir = worktree / ".forge" / "sessions" / "stale-session"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "name": "stale-session",
        "created_at": "2026-01-01T00:00:00Z",
        "last_accessed_at": "2026-01-01T00:00:00Z",
        "intent": {},
        "overrides": {},
        "confirmed": {},
    }
    (session_dir / "forge.session.json").write_text(json.dumps(manifest))

    runner = CliRunner()
    result = runner.invoke(delete, ["stale-session", "--yes", "--force"])

    assert result.exit_code == 0
    assert not session_dir.exists()
