"""Unit tests for worktree creation utilities.

These are pure logic tests that don't require Docker.
Integration tests (requiring real git operations) are in test_create_integration.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.session.exceptions import (
    BranchExistsError,
    InvalidBranchNameError,
)
from forge.session.worktree.create import (
    get_worktree_for_branch,
    sanitize_branch_name,
    validate_branch_name,
)


class TestValidateBranchName:
    """Tests for validate_branch_name()."""

    def test_valid_simple_name(self) -> None:
        """Valid simple branch names should pass."""
        validate_branch_name("feature")
        validate_branch_name("fix-123")
        validate_branch_name("feature/auth")

    def test_invalid_name_raises(self) -> None:
        """Invalid branch names should raise InvalidBranchNameError."""
        with pytest.raises(InvalidBranchNameError) as exc_info:
            validate_branch_name("..invalid")
        assert exc_info.value.branch == "..invalid"

    def test_empty_name_raises(self) -> None:
        """Empty branch name should raise InvalidBranchNameError."""
        with pytest.raises(InvalidBranchNameError):
            validate_branch_name("")


class TestSanitizeBranchName:
    """Tests for sanitize_branch_name()."""

    def test_passthrough_valid_session_names(self) -> None:
        """Valid session names should pass through unchanged."""
        assert sanitize_branch_name("auth-feature") == "auth-feature"
        assert sanitize_branch_name("bugfix-123") == "bugfix-123"
        assert sanitize_branch_name("a1") == "a1"


class TestGetWorktreeForBranch:
    """Tests for get_worktree_for_branch()."""

    def test_returns_none_when_branch_not_in_worktree(self) -> None:
        """Branch not checked out in any worktree returns None."""
        porcelain = b"worktree /repo\0HEAD aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\0branch refs/heads/main\0\0"
        result = _mock_worktree_lookup(porcelain, "feature")
        assert result is None

    def test_returns_path_when_branch_in_worktree(self) -> None:
        """Branch checked out in a worktree returns its path."""
        porcelain = (
            b"worktree /repo\0HEAD aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\0branch refs/heads/main\0\0"
            b"worktree /repo-feature\0HEAD bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\0"
            b"branch refs/heads/feature\0\0"
        )
        result = _mock_worktree_lookup(porcelain, "feature")
        assert result == "/repo-feature"

    def test_returns_none_on_git_failure(self) -> None:
        """Git failure returns None (non-fatal)."""
        with patch("forge.session.workspace.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = b"failure"
            assert get_worktree_for_branch("feature", Path("/repo")) is None

    def test_partial_branch_name_no_false_positive(self) -> None:
        """Branch 'exec' should not match 'executor'."""
        porcelain = (
            b"worktree /repo-executor\0HEAD aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\0"
            b"branch refs/heads/executor\0\0"
        )
        result = _mock_worktree_lookup(porcelain, "exec")
        assert result is None


class TestBranchExistsErrorMessage:
    """Tests for BranchExistsError message variants."""

    def test_without_worktree_shows_branch_name(self) -> None:
        """Orphaned branch: message includes branch name."""
        e = BranchExistsError("feature")
        assert "feature" in str(e)
        assert "already exists" in str(e)
        assert e.worktree is None

    def test_with_worktree_shows_path_as_context(self) -> None:
        """Worktree-held branch: show the worktree path as context."""
        e = BranchExistsError("executor", worktree="/repo-executor")
        assert "checked out" in str(e)
        assert "/repo-executor" in str(e)
        assert "git worktree remove" not in str(e)


def _mock_worktree_lookup(porcelain_output: bytes, branch: str) -> str | None:
    """Run get_worktree_for_branch with mocked git output."""
    with patch("forge.session.workspace.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = porcelain_output
        return get_worktree_for_branch(branch, Path("/repo"))
