"""Tests for session cleanup utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session.claude.cleanup import (
    CleanupResult,
    cleanup_session,
    delete_session_data,
)


@pytest.fixture
def mock_claude_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a mock ~/.claude/projects directory."""
    claude_projects = tmp_path / ".claude" / "projects"
    claude_projects.mkdir(parents=True)

    # Mock the path functions
    monkeypatch.setattr(
        "forge.session.claude.cleanup.get_transcript_path",
        lambda root, sid: claude_projects / f"-test-{sid}.jsonl",
    )
    monkeypatch.setattr(
        "forge.session.claude.cleanup.find_agent_logs",
        lambda root, sid: [],  # Default to no agent logs
    )

    return claude_projects


class TestCleanupResult:
    """Tests for CleanupResult dataclass."""

    def test_total_deleted_empty(self) -> None:
        """Total deleted should be 0 for empty result."""
        result = CleanupResult()
        assert result.total_deleted == 0

    def test_total_deleted_counts_both(self) -> None:
        """Total deleted should count transcripts and logs."""
        result = CleanupResult(
            deleted_transcripts=[Path("/a.jsonl"), Path("/b.jsonl")],
            deleted_agent_logs=[Path("/agent.jsonl")],
        )
        assert result.total_deleted == 3

    def test_has_failures_false_when_empty(self) -> None:
        """has_failures should be False when no failures."""
        result = CleanupResult()
        assert result.has_failures is False

    def test_has_failures_true_when_failures(self) -> None:
        """has_failures should be True when failures present."""
        result = CleanupResult(
            failed=[(Path("/bad.jsonl"), "Permission denied")],
        )
        assert result.has_failures is True


class TestDeleteSessionData:
    """Tests for delete_session_data()."""

    def test_deletes_transcript_files(self, mock_claude_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should delete transcript files."""
        # Create a transcript file
        transcript = mock_claude_dir / "-test-session-123.jsonl"
        transcript.write_text('{"test": "data"}')

        result = delete_session_data("/test/project", ["session-123"])

        assert not transcript.exists()
        assert len(result.deleted_transcripts) == 1

    def test_handles_missing_transcripts(self, mock_claude_dir: Path) -> None:
        """Should not fail when transcript doesn't exist."""
        result = delete_session_data("/test/project", ["nonexistent-session"])

        assert result.total_deleted == 0
        assert not result.has_failures

    def test_deletes_multiple_sessions(self, mock_claude_dir: Path) -> None:
        """Should delete multiple session transcripts."""
        # Create multiple transcripts
        t1 = mock_claude_dir / "-test-session-1.jsonl"
        t2 = mock_claude_dir / "-test-session-2.jsonl"
        t1.write_text("{}")
        t2.write_text("{}")

        result = delete_session_data("/test/project", ["session-1", "session-2"])

        assert not t1.exists()
        assert not t2.exists()
        assert len(result.deleted_transcripts) == 2

    def test_records_failures(self, mock_claude_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should record failed deletions."""
        # Create a transcript but make deletion fail
        transcript = mock_claude_dir / "-test-session-123.jsonl"
        transcript.mkdir()  # Creating dir instead of file will cause unlink to fail

        result = delete_session_data("/test/project", ["session-123"])

        assert result.has_failures
        assert len(result.failed) == 1
        assert transcript in [p for p, _ in result.failed]

    def test_deletes_agent_logs(self, mock_claude_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should delete agent log files."""
        # Create agent log
        agent_log = mock_claude_dir / "agent-abc.jsonl"
        agent_log.write_text('{"session_id": "session-123"}')

        # Mock find_agent_logs to return our log
        monkeypatch.setattr(
            "forge.session.claude.cleanup.find_agent_logs",
            lambda root, sid: [agent_log] if sid == "session-123" else [],
        )

        result = delete_session_data("/test/project", ["session-123"])

        assert not agent_log.exists()
        assert len(result.deleted_agent_logs) == 1


class TestCleanupSession:
    """Tests for cleanup_session() convenience function."""

    def test_cleans_current_session_id(self, mock_claude_dir: Path) -> None:
        """Should clean up single session ID (1:1 model)."""
        current = mock_claude_dir / "-test-current-id.jsonl"
        current.write_text("{}")

        result = cleanup_session(
            project_root="/test/project",
            claude_session_id="current-id",
        )

        assert len(result.deleted_transcripts) == 1

    def test_handles_none_current_id(self, mock_claude_dir: Path) -> None:
        """Should handle None current session ID."""
        result = cleanup_session(
            project_root="/test/project",
            claude_session_id=None,
        )

        assert result.total_deleted == 0

    def test_handles_all_none(self, mock_claude_dir: Path) -> None:
        """Should handle None session ID."""
        result = cleanup_session(
            project_root="/test/project",
            claude_session_id=None,
        )

        assert result.total_deleted == 0

    def test_cleans_artifact_session_ids(self, mock_claude_dir: Path) -> None:
        """Should clean up rollover UUIDs referenced by transcript artifacts."""
        current = mock_claude_dir / "-test-current-id.jsonl"
        rollover = mock_claude_dir / "-test-rollover-id.jsonl"
        current.write_text("{}")
        rollover.write_text("{}")

        result = cleanup_session(
            project_root="/test/project",
            claude_session_id="current-id",
            artifact_session_ids=["rollover-id", "current-id", "rollover-id"],
        )

        assert not current.exists()
        assert not rollover.exists()
        assert len(result.deleted_transcripts) == 2
