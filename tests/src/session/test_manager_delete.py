"""Targeted tests for SessionManager.delete_session control flow."""

from __future__ import annotations

from pathlib import Path

import pytest

import forge.session.claude.cleanup as cleanup_mod
import forge.session.worktree as worktree_pkg
import forge.session.worktree.cleanup as worktree_cleanup_mod
from forge.session import ForgeSessionError, IndexStore, SessionManager, SessionStore
from forge.session.manager import _tracked_derivation_transcript_session_ids
from forge.session.models import Derivation


def _init_project(path: Path) -> None:
    """Create a minimal Forge-enabled project root for manager tests."""
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    (path / ".forge").mkdir()
    (path / ".claude").mkdir()


def test_tracked_derivation_transcript_ids_include_rewind_relocated_id() -> None:
    """Shared-transcript scans must see rewind's fresh relocated UUID."""
    derivation = Derivation(
        parent_session="parent",
        rewind_relocated_session_id="296385c3-9753-452b-af3d-e9170233c613",
    )

    assert _tracked_derivation_transcript_session_ids(derivation) == [
        "296385c3-9753-452b-af3d-e9170233c613"
    ]
    assert _tracked_derivation_transcript_session_ids(
        {"rewind_relocated_session_id": "296385c3-9753-452b-af3d-e9170233c613"}
    ) == ["296385c3-9753-452b-af3d-e9170233c613"]


def test_delete_preserves_session_when_worktree_cleanup_reports_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup errors should abort deletion before transcripts/index/manifest are removed."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    project = tmp_path / "project"
    _init_project(project)
    monkeypatch.chdir(project)

    manager = SessionManager(index_store=IndexStore())
    manager.start_session(name="cleanup-fail-test", worktree_path=str(project))
    store = SessionStore(str(project), "cleanup-fail-test")

    def _mark_worktree(manifest) -> None:
        assert manifest.worktree is not None
        manifest.worktree.is_worktree = True
        manifest.worktree.branch = "cleanup-fail-branch"
        manifest.confirmed.claude_session_id = "cleanup-fail-uuid"

    store.update(timeout_s=5.0, mutate=_mark_worktree)

    captured = {"cleanup_called": False, "worktree_cleanup_called": False}

    def fake_cleanup_session(project_root, claude_session_id, artifact_session_ids=None):
        captured["cleanup_called"] = True
        return cleanup_mod.CleanupResult()

    def fake_cleanup_worktree(**kwargs):
        captured["worktree_cleanup_called"] = True
        return worktree_pkg.CleanupResult(errors=["branch still in use"])

    monkeypatch.setattr(cleanup_mod, "cleanup_session", fake_cleanup_session)
    monkeypatch.setattr(worktree_pkg, "cleanup_worktree", fake_cleanup_worktree)
    monkeypatch.setattr(worktree_cleanup_mod, "cleanup_worktree", fake_cleanup_worktree)
    monkeypatch.setattr(
        SessionManager,
        "_find_co_resident_sessions",
        lambda self, worktree_path, exclude: [],
    )

    with pytest.raises(ForgeSessionError, match="branch still in use"):
        manager.delete_session("cleanup-fail-test", delete_branch=True, force=True)

    assert captured["worktree_cleanup_called"] is True
    assert captured["cleanup_called"] is False
    assert manager.session_exists("cleanup-fail-test") is True
    assert store.exists() is True
