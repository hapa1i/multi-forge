"""Transcript and agent log cleanup utilities.

This module provides utilities for deleting Claude session data:
- Transcript files (.jsonl)
- Agent log files (agent-*.jsonl)

Each Claude-runtime Forge session has one current ``claude_session_id`` even though
multiple process launches may reattach to that conversation.
If /compact or /clear rolled over to a new UUID, older raw transcript UUIDs may
also be tracked via transcript artifacts and should be cleaned up too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import find_agent_logs, get_transcript_path


@dataclass
class CleanupResult:
    """Result of a cleanup operation.

    Attributes:
        deleted_transcripts: Paths to successfully deleted transcript files.
        deleted_agent_logs: Paths to successfully deleted agent log files.
        failed: List of (path, error_message) tuples for failed deletions.
    """

    deleted_transcripts: list[Path] = field(default_factory=list)
    deleted_agent_logs: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def total_deleted(self) -> int:
        """Total number of files successfully deleted."""
        return len(self.deleted_transcripts) + len(self.deleted_agent_logs)

    @property
    def has_failures(self) -> bool:
        """Whether any deletions failed."""
        return len(self.failed) > 0


def delete_session_data(
    project_root: str,
    session_ids: list[str],
) -> CleanupResult:
    """Delete transcript and agent log files for given session IDs.

    Best-effort: continues even if some deletions fail.

    Args:
        project_root: Absolute path to project root (for transcript path encoding).
        session_ids: List of Claude session UUIDs to clean up.

    Returns:
        CleanupResult with lists of deleted files and any failures.
    """
    result = CleanupResult()

    for session_id in session_ids:
        # Delete transcript
        transcript_path = get_transcript_path(project_root, session_id)
        if transcript_path.exists():
            try:
                transcript_path.unlink()
                result.deleted_transcripts.append(transcript_path)
            except OSError as e:
                result.failed.append((transcript_path, str(e)))

        # Delete agent logs
        agent_logs = find_agent_logs(project_root, session_id)
        for log_path in agent_logs:
            try:
                log_path.unlink()
                result.deleted_agent_logs.append(log_path)
            except OSError as e:
                result.failed.append((log_path, str(e)))

    return result


def cleanup_session(
    project_root: str,
    claude_session_id: str | None,
    artifact_session_ids: list[str] | None = None,
) -> CleanupResult:
    """Clean up session data for the session's tracked Claude UUIDs.

    Args:
        project_root: Absolute path to project root.
        claude_session_id: Session UUID (from confirmed.claude_session_id).
        artifact_session_ids: Additional UUIDs referenced by transcript artifacts.

    Returns:
        CleanupResult with lists of deleted files and any failures.
    """
    session_ids: list[str] = []

    for session_id in [claude_session_id, *(artifact_session_ids or [])]:
        if session_id and session_id not in session_ids:
            session_ids.append(session_id)

    return delete_session_data(project_root, session_ids)
