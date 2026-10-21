"""Tests for forge.session.cleanup module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from forge.install.project_compat import (
    ProjectCompatibilityError,
    ProjectCompatibilitySkip,
)
from forge.session.cleanup import (
    SessionCleanupResult,
    auto_clean_old_sessions,
    clean_old_sessions,
)


def _make_entry(last_accessed_at: str, **kwargs):
    """Create a mock SessionIndexEntry with the given last_accessed_at."""
    entry = MagicMock()
    entry.last_accessed_at = last_accessed_at
    entry.forge_root = "/project"
    entry.worktree_path = "/project"
    for k, v in kwargs.items():
        setattr(entry, k, v)
    return entry


def _iso_days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


@pytest.fixture
def cleanup_project(tmp_path, monkeypatch):
    from forge.session import IndexStore, create_session_state
    from tests.fixtures.session_state import publish_session

    root = tmp_path / "project"
    root.mkdir()
    (root / ".forge").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.chdir(root)

    def seed(name, age=60, *, parent=None, project=None):
        project = project or root
        project.mkdir(parents=True, exist_ok=True)
        state = create_session_state(name, worktree_path=str(project), parent_session=parent)
        state.forge_root = str(project)
        state.last_accessed_at = _iso_days_ago(age) if isinstance(age, int) else age
        publish_session(IndexStore(), state, project, forge_root=str(project))
        IndexStore().update_session(name, last_accessed_at=state.last_accessed_at, forge_root=str(project))
        return state

    return root, seed


class TestCleanOldSessions:
    def test_empty_sessions(self, cleanup_project):
        assert clean_old_sessions(30).is_empty

    def test_selects_old_sessions_and_keeps_recent(self, cleanup_project):
        from forge.session import SessionStore

        root, seed = cleanup_project
        seed("old-one", 60)
        seed("old-two", 45)
        seed("recent", 5)
        result = clean_old_sessions(30)
        assert sorted(result.deleted) == ["old-one", "old-two"]
        assert SessionStore(str(root), "recent").exists()

    def test_preview_uses_same_selection_without_writing(self, cleanup_project):
        from forge.session import IndexStore, SessionStore

        root, seed = cleanup_project
        seed("old")
        index = IndexStore().index_path
        before = index.read_bytes(), index.stat().st_mtime_ns
        result = clean_old_sessions(30, apply=False)
        assert [plan.name for plan in result.plans] == ["old"]
        assert result.deleted == []
        assert SessionStore(str(root), "old").exists()
        assert (index.read_bytes(), index.stat().st_mtime_ns) == before

    def test_skips_active_sessions_even_with_force(self, cleanup_project):
        import os

        from forge.session.active import ActiveSessionStore

        root, seed = cleanup_project
        seed("active-old")
        seed("dead-old")
        ActiveSessionStore().upsert_session(
            "active-old",
            forge_root=str(root),
            worktree_path=str(root),
            launch_mode="host",
            launcher_pid=os.getpid(),
        )
        result = clean_old_sessions(30, force=True)
        assert result.deleted == ["dead-old"]
        assert result.skipped_active == ["active-old"]

    def test_skips_unparseable_timestamps(self, cleanup_project):
        _, seed = cleanup_project
        seed("bad-ts", "not-a-date")
        seed("old")
        result = clean_old_sessions(30)
        assert result.deleted == ["old"]
        assert result.skipped_unparseable == ["bad-ts"]

    def test_continues_after_apply_failure(self, cleanup_project, monkeypatch):
        from forge.session.deletion import apply_session_deletion

        _, seed = cleanup_project
        seed("fail")
        seed("succeed")

        def apply(index, plan):
            if plan.name == "fail":
                raise OSError("disk full")
            return apply_session_deletion(index, plan)

        monkeypatch.setattr("forge.session.cleanup.apply_session_deletion", apply)
        result = clean_old_sessions(30)
        assert result.deleted == ["succeed"]
        assert result.failed == [("fail", "disk full")]

    @pytest.mark.parametrize("force", [False, True])
    def test_planning_keeps_requested_worktree_policy(self, cleanup_project, force):
        _, seed = cleanup_project
        seed("old")
        result = clean_old_sessions(30, force=force, delete_worktree=True, apply=False)
        assert result.plans[0].force is force
        assert result.plans[0].delete_worktree
        assert result.plans[0].native is None

    def test_active_store_failure_aborts_cleanup(self, cleanup_project, monkeypatch):
        _, seed = cleanup_project
        seed("old")

        def fail(self):
            raise RuntimeError("corrupt")

        monkeypatch.setattr("forge.session.cleanup.ActiveSessionStore.peek_sessions_strict", fail)
        result = clean_old_sessions(30)
        assert result.deleted == []
        assert result.aborted_error == "corrupt"
        assert result.should_exit_nonzero

    def test_dependency_refusal_is_identical_before_and_after_apply(self, cleanup_project):
        from forge.session import SessionStore

        root, seed = cleanup_project
        seed("parent")
        seed("child", parent="parent")
        preview = clean_old_sessions(30, apply=False)
        result = clean_old_sessions(30)
        assert preview.failed == result.failed
        assert result.deleted == ["child"]
        assert SessionStore(str(root), "parent").exists()

    @pytest.mark.parametrize("state", ["incompatible", "malformed", "unsupported_schema", "unreadable"])
    def test_project_compatibility_skip_is_typed_and_other_roots_continue(self, cleanup_project, state):
        root, seed = cleanup_project
        seed("refused")
        seed("compatible", project=root.parent / "compatible")
        refusal = ProjectCompatibilityError(str(root / ".forge/project.toml"), f"{state} pin", state=state)
        with patch(
            "forge.session.cleanup.enforce_project_compatibility",
            side_effect=[refusal, None],
        ):
            result = clean_old_sessions(30, force=True)
        assert result.deleted == ["compatible"]
        assert result.should_exit_nonzero
        assert result.skipped_project_compatibility == [
            ProjectCompatibilitySkip(
                target="refused",
                forge_root=str(root),
                state=state,
                reason=f"{state} pin",
                recovery=refusal.recovery,
            )
        ]


class TestAutoCleanOldSessions:
    @patch("forge.session.cleanup.get_runtime_config")
    def test_noop_when_disabled(self, mock_config):
        mock_config.return_value.session_retention_days = 0
        auto_clean_old_sessions()

    @patch("forge.session.cleanup.clean_old_sessions")
    @patch("forge.session.cleanup.get_runtime_config")
    def test_calls_clean_with_config_value(self, mock_config, mock_clean):
        mock_config.return_value.session_retention_days = 90
        mock_clean.return_value = SessionCleanupResult()

        auto_clean_old_sessions()
        mock_clean.assert_called_once_with(
            older_than_days=90,
            delete_worktree=False,
            delete_branch=False,
            force=True,
        )

    @patch("forge.session.cleanup.get_runtime_config", side_effect=RuntimeError("boom"))
    def test_swallows_exceptions(self, _mock_config):
        """auto_clean_old_sessions never raises."""
        auto_clean_old_sessions()

    @patch("forge.session.cleanup.clean_old_sessions")
    @patch("forge.session.cleanup.get_runtime_config")
    def test_logs_project_compatibility_skips_without_raising(self, mock_config, mock_clean, caplog):
        mock_config.return_value.session_retention_days = 30
        mock_clean.return_value = SessionCleanupResult(
            skipped_project_compatibility=[
                ProjectCompatibilitySkip(
                    target="old-refused",
                    forge_root="/refused",
                    state="incompatible",
                    reason="version mismatch",
                    recovery="use a satisfying Forge",
                )
            ]
        )

        with caplog.at_level("DEBUG", logger="forge.session.cleanup"):
            auto_clean_old_sessions()

        assert "Auto-clean skipped session 'old-refused'" in caplog.text
        assert "incompatible" in caplog.text


class TestSessionCleanupResult:
    def test_default_empty(self):
        result = SessionCleanupResult()
        assert result.deleted == []
        assert result.skipped_active == []
        assert result.skipped_unparseable == []
        assert result.skipped_project_compatibility == []
        assert result.failed == []
