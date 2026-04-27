"""Tests for config copy utilities.

All tests require real git operations and run in Docker containers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.src.session.conftest import WorktreeWorkspace

# Mark all tests as Docker tests
pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


class TestIsFileTracked:
    """Tests for is_file_tracked()."""

    def test_tracked_file_returns_true(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Tracked files should return True."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.config_copy import is_file_tracked

# README.md is tracked in the base git repo
is_tracked = is_file_tracked(Path('README.md'), Path('/workspace'))
print(json.dumps({'is_tracked': is_tracked}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["is_tracked"] is True

    def test_untracked_file_returns_false(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Untracked files should return False."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.config_copy import is_file_tracked

# Create an untracked file
(Path('/workspace') / '.env').write_text('SECRET=value')

is_tracked = is_file_tracked(Path('.env'), Path('/workspace'))
print(json.dumps({'is_tracked': is_tracked}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["is_tracked"] is False

    def test_nonexistent_file_returns_false(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Nonexistent files should return False."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.config_copy import is_file_tracked

is_tracked = is_file_tracked(Path('nonexistent.txt'), Path('/workspace'))
print(json.dumps({'is_tracked': is_tracked}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["is_tracked"] is False

    def test_absolute_path_works(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should handle absolute paths."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.config_copy import is_file_tracked

readme_abs = Path('/workspace/README.md')
is_tracked = is_file_tracked(readme_abs, Path('/workspace'))
print(json.dumps({'is_tracked': is_tracked}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["is_tracked"] is True


class TestCopyRuntimeConfig:
    """Tests for copy_runtime_config()."""

    def test_copies_existing_untracked_files(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should copy untracked files from source to target."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.config_copy import copy_runtime_config

# Create source files in main repo
(Path('/workspace') / '.env').write_text('SECRET=value')
(Path('/workspace') / '.envrc').write_text('source_env')

# Create worktree
wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Copy config
result = copy_runtime_config(Path('/workspace'), wt_path)

env_copied = '.env' in result.copied
envrc_copied = '.envrc' in result.copied
env_content = (wt_path / '.env').read_text() if (wt_path / '.env').exists() else None
envrc_content = (wt_path / '.envrc').read_text() if (wt_path / '.envrc').exists() else None

print(json.dumps({
    'env_copied': env_copied,
    'envrc_copied': envrc_copied,
    'env_content': env_content,
    'envrc_content': envrc_content
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["env_copied"] is True
        assert result.data["envrc_copied"] is True
        assert result.data["env_content"] == "SECRET=value"
        assert result.data["envrc_content"] == "source_env"

    def test_skips_nonexistent_files(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should skip files that don't exist in source."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.config_copy import copy_runtime_config, DEFAULT_CONFIG_ALLOWLIST

# Create worktree without any config files in source
wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

result = copy_runtime_config(Path('/workspace'), wt_path)

# Check that all default files are skipped_not_found
all_skipped = all(f in result.skipped_not_found for f in DEFAULT_CONFIG_ALLOWLIST)

print(json.dumps({'all_skipped': all_skipped}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["all_skipped"] is True

    def test_skips_already_existing_files(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should skip files that already exist in target."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.config_copy import copy_runtime_config

# Create source file
(Path('/workspace') / '.env').write_text('SOURCE=value')

# Create worktree
wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Pre-create file in target
(wt_path / '.env').write_text('TARGET=different')

result = copy_runtime_config(Path('/workspace'), wt_path)

env_in_skipped = '.env' in result.skipped_exists
env_content = (wt_path / '.env').read_text()

print(json.dumps({
    'env_in_skipped': env_in_skipped,
    'env_content': env_content
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["env_in_skipped"] is True
        # Should NOT overwrite
        assert result.data["env_content"] == "TARGET=different"

    def test_skips_tracked_files(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should skip files that are tracked by git."""
        result = worktree_workspace.run_python("""
import json
import subprocess
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.config_copy import copy_runtime_config

# Create and track a file that's in the allowlist
(Path('/workspace') / '.envrc').write_text('tracked_content')
subprocess.run(['git', 'add', '.envrc'], cwd='/workspace', check=True, capture_output=True)
subprocess.run(['git', 'commit', '-m', 'Add .envrc'], cwd='/workspace', check=True, capture_output=True)

# Create worktree
wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# The tracked file should already be in the worktree
file_exists = (wt_path / '.envrc').exists()

# Copy config - should skip the tracked file
result = copy_runtime_config(Path('/workspace'), wt_path)

# Should be in skipped_exists because it already exists
envrc_in_skipped = '.envrc' in result.skipped_exists

print(json.dumps({
    'file_exists': file_exists,
    'envrc_in_skipped': envrc_in_skipped
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["file_exists"] is True
        assert result.data["envrc_in_skipped"] is True

    def test_custom_allowlist(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should respect custom allowlist."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.config_copy import copy_runtime_config

# Create custom config file
(Path('/workspace') / 'custom.conf').write_text('custom=value')

# Create worktree
wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

result = copy_runtime_config(Path('/workspace'), wt_path, allowlist=('custom.conf',))

custom_copied = 'custom.conf' in result.copied
file_exists = (wt_path / 'custom.conf').exists()

print(json.dumps({
    'custom_copied': custom_copied,
    'file_exists': file_exists
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["custom_copied"] is True
        assert result.data["file_exists"] is True

    def test_result_structure(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """ConfigCopyResult should have correct structure."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.config_copy import copy_runtime_config, ConfigCopyResult

wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

result = copy_runtime_config(Path('/workspace'), wt_path)

print(json.dumps({
    'is_config_copy_result': isinstance(result, ConfigCopyResult),
    'has_copied': isinstance(result.copied, list),
    'has_skipped_exists': isinstance(result.skipped_exists, list),
    'has_skipped_tracked': isinstance(result.skipped_tracked, list),
    'has_skipped_not_found': isinstance(result.skipped_not_found, list),
    'has_failed': isinstance(result.failed, list)
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["is_config_copy_result"] is True
        assert result.data["has_copied"] is True
        assert result.data["has_skipped_exists"] is True
        assert result.data["has_skipped_tracked"] is True
        assert result.data["has_skipped_not_found"] is True
        assert result.data["has_failed"] is True


class TestGetCopiedConfigFiles:
    """Tests for get_copied_config_files()."""

    def test_returns_untracked_allowlist_files(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should return untracked files that match allowlist."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.config_copy import get_copied_config_files

# Create worktree
wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Create some untracked files
(wt_path / '.env').write_text('SECRET=value')
(wt_path / '.envrc').write_text('source_env')

result = get_copied_config_files(wt_path)

file_names = [p.name for p in result]

print(json.dumps({
    'count': len(result),
    'has_env': '.env' in file_names,
    'has_envrc': '.envrc' in file_names
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["count"] == 2
        assert result.data["has_env"] is True
        assert result.data["has_envrc"] is True

    def test_excludes_tracked_files(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should exclude tracked files."""
        result = worktree_workspace.run_python("""
import json
import subprocess
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.config_copy import get_copied_config_files

# Create and track a file
(Path('/workspace') / '.envrc').write_text('tracked')
subprocess.run(['git', 'add', '.envrc'], cwd='/workspace', check=True, capture_output=True)
subprocess.run(['git', 'commit', '-m', 'Add .envrc'], cwd='/workspace', check=True, capture_output=True)

# Create worktree
wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

# Add an untracked file
(wt_path / '.env').write_text('untracked')

result = get_copied_config_files(wt_path)
file_names = [p.name for p in result]

print(json.dumps({
    'count': len(result),
    'files': file_names
}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        # Should only include untracked .env, not tracked .envrc
        assert result.data["count"] == 1
        assert result.data["files"] == [".env"]

    def test_returns_empty_for_no_files(self, worktree_workspace: "WorktreeWorkspace") -> None:
        """Should return empty list when no config files exist."""
        result = worktree_workspace.run_python("""
import json
from pathlib import Path
from forge.session.worktree.create import create_worktree
from forge.session.worktree.config_copy import get_copied_config_files

wt = create_worktree('feature', cwd=Path('/workspace'))
wt_path = Path(wt.worktree_path)

result = get_copied_config_files(wt_path)
print(json.dumps({'result': [str(p) for p in result]}))
""")
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["result"] == []
