"""Tests for forge.session.cleanup module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from forge.session.cleanup import (
    SessionCleanupResult,
    auto_clean_old_sessions,
    clean_old_sessions,
)


def _make_entry(last_accessed_at: str, **kwargs):
    """Create a mock SessionIndexEntry with the given last_accessed_at."""
    entry = MagicMock()
    entry.last_accessed_at = last_accessed_at
    for k, v in kwargs.items():
        setattr(entry, k, v)
    return entry


def _iso_days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


class TestCleanOldSessions:
    @patch("forge.session.cleanup.ActiveSessionStore", autospec=True)
    @patch("forge.session.cleanup.SessionManager", autospec=True)
    def test_empty_sessions(self, mock_manager_cls, mock_active_cls):
        mock_manager_cls.return_value.list_sessions.return_value = []
        mock_active_cls.return_value.list_sessions.return_value = []

        result = clean_old_sessions(30)
        assert result.deleted == []
        assert result.skipped_active == []
        assert result.failed == []

    @patch("forge.session.cleanup.ActiveSessionStore", autospec=True)
    @patch("forge.session.cleanup.SessionManager", autospec=True)
    def test_keeps_recent_sessions(self, mock_manager_cls, mock_active_cls):
        manager = mock_manager_cls.return_value
        manager.list_sessions.return_value = [
            ("recent", _make_entry(_iso_days_ago(5))),
        ]
        mock_active_cls.return_value.list_sessions.return_value = []

        result = clean_old_sessions(30)
        assert result.deleted == []
        manager.delete_session.assert_not_called()

    @patch("forge.session.cleanup.ActiveSessionStore", autospec=True)
    @patch("forge.session.cleanup.SessionManager", autospec=True)
    def test_deletes_old_sessions(self, mock_manager_cls, mock_active_cls):
        manager = mock_manager_cls.return_value
        manager.list_sessions.return_value = [
            ("old-one", _make_entry(_iso_days_ago(60))),
            ("old-two", _make_entry(_iso_days_ago(45))),
            ("recent", _make_entry(_iso_days_ago(5))),
        ]
        mock_active_cls.return_value.list_sessions.return_value = []

        result = clean_old_sessions(30)
        assert sorted(result.deleted) == ["old-one", "old-two"]
        assert manager.delete_session.call_count == 2

    @patch("forge.session.cleanup.ActiveSessionStore", autospec=True)
    @patch("forge.session.cleanup.SessionManager", autospec=True)
    def test_skips_active_sessions(self, mock_manager_cls, mock_active_cls):
        manager = mock_manager_cls.return_value
        manager.list_sessions.return_value = [
            ("active-old", _make_entry(_iso_days_ago(60), forge_root="/project", worktree_path="/project")),
            ("dead-old", _make_entry(_iso_days_ago(60), forge_root="/project", worktree_path="/project")),
        ]
        active_entry = MagicMock()
        active_entry.forge_root = "/project"
        active_entry.worktree_path = "/project"
        mock_active_cls.return_value.list_sessions.return_value = [
            ("active-old", active_entry),
        ]

        result = clean_old_sessions(30)
        assert result.deleted == ["dead-old"]
        assert result.skipped_active == ["active-old"]

    @patch("forge.session.cleanup.ActiveSessionStore", autospec=True)
    @patch("forge.session.cleanup.SessionManager", autospec=True)
    def test_skips_unparseable_timestamps(self, mock_manager_cls, mock_active_cls):
        manager = mock_manager_cls.return_value
        manager.list_sessions.return_value = [
            ("bad-ts", _make_entry("not-a-date")),
            ("good-old", _make_entry(_iso_days_ago(60))),
        ]
        mock_active_cls.return_value.list_sessions.return_value = []

        result = clean_old_sessions(30)
        assert result.deleted == ["good-old"]
        assert result.skipped_unparseable == ["bad-ts"]

    @patch("forge.session.cleanup.ActiveSessionStore", autospec=True)
    @patch("forge.session.cleanup.SessionManager", autospec=True)
    def test_continues_after_delete_failure(self, mock_manager_cls, mock_active_cls):
        manager = mock_manager_cls.return_value
        manager.list_sessions.return_value = [
            ("fail", _make_entry(_iso_days_ago(60))),
            ("succeed", _make_entry(_iso_days_ago(60))),
        ]
        mock_active_cls.return_value.list_sessions.return_value = []

        manager.delete_session.side_effect = [RuntimeError("disk full"), None]

        result = clean_old_sessions(30)
        assert result.deleted == ["succeed"]
        assert len(result.failed) == 1
        assert result.failed[0][0] == "fail"
        assert "disk full" in result.failed[0][1]

    @patch("forge.session.cleanup.ActiveSessionStore", autospec=True)
    @patch("forge.session.cleanup.SessionManager", autospec=True)
    def test_passes_force_flag(self, mock_manager_cls, mock_active_cls):
        """force=True is passed through to delete_session."""
        manager = mock_manager_cls.return_value
        manager.list_sessions.return_value = [
            ("old", _make_entry(_iso_days_ago(60))),
        ]
        mock_active_cls.return_value.list_sessions.return_value = []

        clean_old_sessions(30, force=True, delete_worktree=True)
        manager.delete_session.assert_called_once()
        call_kwargs = manager.delete_session.call_args
        assert call_kwargs[0][0] == "old"
        assert call_kwargs[1]["force"] is True
        assert call_kwargs[1]["delete_worktree"] is True

    @patch("forge.session.cleanup.ActiveSessionStore", autospec=True)
    @patch("forge.session.cleanup.SessionManager", autospec=True)
    def test_default_force_is_false(self, mock_manager_cls, mock_active_cls):
        """Manual cleanup defaults to force=False (respects dirty worktrees)."""
        manager = mock_manager_cls.return_value
        manager.list_sessions.return_value = [
            ("old", _make_entry(_iso_days_ago(60))),
        ]
        mock_active_cls.return_value.list_sessions.return_value = []

        clean_old_sessions(30)
        call_kwargs = manager.delete_session.call_args[1]
        assert call_kwargs["force"] is False

    @patch("forge.session.cleanup.ActiveSessionStore", autospec=True)
    @patch("forge.session.cleanup.SessionManager", autospec=True)
    def test_active_store_failure_aborts_cleanup(self, mock_manager_cls, mock_active_cls):
        """If active store fails, cleanup aborts entirely (fail-closed)."""
        manager = mock_manager_cls.return_value
        manager.list_sessions.return_value = [
            ("old", _make_entry(_iso_days_ago(60))),
        ]
        mock_active_cls.return_value.list_sessions.side_effect = RuntimeError("corrupt")

        result = clean_old_sessions(30)
        assert result.deleted == []
        assert result.failed == []
        assert result.aborted is True
        assert result.aborted_error == "corrupt"
        assert result.should_exit_nonzero is True
        assert result.failure_items() == [("active session registry", "corrupt")]
        manager.delete_session.assert_not_called()


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
            delete_transcripts=True,
            delete_worktree=False,
            delete_branch=False,
            force=True,
        )

    @patch("forge.session.cleanup.get_runtime_config", side_effect=RuntimeError("boom"))
    def test_swallows_exceptions(self, _mock_config):
        """auto_clean_old_sessions never raises."""
        auto_clean_old_sessions()


class TestSessionCleanupResult:
    def test_default_empty(self):
        result = SessionCleanupResult()
        assert result.deleted == []
        assert result.skipped_active == []
        assert result.skipped_unparseable == []
        assert result.failed == []
