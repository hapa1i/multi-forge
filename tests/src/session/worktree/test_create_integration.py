"""Integration tests for worktree creation utilities.

These tests require Docker for isolation since they perform real git operations.
Split from test_create.py to follow testing-guidelines.md naming convention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.src.session.conftest import WorktreeWorkspace

# File-level markers for all tests in this module
pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


class TestGetRepoRoot:
    """Tests for get_repo_root() - requires real git repo."""

    def test_finds_repo_root(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should find repository root from repo directory."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import get_repo_root
result = get_repo_root(Path('/workspace'))
print(json.dumps({'root': str(result)}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["root"] == "/workspace"

    def test_finds_repo_root_from_subdir(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should find repository root from subdirectory."""
        # Create subdirectory
        worktree_workspace.exec("mkdir -p /workspace/src/nested")

        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import get_repo_root
result = get_repo_root(Path('/workspace/src/nested'))
print(json.dumps({'root': str(result)}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["root"] == "/workspace"

    def test_raises_when_not_in_repo(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should raise GitWorktreeError when not in a git repository."""
        # Create directory outside git repo
        worktree_workspace.exec("mkdir -p /tmp/not-a-repo")

        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import get_repo_root
from forge.session.exceptions import GitWorktreeError
try:
    get_repo_root(Path('/tmp/not-a-repo'))
    print(json.dumps({'error': None}))
except GitWorktreeError as e:
    print(json.dumps({'error': 'GitWorktreeError', 'operation': e.operation}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "GitWorktreeError"
        assert result.data["operation"] == "rev-parse"


class TestBranchExists:
    """Tests for branch_exists() - requires real git repo."""

    def test_returns_true_for_existing_branch(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should return True for existing branch."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import branch_exists
exists = branch_exists('main', Path('/workspace'))
print(json.dumps({'exists': exists}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["exists"] is True

    def test_returns_false_for_nonexistent_branch(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should return False for nonexistent branch."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import branch_exists
exists = branch_exists('nonexistent', Path('/workspace'))
print(json.dumps({'exists': exists}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["exists"] is False

    def test_does_not_match_tags(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should not match tags with same name."""
        # Create a tag
        worktree_workspace.git("tag", "release-1.0")

        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import branch_exists
exists = branch_exists('release-1.0', Path('/workspace'))
print(json.dumps({'exists': exists}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        # Should return False because it's a tag, not a branch
        assert result.data["exists"] is False


class TestResolveWorktreePath:
    """Tests for resolve_worktree_path() - needs repo context."""

    def test_creates_sibling_path(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Worktree should be created as sibling to repo."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import resolve_worktree_path
result = resolve_worktree_path(Path('/workspace'), 'feature')
print(json.dumps({'path': str(result)}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        # Sibling to /workspace would be /workspace-feature
        assert result.data["path"] == "/workspace-feature"

    def test_path_is_absolute(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Returned path should be absolute."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import resolve_worktree_path
result = resolve_worktree_path(Path('/workspace'), 'feature')
print(json.dumps({'is_absolute': result.is_absolute()}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["is_absolute"] is True


class TestCreateWorktree:
    """Tests for create_worktree() - requires real git operations."""

    def test_creates_worktree_with_default_branch(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should create worktree with branch derived from session name."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree, branch_exists

result = create_worktree('feature', cwd=Path('/workspace'))
wt_exists = Path(result.worktree_path).exists()
br_exists = branch_exists('feature', Path('/workspace'))

print(json.dumps({
    'branch': result.branch,
    'created_branch': result.created_branch,
    'worktree_exists': wt_exists,
    'branch_exists': br_exists
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["branch"] == "feature"
        assert result.data["created_branch"] is True
        assert result.data["worktree_exists"] is True
        assert result.data["branch_exists"] is True

    def test_creates_worktree_with_custom_branch(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should create worktree with custom branch name."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree, branch_exists

result = create_worktree('feature', branch='feature/auth', cwd=Path('/workspace'))
br_exists = branch_exists('feature/auth', Path('/workspace'))

print(json.dumps({
    'branch': result.branch,
    'branch_exists': br_exists
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["branch"] == "feature/auth"
        assert result.data["branch_exists"] is True

    def test_raises_when_branch_exists(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should raise BranchExistsError when branch already exists."""
        # Create branch first
        worktree_workspace.git("branch", "existing")

        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.exceptions import BranchExistsError

try:
    create_worktree('existing', cwd=Path('/workspace'))
    print(json.dumps({'error': None}))
except BranchExistsError as e:
    print(json.dumps({'error': 'BranchExistsError', 'branch': e.branch}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "BranchExistsError"
        assert result.data["branch"] == "existing"

    def test_raises_when_path_exists(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should raise WorktreePathExistsError when path already exists."""
        # Create target path
        worktree_workspace.exec("mkdir -p /workspace-feature")

        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.exceptions import WorktreePathExistsError

try:
    create_worktree('feature', cwd=Path('/workspace'))
    print(json.dumps({'error': None}))
except WorktreePathExistsError as e:
    print(json.dumps({'error': 'WorktreePathExistsError', 'path': e.path}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "WorktreePathExistsError"
        assert "/workspace-feature" in result.data["path"]

    def test_force_refuses_unowned_manual_worktree(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """--force should not replace a manual worktree that Forge does not own."""
        worktree_workspace.git("worktree", "add", "/workspace-feature", "-b", "manual-feature")

        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.exceptions import WorktreePathExistsError

try:
    create_worktree('feature', cwd=Path('/workspace'), force=True)
    print(json.dumps({'error': None}))
except WorktreePathExistsError as e:
    print(json.dumps({'error': 'WorktreePathExistsError', 'path': e.path}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "WorktreePathExistsError"
        assert "/workspace-feature" in result.data["path"]

    def test_validates_explicit_branch_name(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should validate explicit branch names."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.exceptions import InvalidBranchNameError

try:
    create_worktree('feature', branch='..invalid', cwd=Path('/workspace'))
    print(json.dumps({'error': None}))
except InvalidBranchNameError:
    print(json.dumps({'error': 'InvalidBranchNameError'}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "InvalidBranchNameError"

    def test_worktree_has_correct_structure(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Created worktree should have correct git structure."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree

result = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(result.worktree_path)

# Check .git file (not directory) pointing to main repo
git_file = wt_path / '.git'
has_git_file = git_file.is_file()

# Check README.md from main repo
has_readme = (wt_path / 'README.md').exists()

print(json.dumps({
    'has_git_file': has_git_file,
    'has_readme': has_readme
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["has_git_file"] is True
        assert result.data["has_readme"] is True
