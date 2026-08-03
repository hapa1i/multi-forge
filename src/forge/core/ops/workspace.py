"""UI-agnostic operations for Git-derived workspace reads."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from forge.session import ForgeSessionError
from forge.session.workspace import WorkspaceWorktree, resolve_workspace

from .context import ExecutionContext
from .session import ForgeOpError, list_sessions

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkspaceWorktreeSummary:
    """A Git worktree plus its Forge session occupancy counts."""

    worktree: WorkspaceWorktree
    sessions: int
    active: int


@dataclass(frozen=True)
class ListWorkspaceWorktreesResult:
    """The derived workspace identity and all registered worktrees."""

    primary_root: Path
    common_dir: Path | None
    worktrees: tuple[WorkspaceWorktreeSummary, ...]


def list_workspace_worktrees(*, ctx: ExecutionContext) -> ListWorkspaceWorktreesResult:
    """Join Git worktree membership with Forge session occupancy.

    Incognito sessions count because this surface reports worktree occupancy,
    not the default visibility policy of ``forge session list``.
    """

    try:
        workspace = resolve_workspace(ctx.cwd)
    except ForgeSessionError as exc:
        raise ForgeOpError(f"Could not resolve workspace: {exc}") from exc

    session_result = list_sessions(ctx=ctx, include_incognito=True, scope="workspace")
    row_keys = tuple(_path_key(row.checkout_root) for row in workspace.worktrees)
    counts = {key: [0, 0] for key in row_keys}

    for item in session_result.sessions:
        checkout_root = item.entry.checkout_root or item.entry.worktree_path
        key = _path_key(Path(checkout_root))
        row_counts = counts.get(key)
        if row_counts is None:
            # The index read and Git read are independent snapshots.  A row can
            # legitimately disappear or move between them.
            _log.debug("Session %r belongs to an unavailable workspace row: %s", item.name, checkout_root)
            continue
        row_counts[0] += 1
        if item.is_active:
            row_counts[1] += 1

    summaries = tuple(
        WorkspaceWorktreeSummary(
            worktree=row,
            sessions=counts[key][0],
            active=counts[key][1],
        )
        for row, key in zip(workspace.worktrees, row_keys, strict=True)
    )
    return ListWorkspaceWorktreesResult(
        primary_root=workspace.primary_root,
        common_dir=workspace.common_dir,
        worktrees=summaries,
    )


def _path_key(path: Path) -> Path:
    """Normalize existing paths while preserving missing Git spellings."""

    try:
        return path.resolve() if path.exists() else path
    except OSError:
        return path
