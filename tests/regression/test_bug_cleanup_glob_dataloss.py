"""Regression: glob-aware cleanup must not delete config files when worktree removal fails.

Bug: After adding glob patterns to DEFAULT_CONFIG_ALLOWLIST, cleanup_worktree()
deleted nested .claude/settings.local.json BEFORE attempting git worktree remove.
If removal failed (dirty worktree from user changes), the config files were already
gone -- data loss regression from the glob expansion.

Fix: Try worktree removal first. Only delete config files on DirtyWorktreeError,
then retry. If removal fails for other reasons, config files are preserved.

Affected file: src/forge/session/worktree/cleanup.py
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.session.exceptions import DirtyWorktreeError, GitWorktreeError
from forge.session.worktree.cleanup import cleanup_worktree

pytestmark = pytest.mark.regression


def test_cleanup_preserves_config_on_non_dirty_failure(tmp_path: Path) -> None:
    """Config files survive when removal fails for reasons other than dirty state."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".claude").mkdir()
    (worktree / ".claude" / "settings.local.json").write_text('{"user": true}')

    with (
        patch(
            "forge.session.worktree.cleanup.remove_worktree",
            side_effect=GitWorktreeError("remove", "lock held", 1),
        ),
        patch("forge.session.worktree.cleanup.get_main_repo_root", return_value=tmp_path),
    ):
        result = cleanup_worktree(worktree)

    assert result.worktree_removed is False
    assert len(result.errors) == 1
    assert result.config_files_removed == []
    assert (worktree / ".claude" / "settings.local.json").exists()


def test_cleanup_removes_config_only_on_dirty_retry(tmp_path: Path) -> None:
    """Config files are removed only when worktree is dirty, enabling retry."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".claude").mkdir()
    (worktree / ".claude" / "settings.local.json").write_text('{"user": true}')

    call_count = 0

    def remove_side_effect(path, force=False, repo_root=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise DirtyWorktreeError(str(path))
        return True

    with (
        patch("forge.session.worktree.cleanup.remove_worktree", side_effect=remove_side_effect),
        patch("forge.session.worktree.cleanup.get_main_repo_root", return_value=tmp_path),
        patch("forge.session.worktree.config_copy.is_file_tracked", return_value=False),
    ):
        result = cleanup_worktree(worktree)

    assert result.worktree_removed is True
    assert len(result.config_files_removed) > 0
    assert call_count == 2
