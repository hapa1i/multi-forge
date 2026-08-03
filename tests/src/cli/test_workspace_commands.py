"""CLI tests for ``forge workspace worktrees``."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.ops.session import ForgeOpError
from forge.core.ops.workspace import ListWorkspaceWorktreesResult, WorkspaceWorktreeSummary
from forge.session.workspace import WorkspaceWorktree


def test_worktrees_json_has_pinned_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _result(tmp_path)
    monkeypatch.setattr("forge.cli.workspace.list_workspace_worktrees", lambda **_: result)

    invocation = CliRunner().invoke(main, ["workspace", "worktrees", "--json"])

    assert invocation.exit_code == 0, invocation.output
    assert invocation.stderr == ""
    payload = json.loads(invocation.stdout)
    assert payload == {
        "primary_root": str(tmp_path / "main"),
        "common_dir": str(tmp_path / "main" / ".git"),
        "worktrees": [
            {
                "checkout_root": str(tmp_path / "main"),
                "branch": "main",
                "head": "a" * 40,
                "is_primary": True,
                "is_bare": False,
                "is_prunable": False,
                "is_locked": False,
                "is_detached": False,
                "path_exists": True,
                "sessions": 2,
                "active": 1,
            },
            {
                "checkout_root": str(tmp_path / "missing-locked"),
                "branch": "portable",
                "head": "b" * 40,
                "is_primary": False,
                "is_bare": False,
                "is_prunable": False,
                "is_locked": True,
                "is_detached": False,
                "path_exists": False,
                "sessions": 0,
                "active": 0,
            },
            {
                "checkout_root": str(tmp_path / "missing-prunable"),
                "branch": "stale",
                "head": "c" * 40,
                "is_primary": False,
                "is_bare": False,
                "is_prunable": True,
                "is_locked": False,
                "is_detached": False,
                "path_exists": False,
                "sessions": 0,
                "active": 0,
            },
        ],
    }


def test_worktrees_human_output_uses_point_in_time_vocabulary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("forge.cli.workspace.list_workspace_worktrees", lambda **_: _result(tmp_path))

    invocation = CliRunner().invoke(main, ["workspace", "worktrees"])

    assert invocation.exit_code == 0, invocation.output
    assert "Workspace:" in invocation.stdout
    assert "2 sessions, 1 active" in invocation.stdout
    assert "missing (locked)" in invocation.stdout
    assert "missing (prunable)" in invocation.stdout
    assert "gone" not in invocation.stdout
    assert invocation.stderr == ""


def test_non_git_json_uses_null_common_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    member = _worktree(tmp_path, branch=None, head=None, is_primary=True)
    result = ListWorkspaceWorktreesResult(
        primary_root=tmp_path,
        common_dir=None,
        worktrees=(WorkspaceWorktreeSummary(worktree=member, sessions=0, active=0),),
    )
    monkeypatch.setattr("forge.cli.workspace.list_workspace_worktrees", lambda **_: result)

    invocation = CliRunner().invoke(main, ["workspace", "worktrees", "--json"])

    assert invocation.exit_code == 0, invocation.output
    assert json.loads(invocation.stdout)["common_dir"] is None


def test_worktrees_error_uses_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(**_: object) -> None:
        raise ForgeOpError("Could not resolve workspace: git binary not found in PATH")

    monkeypatch.setattr("forge.cli.workspace.list_workspace_worktrees", _fail)

    invocation = CliRunner().invoke(main, ["workspace", "worktrees", "--json"])

    assert invocation.exit_code == 1
    assert invocation.stdout == ""
    assert "git binary not found" in invocation.stderr


def test_workspace_read_does_not_trigger_session_retention_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_called = False

    def _cleanup() -> None:
        nonlocal cleanup_called
        cleanup_called = True

    monkeypatch.setattr(import_module("forge.cli.main"), "_auto_clean_sessions_best_effort", _cleanup)
    monkeypatch.setattr("forge.cli.workspace.list_workspace_worktrees", lambda **_: _result(tmp_path))

    invocation = CliRunner().invoke(main, ["workspace", "worktrees", "--json"])

    assert invocation.exit_code == 0, invocation.output
    assert cleanup_called is False


def _result(tmp_path: Path) -> ListWorkspaceWorktreesResult:
    primary = _worktree(tmp_path / "main", branch="main", head="a" * 40, is_primary=True)
    locked = _worktree(
        tmp_path / "missing-locked",
        branch="portable",
        head="b" * 40,
        is_locked=True,
        path_exists=False,
    )
    prunable = _worktree(
        tmp_path / "missing-prunable",
        branch="stale",
        head="c" * 40,
        is_prunable=True,
        path_exists=False,
    )
    return ListWorkspaceWorktreesResult(
        primary_root=primary.checkout_root,
        common_dir=primary.checkout_root / ".git",
        worktrees=(
            WorkspaceWorktreeSummary(worktree=primary, sessions=2, active=1),
            WorkspaceWorktreeSummary(worktree=locked, sessions=0, active=0),
            WorkspaceWorktreeSummary(worktree=prunable, sessions=0, active=0),
        ),
    )


def _worktree(
    checkout_root: Path,
    *,
    branch: str | None,
    head: str | None,
    is_primary: bool = False,
    is_locked: bool = False,
    is_prunable: bool = False,
    path_exists: bool = True,
) -> WorkspaceWorktree:
    return WorkspaceWorktree(
        checkout_root=checkout_root,
        branch=branch,
        head=head,
        is_primary=is_primary,
        is_bare=False,
        is_prunable=is_prunable,
        is_locked=is_locked,
        is_detached=False,
        path_exists=path_exists,
    )
