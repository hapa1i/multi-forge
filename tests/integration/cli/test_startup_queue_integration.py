"""Docker-based integration tests for CLI startup queue processing.

These tests run inside a session-scoped container (docker_in marker) for
complete filesystem isolation. They test the behavioral aspects of:
- Non-exempt commands processing pending-work queue
- Exempt commands skipping queue processing
- Robustness against corrupted markers

The startup queue lives at ~/.forge/pending-work/ and is processed by
non-exempt commands on startup.
"""

from __future__ import annotations

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


def _create_stop_marker(
    workspace: ContainerLike,
    session_id: str = "test-marker-123",
) -> str:
    """Create a valid pending-work stop marker."""
    marker_path = f"$HOME/.forge/pending-work/{session_id}.json"
    workspace.mkdir("$HOME/.forge/pending-work", parents=True)

    marker_data = {
        "schema_version": 1,
        "kind": "stop",
        "session_id": session_id,
        "session_name": "test-session",
        "worktree_path": "/workspace",
        "artifacts": {
            "transcript_snapshot_rel": f".forge/artifacts/test-session/transcripts/{session_id}.jsonl",
        },
        "created_at": "2025-01-01T00:00:00Z",
    }
    workspace.write_json(marker_path, marker_data)

    return marker_path


class TestStartupQueueProcessing:
    """Tests for CLI startup queue processing behavior."""

    def test_forge_status_processes_queue(self, mock_claude_workspace: ContainerLike) -> None:
        """forge extension status (non-exempt) triggers pending-work processing and deletes markers."""
        # Create a marker
        marker_path = _create_stop_marker(mock_claude_workspace)

        # Verify marker exists
        check = mock_claude_workspace.exec(f"test -f {marker_path} && echo exists || echo missing")
        assert "exists" in check.stdout

        # Run a non-exempt command: forge extension status
        # Command may fail (no install state), but startup processing runs first
        mock_claude_workspace.exec("forge extension status")

        # Marker should be deleted by startup processing
        check = mock_claude_workspace.exec(f"test -f {marker_path} && echo exists || echo missing")
        assert "missing" in check.stdout, "Non-exempt command should process and delete pending-work markers"

    def test_forge_status_handles_empty_queue(self, mock_claude_workspace: ContainerLike) -> None:
        """forge extension status handles empty queue gracefully (fast path)."""
        # Ensure queue directory doesn't exist
        mock_claude_workspace.exec("rm -rf $HOME/.forge/pending-work")

        # Should not crash even with empty queue
        result = mock_claude_workspace.exec("forge extension status")

        # Command completes (may fail if no install state, but shouldn't crash)
        # We just verify it produces output without crashing
        assert result.returncode >= 0


class TestExemptSubcommands:
    """Tests that exempt subcommands skip queue processing."""

    def test_forge_hook_skips_queue(self, mock_claude_workspace: ContainerLike) -> None:
        """forge hook (exempt) does NOT process pending-work queue."""
        marker_path = _create_stop_marker(mock_claude_workspace)

        # Verify marker exists
        check = mock_claude_workspace.exec(f"test -f {marker_path} && echo exists || echo missing")
        assert "exists" in check.stdout

        # Run an exempt command: forge hook (send empty JSON to stdin)
        mock_claude_workspace.exec("echo '{}' | forge hook stop")

        # Marker should still exist (exempt command skips processing)
        check = mock_claude_workspace.exec(f"test -f {marker_path} && echo exists || echo missing")
        assert "exists" in check.stdout, "Exempt command (hook) should NOT process pending-work queue"

    def test_forge_status_line_skips_queue(self, mock_claude_workspace: ContainerLike) -> None:
        """forge status-line (exempt) does NOT process pending-work queue."""
        marker_path = _create_stop_marker(mock_claude_workspace)

        # Verify marker exists
        check = mock_claude_workspace.exec(f"test -f {marker_path} && echo exists || echo missing")
        assert "exists" in check.stdout

        # Run an exempt command: forge status-line
        mock_claude_workspace.exec("forge status-line")

        # Marker should still exist (exempt command skips processing)
        check = mock_claude_workspace.exec(f"test -f {marker_path} && echo exists || echo missing")
        assert "exists" in check.stdout, "Exempt command (status-line) should NOT process pending-work queue"


class TestStartupQueueRobustness:
    """Tests for startup queue robustness (error handling)."""

    def test_corrupted_marker_does_not_crash_cli(self, mock_claude_workspace: ContainerLike) -> None:
        """Corrupted markers don't crash CLI startup."""
        # Create corrupted marker
        mock_claude_workspace.exec("mkdir -p $HOME/.forge/pending-work")
        mock_claude_workspace.exec("echo 'not valid json' > $HOME/.forge/pending-work/corrupted.json")

        # Run non-exempt command
        result = mock_claude_workspace.exec("forge status")

        # Should not crash (best-effort processing)
        # We just verify it produces some output without segfault etc
        assert result.returncode >= 0

        # Corrupted marker should still exist (not deleted on error)
        check = mock_claude_workspace.exec(
            "test -f $HOME/.forge/pending-work/corrupted.json && echo exists || echo missing"
        )
        assert "exists" in check.stdout

    def test_multiple_markers_processed(self, mock_claude_workspace: ContainerLike) -> None:
        """Multiple markers are processed by startup."""
        markers = []
        for i in range(3):
            marker_path = _create_stop_marker(mock_claude_workspace, session_id=f"multi-{i}")
            markers.append(marker_path)

        # Verify all markers exist
        for marker in markers:
            check = mock_claude_workspace.exec(f"test -f {marker} && echo exists || echo missing")
            assert "exists" in check.stdout

        # Run non-exempt command
        mock_claude_workspace.exec("forge extension status")

        # All markers should be deleted
        for marker in markers:
            check = mock_claude_workspace.exec(f"test -f {marker} && echo exists || echo missing")
            assert "missing" in check.stdout, "All valid markers should be processed"
