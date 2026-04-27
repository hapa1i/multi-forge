"""Tests for CLI startup queue processing.

These tests verify that non-exempt CLI commands (like `forge status`) trigger
pending-work queue processing, while exempt commands (like `forge hook`) skip it.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from forge.cli.main import main
from forge.core.workqueue import (
    enqueue_index_marker,
    enqueue_stop_marker,
    pending_work_dir,
)


def _create_test_marker(tmp_path: Path, session_id: str = "test-marker-123") -> Path:
    """Create a valid pending-work marker for testing."""
    marker = enqueue_stop_marker(
        session_id=session_id,
        worktree_path=tmp_path,
        session_name="test-session",
        transcript_snapshot_rel=f".forge/artifacts/test-session/transcripts/{session_id}.jsonl",
    )
    assert marker is not None
    return marker


class TestStartupQueueProcessing:
    """Tests for CLI startup queue processing behavior."""

    def test_forge_status_processes_queue(self, tmp_path: Path) -> None:
        """forge status (non-exempt) triggers pending-work processing and deletes markers."""
        # Create a marker
        marker = _create_test_marker(tmp_path)
        assert marker.is_file()

        # Run a non-exempt command: forge extensions status
        runner = CliRunner()
        runner.invoke(main, ["extensions", "status"])

        # Command may fail (no install state), but that's OK -
        # the important thing is startup processing ran first
        # Note: we don't assert exit_code because status may fail without install

        # Marker should be deleted by startup processing
        assert not marker.is_file(), "Non-exempt command should process and delete pending-work markers"

    def test_forge_status_handles_empty_queue(self) -> None:
        """forge status handles empty queue gracefully (fast path)."""
        # Ensure queue directory doesn't exist
        queue_dir = pending_work_dir()
        assert not queue_dir.exists()

        runner = CliRunner()
        # Should not crash even with empty queue
        result = runner.invoke(main, ["status"])

        # Command completes (may have non-zero exit if no install state, but shouldn't crash)
        assert result.exception is None or isinstance(result.exception, SystemExit)


class TestExemptSubcommands:
    """Tests that exempt subcommands skip queue processing."""

    def test_forge_hook_skips_queue(self, tmp_path: Path) -> None:
        """forge hook (exempt) does NOT process pending-work queue."""
        # Create a marker
        marker = _create_test_marker(tmp_path)
        assert marker.is_file()

        # Run an exempt command: forge hook (with a simple subcommand)
        runner = CliRunner()
        # Send empty JSON to avoid parse errors
        runner.invoke(main, ["hook", "stop"], input="{}")

        # Marker should still exist (exempt command skips processing)
        assert marker.is_file(), "Exempt command (hook) should NOT process pending-work queue"

    def test_forge_status_line_skips_queue(self, tmp_path: Path) -> None:
        """forge status-line (exempt) does NOT process pending-work queue."""
        # Create a marker
        marker = _create_test_marker(tmp_path)
        assert marker.is_file()

        # Run an exempt command: forge status-line
        runner = CliRunner()
        runner.invoke(main, ["status-line"])

        # Marker should still exist (exempt command skips processing)
        assert marker.is_file(), "Exempt command (status-line) should NOT process pending-work queue"


class TestStartupQueueRobustness:
    """Tests for startup queue robustness (error handling)."""

    def test_corrupted_marker_does_not_crash_cli(self, tmp_path: Path) -> None:
        """Corrupted markers don't crash CLI startup and are moved to failed/."""
        queue_dir = pending_work_dir()
        queue_dir.mkdir(parents=True, exist_ok=True)

        # Create a corrupted marker
        corrupt_marker = queue_dir / "corrupted.json"
        corrupt_marker.write_text("not valid json")

        # Run non-exempt command (extensions status triggers startup processing)
        runner = CliRunner()
        result = runner.invoke(main, ["extensions", "status"])

        # Should not crash (best-effort processing)
        assert result.exception is None or isinstance(result.exception, SystemExit)

        # Corrupted marker should be moved to failed/ (not stuck in queue)
        assert not corrupt_marker.is_file()
        assert (queue_dir / "failed" / "corrupted.json").is_file()

    def test_multiple_markers_processed(self, tmp_path: Path) -> None:
        """Multiple markers are processed by startup."""
        markers = []
        for i in range(3):
            marker = _create_test_marker(tmp_path, session_id=f"multi-{i}")
            markers.append(marker)

        assert all(m.is_file() for m in markers)

        # Run non-exempt command
        runner = CliRunner()
        runner.invoke(main, ["extensions", "status"])

        # All markers should be deleted
        assert all(not m.is_file() for m in markers), "All valid markers should be processed"


def _create_index_marker_with_transcript(tmp_path: Path, session_id: str = "test-idx-123") -> Path:
    """Create a valid index marker AND its backing transcript file.

    The real index handler requires the transcript file to exist on disk.
    Creates a minimal .git dir so resolve_project_root finds the project root.
    """
    # Create .git so resolve_project_root works
    (tmp_path / ".git").mkdir(exist_ok=True)

    # Create the transcript file the marker payload references
    transcript_rel = f".forge/artifacts/test-session/transcripts/{session_id}.jsonl"
    transcript_abs = tmp_path / transcript_rel
    transcript_abs.parent.mkdir(parents=True, exist_ok=True)
    transcript_abs.write_text(
        '{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z",'
        '"message":{"role":"user","content":[{"type":"text","text":"hello"}]}}\n'
    )

    marker = enqueue_index_marker(
        session_id=session_id,
        worktree_path=tmp_path,
        session_name="test-session",
        transcript_snapshot_rel=transcript_rel,
    )
    assert marker is not None
    return marker


class TestIndexMarkerProcessing:
    """Tests for index marker processing during CLI startup."""

    def test_index_marker_deleted_on_startup(self, tmp_path: Path) -> None:
        """Index markers are processed and deleted by non-exempt CLI commands."""
        marker = _create_index_marker_with_transcript(tmp_path)
        assert marker.is_file()

        runner = CliRunner()
        runner.invoke(main, ["extensions", "status"])

        assert not marker.is_file(), "Index marker should be deleted by startup processing"

    def test_both_stop_and_index_markers_processed(self, tmp_path: Path) -> None:
        """Both stop and index markers from the same session are processed."""
        stop_marker = _create_test_marker(tmp_path, session_id="dual-test")
        index_marker = _create_index_marker_with_transcript(tmp_path, session_id="dual-test")

        assert stop_marker.is_file()
        assert index_marker.is_file()

        runner = CliRunner()
        runner.invoke(main, ["extensions", "status"])

        assert not stop_marker.is_file(), "Stop marker should be processed"
        assert not index_marker.is_file(), "Index marker should be processed"

    def test_exempt_command_skips_index_markers(self, tmp_path: Path) -> None:
        """Exempt commands (hook) do not process index markers."""
        marker = _create_index_marker_with_transcript(tmp_path)
        assert marker.is_file()

        runner = CliRunner()
        runner.invoke(main, ["hook", "stop"], input="{}")

        assert marker.is_file(), "Exempt command should not process index markers"

    def test_index_handler_creates_search_document(self, tmp_path: Path) -> None:
        """Index marker processing extracts and stores a search document."""
        _create_index_marker_with_transcript(tmp_path, session_id="doc-test")

        runner = CliRunner()
        runner.invoke(main, ["extensions", "status"])

        from forge.search.store import SearchDocumentStore

        store = SearchDocumentStore(forge_root=tmp_path)
        docs = store.read()
        assert any(d.session_id == "doc-test" for d in docs)
