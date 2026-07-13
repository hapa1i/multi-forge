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

import json

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


def _create_index_marker(workspace: ContainerLike, session_id: str = "compat-index") -> str:
    """Create a current-schema index marker targeting /workspace."""
    marker_id = f"idx-{session_id}"
    marker_path = f"$HOME/.forge/pending-work/{marker_id}.json"
    workspace.mkdir("$HOME/.forge/pending-work", parents=True)
    workspace.write_json(
        marker_path,
        {
            "schema_version": 1,
            "kind": "index",
            "marker_id": marker_id,
            "forge_version": "0.0.0",
            "created_at": "2025-01-01T00:00:00Z",
            "payload": {
                "session_id": session_id,
                "session_name": "compat-session",
                "worktree_path": "/workspace",
                "forge_root": "/workspace",
                "transcript_snapshot_rel": f".forge/artifacts/compat-session/transcripts/{session_id}.jsonl",
            },
            "attempt_count": 0,
            "last_attempt_at": None,
            "last_error": None,
        },
    )
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
        """A known-success command handles an empty queue without changing its exit."""
        # Ensure queue directory doesn't exist
        mock_claude_workspace.exec("rm -rf $HOME/.forge/pending-work")

        result = mock_claude_workspace.exec("forge model backend list --json")

        assert result.returncode == 0, result.stderr


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
        """Corrupted markers are quarantined without failing the foreground command."""
        # Create corrupted marker
        mock_claude_workspace.exec("mkdir -p $HOME/.forge/pending-work")
        mock_claude_workspace.exec("echo 'not valid json' > $HOME/.forge/pending-work/corrupted.json")

        result = mock_claude_workspace.exec("forge model backend list --json")

        assert result.returncode == 0, result.stderr
        json.loads(result.stdout)
        assert result.stderr == ""
        assert not mock_claude_workspace.file_exists("$HOME/.forge/pending-work/corrupted.json")
        assert mock_claude_workspace.file_exists("$HOME/.forge/pending-work/failed/corrupted.json")

    def test_incompatible_index_marker_retries_without_failing_foreground(
        self,
        mock_claude_workspace: ContainerLike,
    ) -> None:
        """The target-root pin blocks indexing through the bounded queue failure path."""
        mock_claude_workspace.mkdir("/workspace/.forge", parents=True)
        mock_claude_workspace.write_file(
            "/workspace/.forge/project.toml",
            'schema_version = 1\nrequired_forge = ">=9999"\n',
        )
        marker_path = _create_index_marker(mock_claude_workspace)

        result = mock_claude_workspace.exec("forge model backend list --json")

        assert result.returncode == 0, result.stderr
        json.loads(result.stdout)
        assert result.stderr == ""
        marker = mock_claude_workspace.read_json(marker_path)
        assert marker["attempt_count"] == 1
        assert "project compatibility refused (incompatible)" in marker["last_error"]
        assert not mock_claude_workspace.file_exists("/workspace/.forge/search-index")

    def test_poison_marker_quarantine_preserves_foreground_json_wire(
        self,
        mock_claude_workspace: ContainerLike,
    ) -> None:
        marker_path = _create_index_marker(mock_claude_workspace, session_id="poison")
        marker = mock_claude_workspace.read_json(marker_path)
        marker["attempt_count"] = 5
        mock_claude_workspace.write_json(marker_path, marker)

        result = mock_claude_workspace.exec("forge model backend list --json")

        assert result.returncode == 0, result.stderr
        json.loads(result.stdout)
        assert result.stderr == ""
        assert not mock_claude_workspace.file_exists(marker_path)
        assert mock_claude_workspace.file_exists("$HOME/.forge/pending-work/failed/idx-poison.json")

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
