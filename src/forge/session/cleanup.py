"""Session age-based cleanup.

Mirrors the log management cleanup pattern (forge.cli.logs):
- auto_clean_old_sessions(): called on CLI startup (best-effort)
- clean_old_sessions(): core logic for both auto and manual cleanup

Uses SessionManager.delete_session() for all actual deletion — it already
handles manifests, index, transcripts, worktrees, co-resident sessions,
and active-registry cleanup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from forge.core.state import parse_iso
from forge.install.project_compat import (
    ProjectCompatibilityError,
    ProjectCompatibilitySkip,
    enforce_project_compatibility,
)
from forge.runtime_config import get_runtime_config
from forge.session import SessionManager
from forge.session.active import ActiveSessionStore

logger = logging.getLogger(__name__)


@dataclass
class SessionCleanupResult:
    """Result of a session cleanup operation.

    All skip categories are surfaced so --dry-run and CLI output can
    report every case. No silent drops.
    """

    deleted: list[str] = field(default_factory=list)
    skipped_active: list[str] = field(default_factory=list)
    skipped_unparseable: list[str] = field(default_factory=list)
    skipped_project_compatibility: list[ProjectCompatibilitySkip] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    aborted_error: str | None = None

    @property
    def aborted(self) -> bool:
        """Return True when cleanup stopped before evaluating sessions."""
        return self.aborted_error is not None

    @property
    def is_empty(self) -> bool:
        """Return True when cleanup found nothing actionable and did not abort."""
        return (
            not self.deleted
            and not self.skipped_active
            and not self.skipped_unparseable
            and not self.skipped_project_compatibility
            and not self.failed
            and self.aborted_error is None
        )

    @property
    def has_failures(self) -> bool:
        """Return True when cleanup aborted or any deletion failed."""
        return self.aborted_error is not None or bool(self.failed)

    @property
    def failure_count(self) -> int:
        """Return the number of surfaced cleanup failures."""
        return len(self.failed) + (1 if self.aborted_error is not None else 0)

    def failure_items(self) -> list[tuple[str, str]]:
        """Return cleanup failures as display-ready (name, error) pairs."""
        items = list(self.failed)
        if self.aborted_error is not None:
            items.insert(0, ("active session registry", self.aborted_error))
        return items

    @property
    def should_exit_nonzero(self) -> bool:
        """Return True when CLI cleanup should exit with an error."""
        return self.has_failures or bool(self.skipped_project_compatibility)

    @property
    def has_partial_success(self) -> bool:
        """Return True when cleanup deleted sessions before later failures."""
        return bool(self.deleted)

    @property
    def has_only_skips(self) -> bool:
        """Return True when cleanup evaluated sessions but only skipped them."""
        return (
            not self.deleted
            and not self.failed
            and self.aborted_error is None
            and bool(self.skipped_active or self.skipped_unparseable or self.skipped_project_compatibility)
        )

    @property
    def has_results(self) -> bool:
        """Return True when cleanup produced any visible outcome."""
        return not self.is_empty

    @property
    def summary_failed_count(self) -> int:
        """Return the number of failures for user-facing summaries."""
        return self.failure_count

    @property
    def summary_failed_label(self) -> str:
        """Return singular/plural label for failure summaries."""
        return "failure" if self.failure_count == 1 else "failures"


def clean_old_sessions(
    older_than_days: int,
    *,
    delete_transcripts: bool = True,
    delete_worktree: bool = False,
    delete_branch: bool = False,
    force: bool = False,
) -> SessionCleanupResult:
    """Delete sessions whose last_accessed_at is older than the threshold.

    Active sessions (per ActiveSessionStore) are always skipped. Sessions
    with unparseable timestamps are skipped and reported.

    Args:
        older_than_days: Age threshold in days.
        delete_transcripts: Delete Claude transcript files (~/.claude/projects/*.jsonl).
            Forge artifact snapshots (.forge/artifacts/) are never removed.
        delete_worktree: Delete git worktree directories (default False for safety).
        delete_branch: Delete git branches (requires delete_worktree=True).
        force: Bypass dirty-worktree protection (only relevant when delete_worktree=True).
    """
    result = SessionCleanupResult()
    manager = SessionManager()

    all_sessions = manager.list_sessions(include_incognito=True)

    # One-pass active session lookup (single lock/read/probe cycle).
    # Fail-closed: if we can't determine liveness, abort cleanup entirely.
    # Sessions are high-value objects — deleting one whose Claude process is
    # still running would destroy state.
    active_store = ActiveSessionStore()
    try:
        active_entries = active_store.list_sessions()
        # Use (name, forge_root) tuples to avoid cross-project false positives
        active_identities = {(name, ae.forge_root or ae.worktree_path) for name, ae in active_entries}
    except Exception as e:
        logger.debug("Cannot read active session registry, aborting cleanup: %s", e)
        result.aborted_error = str(e)
        return result

    for name, entry in all_sessions:
        # Check age
        try:
            dt = parse_iso(entry.last_accessed_at)
            age_days = (datetime.now(UTC) - dt).total_seconds() / 86400
        except (ValueError, TypeError, AttributeError):
            result.skipped_unparseable.append(name)
            continue

        if age_days <= older_than_days:
            continue

        # Check active status (scoped by forge_root to avoid cross-project false positives)
        entry_identity = (name, entry.forge_root or entry.worktree_path)
        if entry_identity in active_identities:
            result.skipped_active.append(name)
            continue

        # Delete (scoped by forge_root to avoid cross-project collisions).
        # Compatibility is intentionally checked per target so one refused
        # project cannot prevent cleanup of compatible projects.
        forge_root = entry.forge_root or entry.worktree_path
        try:
            enforce_project_compatibility(forge_root)
        except ProjectCompatibilityError as e:
            skip = ProjectCompatibilitySkip.from_error(
                target=name,
                forge_root=forge_root,
                error=e,
            )
            result.skipped_project_compatibility.append(skip)
            continue

        try:
            manager.delete_session(
                name,
                delete_transcripts=delete_transcripts,
                delete_worktree=delete_worktree,
                delete_branch=delete_branch,
                force=force,
                forge_root=forge_root,
            )
            result.deleted.append(name)
        except Exception as e:
            result.failed.append((name, str(e)))
            logger.debug("Failed to clean session '%s': %s", name, e, exc_info=True)

    return result


def auto_clean_old_sessions() -> None:
    """Auto-prune old sessions based on session_retention_days config.

    Called opportunistically on CLI startup. Best-effort: swallows all
    exceptions to avoid breaking CLI commands.

    Auto-cleanup uses safe defaults:
    - delete_transcripts=True (transcripts are useless without sessions)
    - delete_worktree=False (too destructive for automatic operation)
    - delete_branch=False (branches are lightweight, keep them)
    - force=True (safe because delete_worktree=False means dirty-check is never reached)
    """
    try:
        rc = get_runtime_config()
        if rc.session_retention_days <= 0:
            return

        cleanup_result = clean_old_sessions(
            older_than_days=rc.session_retention_days,
            delete_transcripts=True,
            delete_worktree=False,
            delete_branch=False,
            force=True,
        )
        if cleanup_result.deleted:
            logger.debug(
                "Auto-cleaned %d session(s) older than %d days",
                len(cleanup_result.deleted),
                rc.session_retention_days,
            )
        for skip in cleanup_result.skipped_project_compatibility:
            logger.debug(
                "Auto-clean skipped session '%s' at %s for project compatibility (%s): %s",
                skip.target,
                skip.forge_root,
                skip.state,
                skip.reason,
            )
    except Exception as e:
        logger.debug("Session auto-cleanup error (non-fatal): %s", e)
