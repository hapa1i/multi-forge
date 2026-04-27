"""Tests for worktree cleanup utilities.

All tests require real git operations and run in Docker containers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.src.session.conftest import WorktreeWorkspace

# Mark all tests as Docker tests
pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


class TestIsWorktreeDirty:
    """Tests for is_worktree_dirty()."""

    def test_clean_worktree_returns_false(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Clean worktree should return False."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import is_worktree_dirty

wt = create_worktree('feature', cwd=Path('/workspace'))
is_dirty = is_worktree_dirty(Path(wt.worktree_path))
print(json.dumps({'is_dirty': is_dirty}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["is_dirty"] is False

    def test_dirty_worktree_returns_true(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Worktree with uncommitted changes should return True."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import is_worktree_dirty

wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Create uncommitted changes
(wt_path / 'new_file.txt').write_text('changes')

is_dirty = is_worktree_dirty(wt_path)
print(json.dumps({'is_dirty': is_dirty}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["is_dirty"] is True

    def test_staged_changes_returns_true(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Worktree with staged changes should return True."""
        result = worktree_workspace.run_python("""
import json
import subprocess
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import is_worktree_dirty

wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Create and stage a file
(wt_path / 'staged.txt').write_text('staged')
subprocess.run(['git', 'add', 'staged.txt'], cwd=str(wt_path), check=True, capture_output=True)

is_dirty = is_worktree_dirty(wt_path)
print(json.dumps({'is_dirty': is_dirty}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["is_dirty"] is True


class TestRemoveConfigFiles:
    """Tests for remove_config_files()."""

    def test_removes_untracked_config_files(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should remove untracked config files."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import remove_config_files

wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Create untracked config files
(wt_path / '.env').write_text('SECRET=value')
(wt_path / '.envrc').write_text('source_env')

removed = remove_config_files(wt_path)

env_removed = '.env' in removed
envrc_removed = '.envrc' in removed
env_exists = (wt_path / '.env').exists()
envrc_exists = (wt_path / '.envrc').exists()

print(json.dumps({
    'env_removed': env_removed,
    'envrc_removed': envrc_removed,
    'env_exists': env_exists,
    'envrc_exists': envrc_exists
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["env_removed"] is True
        assert result.data["envrc_removed"] is True
        assert result.data["env_exists"] is False
        assert result.data["envrc_exists"] is False

    def test_does_not_remove_tracked_files(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should not remove tracked config files."""
        result = worktree_workspace.run_python("""
import json
import subprocess
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import remove_config_files

# Create and track a file in main repo
(Path('/workspace') / '.envrc').write_text('tracked')
subprocess.run(['git', 'add', '.envrc'], cwd='/workspace', check=True, capture_output=True)
subprocess.run(['git', 'commit', '-m', 'Add .envrc'], cwd='/workspace', check=True, capture_output=True)

# Create worktree
wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

removed = remove_config_files(wt_path)

envrc_in_removed = '.envrc' in removed
envrc_exists = (wt_path / '.envrc').exists()

print(json.dumps({
    'envrc_in_removed': envrc_in_removed,
    'envrc_exists': envrc_exists
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        # Should not be in removed list
        assert result.data["envrc_in_removed"] is False
        # File should still exist
        assert result.data["envrc_exists"] is True

    def test_returns_empty_for_no_config_files(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should return empty list when no config files exist."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import remove_config_files

wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

removed = remove_config_files(wt_path)
print(json.dumps({'removed': removed}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["removed"] == []


class TestRemoveWorktree:
    """Tests for remove_worktree()."""

    def test_removes_clean_worktree(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should remove a clean worktree."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import remove_worktree

wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

removed = remove_worktree(wt_path)
exists_after = wt_path.exists()

print(json.dumps({'removed': removed, 'exists_after': exists_after}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["removed"] is True
        assert result.data["exists_after"] is False

    def test_raises_for_dirty_worktree(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should raise DirtyWorktreeError for dirty worktree."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import remove_worktree
from forge.session.exceptions import DirtyWorktreeError

wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Create uncommitted changes
(wt_path / 'new_file.txt').write_text('changes')

try:
    remove_worktree(wt_path)
    print(json.dumps({'error': None}))
except DirtyWorktreeError as e:
    print(json.dumps({'error': 'DirtyWorktreeError', 'path': e.path}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "DirtyWorktreeError"

    def test_force_removes_dirty_worktree(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should force remove dirty worktree when force=True."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import remove_worktree

wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Create uncommitted changes
(wt_path / 'new_file.txt').write_text('changes')

removed = remove_worktree(wt_path, force=True)
exists_after = wt_path.exists()

print(json.dumps({'removed': removed, 'exists_after': exists_after}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["removed"] is True
        assert result.data["exists_after"] is False

    def test_returns_false_for_nonexistent_path(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should return False for nonexistent path."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.cleanup import remove_worktree

result = remove_worktree(Path('/nonexistent'))
print(json.dumps({'result': result}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["result"] is False


class TestDeleteBranch:
    """Tests for delete_branch()."""

    def test_deletes_merged_branch(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should delete a merged branch."""
        result = worktree_workspace.run_python("""
import json
import subprocess
from pathlib import Path
from forge.session.worktree.cleanup import delete_branch
from forge.session.worktree.create import branch_exists

# Create and merge a branch
subprocess.run(['git', 'checkout', '-b', 'to-delete'], cwd='/workspace', check=True, capture_output=True)
Path('/workspace/new_file.txt').write_text('content')
subprocess.run(['git', 'add', 'new_file.txt'], cwd='/workspace', check=True, capture_output=True)
subprocess.run(['git', 'commit', '-m', 'Add file'], cwd='/workspace', check=True, capture_output=True)
subprocess.run(['git', 'checkout', 'main'], cwd='/workspace', check=True, capture_output=True)
subprocess.run(['git', 'merge', 'to-delete'], cwd='/workspace', check=True, capture_output=True)

result = delete_branch('to-delete', cwd=Path('/workspace'))
exists_after = branch_exists('to-delete', Path('/workspace'))

print(json.dumps({'deleted': result, 'exists_after': exists_after}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["deleted"] is True
        assert result.data["exists_after"] is False

    def test_raises_for_unmerged_branch_without_force(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should raise BranchNotMergedError for unmerged branch."""
        result = worktree_workspace.run_python("""
import json
import subprocess
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import delete_branch
from forge.session.exceptions import BranchNotMergedError

# Create worktree and branch
wt = create_worktree('unmerged', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Add a commit to make branch diverge
(wt_path / 'diverge.txt').write_text('diverged')
subprocess.run(['git', 'add', 'diverge.txt'], cwd=str(wt_path), check=True, capture_output=True)
subprocess.run(['git', 'commit', '-m', 'Diverge'], cwd=str(wt_path), check=True, capture_output=True)

# Remove worktree first
subprocess.run(['git', 'worktree', 'remove', '--force', str(wt_path)], cwd='/workspace', check=True, capture_output=True)

try:
    delete_branch('unmerged', cwd=Path('/workspace'))
    print(json.dumps({'error': None}))
except BranchNotMergedError as e:
    print(json.dumps({'error': 'BranchNotMergedError', 'branch': e.branch}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "BranchNotMergedError"
        assert result.data["branch"] == "unmerged"

    def test_force_deletes_unmerged_branch(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should force delete unmerged branch when force=True."""
        result = worktree_workspace.run_python("""
import json
import subprocess
from pathlib import Path
from forge.session.worktree.create import create_worktree, branch_exists
from forge.session.worktree.cleanup import delete_branch

# Create worktree and branch
wt = create_worktree('unmerged', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Add a commit
(wt_path / 'diverge.txt').write_text('diverged')
subprocess.run(['git', 'add', 'diverge.txt'], cwd=str(wt_path), check=True, capture_output=True)
subprocess.run(['git', 'commit', '-m', 'Diverge'], cwd=str(wt_path), check=True, capture_output=True)

# Remove worktree first
subprocess.run(['git', 'worktree', 'remove', '--force', str(wt_path)], cwd='/workspace', check=True, capture_output=True)

result = delete_branch('unmerged', cwd=Path('/workspace'), force=True)
exists_after = branch_exists('unmerged', Path('/workspace'))

print(json.dumps({'deleted': result, 'exists_after': exists_after}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["deleted"] is True
        assert result.data["exists_after"] is False

    def test_returns_false_for_nonexistent_branch(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should return False for nonexistent branch."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.cleanup import delete_branch

result = delete_branch('nonexistent', cwd=Path('/workspace'))
print(json.dumps({'result': result}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["result"] is False

    def test_raises_for_checked_out_branch(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should raise BranchInUseError for checked out branch."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import delete_branch
from forge.session.exceptions import BranchInUseError

# Create worktree (branch is checked out there)
create_worktree('in-use', cwd=Path('/workspace'))

try:
    delete_branch('in-use', cwd=Path('/workspace'))
    print(json.dumps({'error': None}))
except BranchInUseError as e:
    print(json.dumps({'error': 'BranchInUseError', 'branch': e.branch}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "BranchInUseError"
        assert result.data["branch"] == "in-use"


class TestCleanupWorktree:
    """Tests for cleanup_worktree()."""

    def test_full_cleanup_flow(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should perform full cleanup: config, worktree, branch."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree, branch_exists
from forge.session.worktree.cleanup import cleanup_worktree

# Create worktree with config file
wt = create_worktree('cleanup-test', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)
(wt_path / '.env').write_text('SECRET=value')

result = cleanup_worktree(
    wt_path,
    branch='cleanup-test',
    delete_branch_flag=True,
    force=True,  # Need force for unmerged branch
)

wt_exists = wt_path.exists()
br_exists = branch_exists('cleanup-test', Path('/workspace'))

print(json.dumps({
    'worktree_removed': result.worktree_removed,
    'branch_deleted': result.branch_deleted,
    'errors': result.errors,
    'wt_exists': wt_exists,
    'br_exists': br_exists
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["worktree_removed"] is True
        assert result.data["branch_deleted"] is True
        assert result.data["errors"] == []
        assert result.data["wt_exists"] is False
        assert result.data["br_exists"] is False

    def test_cleanup_without_branch_deletion(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should only remove worktree, not branch."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree, branch_exists
from forge.session.worktree.cleanup import cleanup_worktree

wt = create_worktree('keep-branch', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

result = cleanup_worktree(wt_path)

wt_exists = wt_path.exists()
br_exists = branch_exists('keep-branch', Path('/workspace'))

print(json.dumps({
    'worktree_removed': result.worktree_removed,
    'branch_deleted': result.branch_deleted,
    'wt_exists': wt_exists,
    'br_exists': br_exists
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["worktree_removed"] is True
        assert result.data["branch_deleted"] is False
        assert result.data["wt_exists"] is False
        # Branch should still exist
        assert result.data["br_exists"] is True

    def test_cleanup_captures_errors(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should capture errors instead of raising."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import cleanup_worktree

wt = create_worktree('error-test', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Create dirty worktree
(wt_path / 'dirty.txt').write_text('changes')

result = cleanup_worktree(wt_path)

print(json.dumps({
    'has_errors': len(result.errors) > 0,
    'worktree_removed': result.worktree_removed
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        # Should have error but not raise
        assert result.data["has_errors"] is True
        assert result.data["worktree_removed"] is False

    def test_cleanup_with_force(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should force cleanup dirty worktree."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.cleanup import cleanup_worktree

wt = create_worktree('force-test', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Create dirty worktree
(wt_path / 'dirty.txt').write_text('changes')

result = cleanup_worktree(wt_path, force=True)

print(json.dumps({
    'worktree_removed': result.worktree_removed,
    'errors': result.errors,
    'wt_exists': wt_path.exists()
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["worktree_removed"] is True
        assert result.data["errors"] == []
        assert result.data["wt_exists"] is False
