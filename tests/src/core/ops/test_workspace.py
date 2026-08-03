"""Tests for the workspace worktree/session join."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError, ListSessionsItem, ListSessionsResult
from forge.core.ops.workspace import list_workspace_worktrees
from forge.session.exceptions import GitWorktreeError
from forge.session.models import SessionIndexEntry
from forge.session.workspace import Workspace, WorkspaceWorktree


def test_join_counts_each_session_row_and_includes_empty_worktrees(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    other_workspace = tmp_path / "other-workspace"
    missing = tmp_path / "missing"
    for path in (primary, linked, other_workspace):
        path.mkdir()
    linked_alias = tmp_path / "linked-alias"
    linked_alias.symlink_to(linked, target_is_directory=True)

    workspace = Workspace(
        primary_root=primary,
        common_dir=primary / ".git",
        worktrees=(
            _worktree(primary, branch="main", is_primary=True),
            _worktree(linked, branch="feature"),
            _worktree(missing, branch="deleted", is_prunable=True, path_exists=False),
        ),
    )
    session_result = ListSessionsResult(
        sessions=[
            _session_item("shared", primary, active=True),
            _session_item("shared", linked_alias),
            _session_item("incognito", linked, active=True, is_incognito=True, legacy=True),
            _session_item("shared", other_workspace, project_root=other_workspace),
        ]
    )
    ctx = ExecutionContext(cwd=primary, worktree_root=primary, project_root=primary, forge_root=primary)

    with (
        patch("forge.core.ops.workspace.resolve_workspace", return_value=workspace),
        patch("forge.core.ops.workspace.list_sessions", return_value=session_result) as mock_list_sessions,
    ):
        result = list_workspace_worktrees(ctx=ctx)

    mock_list_sessions.assert_called_once_with(ctx=ctx, include_incognito=True, scope="workspace")
    assert result.primary_root == primary
    assert result.common_dir == primary / ".git"
    assert [(row.worktree.branch, row.sessions, row.active) for row in result.worktrees] == [
        ("main", 1, 1),
        ("feature", 2, 1),
        ("deleted", 0, 0),
    ]


def test_resolver_error_becomes_typed_op_error(tmp_path: Path) -> None:
    ctx = ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path)
    with patch(
        "forge.core.ops.workspace.resolve_workspace",
        side_effect=GitWorktreeError("list", "metadata unreadable", 1),
    ):
        with pytest.raises(ForgeOpError, match="Could not resolve workspace.*metadata unreadable"):
            list_workspace_worktrees(ctx=ctx)


def _worktree(
    path: Path,
    *,
    branch: str | None,
    is_primary: bool = False,
    is_prunable: bool = False,
    path_exists: bool = True,
) -> WorkspaceWorktree:
    return WorkspaceWorktree(
        checkout_root=path,
        branch=branch,
        head="a" * 40,
        is_primary=is_primary,
        is_bare=False,
        is_prunable=is_prunable,
        is_locked=False,
        is_detached=branch is None,
        path_exists=path_exists,
    )


def _session_item(
    name: str,
    checkout_root: Path,
    *,
    active: bool = False,
    is_incognito: bool = False,
    legacy: bool = False,
    project_root: Path | None = None,
) -> ListSessionsItem:
    entry = SessionIndexEntry(
        worktree_path=str(checkout_root),
        project_root=str(project_root or checkout_root.parent / "primary"),
        last_accessed_at="2026-08-03T00:00:00+00:00",
        is_incognito=is_incognito,
        forge_root=str(checkout_root),
        checkout_root="" if legacy else str(checkout_root),
    )
    return ListSessionsItem(
        name=name,
        entry=entry,
        proxy_template=None,
        model=None,
        models=(),
        is_active=active,
    )
