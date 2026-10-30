"""Tests for SessionManager.

Component Integration Tests (CIT) that test SessionManager with real filesystem
operations and git repo fixtures. All tests run inside Docker containers for
isolation from host filesystem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.src.session.conftest import WorktreeWorkspace

# Mark all tests as Docker integration tests
pytestmark = [pytest.mark.integration, pytest.mark.docker_in]

# HOME path used in container for isolated session state
HOME = "/home/test"


class TestSessionManagerQuery:
    """Tests for SessionManager query operations."""

    def test_list_sessions_empty(self, manager_workspace: "WorktreeWorkspace") -> None:
        """Should return empty list when no sessions."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())
sessions = manager.list_sessions()
print(json.dumps({'sessions': sessions}))
""",
            home=HOME,
        )
        assert result.ok, result.stdout
        assert result.data is not None
        assert result.data["sessions"] == []

    def test_session_exists_false_when_missing(self, manager_workspace: "WorktreeWorkspace") -> None:
        """Should return False for non-existent session."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())
exists = manager.session_exists('nonexistent')
print(json.dumps({'exists': exists}))
""",
            home=HOME,
        )
        assert result.ok, result.stdout
        assert result.data is not None
        assert result.data["exists"] is False


class TestSessionManagerStartSession:
    """Tests for SessionManager.start_session()."""

    def test_start_create_worktree_git_failure_rolls_back(self, manager_workspace: "WorktreeWorkspace") -> None:
        """If git worktree add fails, Forge state should not be written."""
        # Create a branch to cause BranchExistsError
        manager_workspace.git("branch", "boom")

        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())

error = None
try:
    manager.start_session(name='boom', create_worktree=True)
except Exception as e:
    error = type(e).__name__

# No index entry should exist
exists = manager.session_exists('boom')

print(json.dumps({
    'error': error,
    'session_exists': exists,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] is not None  # Some exception was raised
        assert result.data["session_exists"] is False

    def test_start_create_worktree_rollback_on_index_collision(self, manager_workspace: "WorktreeWorkspace") -> None:
        """If index add fails after worktree creation, worktree should be removed."""
        result = manager_workspace.run_python(
            """
import json
from pathlib import Path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.worktree import resolve_worktree_path
from forge.session.worktree.create import get_repo_root

index_store = IndexStore()
manager = SessionManager(index_store=index_store)

# Pre-create a LIVE session so the commit transaction rejects the name. A bare
# index row is crash residue since session_create_crash_atomicity: the
# transaction prunes it and the create succeeds, so it no longer models a
# collision.
manager.start_session(name='collision', worktree_path='/workspace')

repo_root = get_repo_root(Path('/workspace'))
expected_worktree = resolve_worktree_path(repo_root, 'collision')

error = None
try:
    manager.start_session(name='collision', create_worktree=True)
except Exception as e:
    error = type(e).__name__

# Worktree should have been cleaned up
worktree_exists = expected_worktree.exists()

print(json.dumps({
    'error': error,
    'worktree_exists': worktree_exists,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "SessionExistsError"
        assert result.data["worktree_exists"] is False

    def test_start_create_worktree_rolls_back_incompatible_target(self, manager_workspace: "WorktreeWorkspace") -> None:
        """A target checkout pin refusal removes the checkout and created branch."""
        result = manager_workspace.run_python(
            """
import json
import os
import subprocess
from pathlib import Path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.worktree import resolve_worktree_path

repo_root = Path('/workspace')
os.chdir(repo_root)
pin = repo_root / '.forge' / 'project.toml'
pin.parent.mkdir(parents=True, exist_ok=True)
pin.write_text('schema_version = 1\\nrequired_forge = \">=999\"\\n')
subprocess.run(['git', 'add', '-f', '.forge/project.toml'], cwd=repo_root, check=True)
subprocess.run(['git', 'commit', '-m', 'track incompatible pin'], cwd=repo_root, check=True, capture_output=True)

# The source working copy is compatible, while the fresh target sees the
# incompatible pin from HEAD.
pin.write_text('schema_version = 1\\nrequired_forge = \">=0\"\\n')

manager = SessionManager(index_store=IndexStore())
expected_worktree = resolve_worktree_path(repo_root, 'blocked')
error = None
state = None
try:
    manager.start_session(name='blocked', create_worktree=True)
except Exception as e:
    error = type(e).__name__
    state = getattr(e, 'state', None)

branch = subprocess.run(
    ['git', 'branch', '--list', 'blocked'],
    cwd=repo_root,
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()

print(json.dumps({
    'error': error,
    'state': state,
    'worktree_exists': expected_worktree.exists(),
    'branch_exists': bool(branch),
    'session_exists': manager.session_exists('blocked'),
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data == {
            "error": "ProjectCompatibilityError",
            "state": "incompatible",
            "worktree_exists": False,
            "branch_exists": False,
            "session_exists": False,
        }

    def test_start_creates_manifest(self, manager_workspace: "WorktreeWorkspace") -> None:
        """start_session should create manifest file."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.store import SessionStore

manager = SessionManager(index_store=IndexStore())
manifest = manager.start_session(
    name='test-session',
    worktree_path='/workspace',
)

store = SessionStore('/workspace', 'test-session')
print(json.dumps({
    'name': manifest.name,
    'store_exists': store.exists()
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["name"] == "test-session"
        assert result.data["store_exists"] is True

    def test_start_adds_to_index(self, manager_workspace: "WorktreeWorkspace") -> None:
        """start_session should add session to index."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())
manager.start_session(
    name='indexed-session',
    worktree_path='/workspace',
)

exists = manager.session_exists('indexed-session')
print(json.dumps({'exists': exists}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["exists"] is True

    def test_start_leaves_uuid_none(self, manager_workspace: "WorktreeWorkspace") -> None:
        """start_session should leave claude_session_id as None (launch-owned)."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())
manifest = manager.start_session(
    name='uuid-session',
    worktree_path='/workspace',
)

print(json.dumps({
    'session_id': manifest.confirmed.claude_session_id,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["session_id"] is None

    def test_start_raises_when_exists(self, manager_workspace: "WorktreeWorkspace") -> None:
        """start_session should raise SessionExistsError for duplicate names."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session import SessionExistsError

manager = SessionManager(index_store=IndexStore())
manager.start_session(
    name='duplicate-session',
    worktree_path='/workspace',
)

error = None
try:
    manager.start_session(
        name='duplicate-session',
        worktree_path='/workspace',
    )
except SessionExistsError:
    error = 'SessionExistsError'

print(json.dumps({'error': error}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "SessionExistsError"


class TestSessionManagerResumeSession:
    """Tests for SessionManager.resume_session()."""

    def test_resume_creates_child_session(self, manager_workspace: "WorktreeWorkspace") -> None:
        """resume_session should create a new child session derived from parent."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())

# Create parent session
manager.start_session(
    name='parent-session',
    worktree_path='/workspace',
)

# Resume creates a child session
child_manifest, handoff_result = manager.resume_session('parent-session')

print(json.dumps({
    'child_name': child_manifest.name,
    'parent_session': child_manifest.parent_session,
    'has_handoff': handoff_result is not None,
    'context_file_rel': handoff_result.context_file_rel if handoff_result else None,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["child_name"] == "parent-session-resumed"
        assert result.data["parent_session"] == "parent-session"
        assert result.data["has_handoff"] is True
        assert (
            result.data["context_file_rel"] == ".forge/prev_sessions/parent-session/children/parent-session-resumed.md"
        )

    def test_resume_with_explicit_child_name(self, manager_workspace: "WorktreeWorkspace") -> None:
        """resume_session should accept explicit child name."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())

# Create parent session
manager.start_session(
    name='parent-v1',
    worktree_path='/workspace',
)

# Resume with explicit child name
child_manifest, _ = manager.resume_session('parent-v1', child_name='parent-v2')

print(json.dumps({
    'child_name': child_manifest.name,
    'parent_session': child_manifest.parent_session,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["child_name"] == "parent-v2"
        assert result.data["parent_session"] == "parent-v1"

    def test_resume_raises_when_not_found(self, manager_workspace: "WorktreeWorkspace") -> None:
        """resume_session should raise SessionNotFoundError."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session import SessionNotFoundError

manager = SessionManager(index_store=IndexStore())

error = None
try:
    manager.resume_session('nonexistent')
except SessionNotFoundError:
    error = 'SessionNotFoundError'

print(json.dumps({'error': error}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "SessionNotFoundError"


class TestSessionManagerSwitchSession:
    """Tests for SessionManager.switch_session()."""

    def test_switch_updates_timestamps(self, manager_workspace: "WorktreeWorkspace") -> None:
        """switch_session should update last_accessed_at."""
        result = manager_workspace.run_python(
            """
import json
import time
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())
manager.start_session(
    name='switch-time-test',
    worktree_path='/workspace',
)

time.sleep(0.01)

manifest = manager.switch_session('switch-time-test')
has_timestamp = manifest.last_accessed_at is not None
print(json.dumps({'has_timestamp': has_timestamp}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["has_timestamp"] is True


class TestSessionManagerForkSession:
    """Tests for SessionManager.fork_session()."""

    def test_fork_default_no_worktree(self, manager_workspace: "WorktreeWorkspace") -> None:
        """Default fork stays in parent's directory (no git worktree)."""
        result = manager_workspace.run_python(
            """
import json
from pathlib import Path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.worktree import branch_exists

manager = SessionManager(
    index_store=IndexStore(),
)

manager.start_session(
    name='parent-session',
    worktree_path='/workspace',
)

parent, fork = manager.fork_session('parent-session', 'fork-session')
derivation = fork.confirmed.derivation

manifest_path = Path('/workspace/.forge/sessions/fork-session/forge.session.json')

print(json.dumps({
    'parent_name': parent.name,
    'fork_name': fork.name,
    'is_fork': fork.is_fork,
    'parent_session': fork.parent_session,
    'has_worktree': fork.worktree is not None,
    'is_worktree': fork.worktree.is_worktree if fork.worktree else False,
    'fork_path': fork.worktree.path if fork.worktree else None,
    'manifest_exists': manifest_path.exists(),
    'branch_exists': branch_exists('fork-session', Path('/workspace')),
    'derivation': None if derivation is None else {
        'parent_session': derivation.parent_session,
        'resume_mode': derivation.resume_mode,
        'strategy': derivation.strategy,
        'depth': derivation.depth,
        'lineage': derivation.lineage,
        'parent_forge_root': derivation.parent_forge_root,
        'parent_project_root': derivation.parent_project_root,
    },
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["parent_name"] == "parent-session"
        assert result.data["fork_name"] == "fork-session"
        assert result.data["is_fork"] is True
        assert result.data["parent_session"] == "parent-session"
        assert result.data["has_worktree"] is True
        assert result.data["is_worktree"] is False
        assert result.data["fork_path"] == "/workspace"
        assert result.data["manifest_exists"] is True
        assert result.data["branch_exists"] is False
        assert result.data["derivation"] == {
            "parent_session": "parent-session",
            "resume_mode": "native",
            "strategy": None,
            "depth": 1,
            "lineage": ["parent-session"],
            "parent_forge_root": "/workspace",
            "parent_project_root": "/workspace",
        }

    def test_fork_with_worktree_creates_worktree(self, manager_workspace: "WorktreeWorkspace") -> None:
        """fork_session(create_worktree=True) creates a git worktree."""
        result = manager_workspace.run_python(
            """
import json
from pathlib import Path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.worktree import branch_exists

manager = SessionManager(
    index_store=IndexStore(),
)

manager.start_session(
    name='parent-session',
    worktree_path='/workspace',
)

parent, fork = manager.fork_session('parent-session', 'fork-session', create_worktree=True)
derivation = fork.confirmed.derivation

print(json.dumps({
    'parent_name': parent.name,
    'fork_name': fork.name,
    'is_fork': fork.is_fork,
    'parent_session': fork.parent_session,
    'has_worktree': fork.worktree is not None,
    'is_worktree': fork.worktree.is_worktree if fork.worktree else False,
    'worktree_exists': Path(fork.worktree.path).exists() if fork.worktree else False,
    'branch_exists': branch_exists('fork-session', Path('/workspace')),
    'derivation': None if derivation is None else {
        'parent_session': derivation.parent_session,
        'resume_mode': derivation.resume_mode,
        'strategy': derivation.strategy,
        'depth': derivation.depth,
        'lineage': derivation.lineage,
        'parent_forge_root': derivation.parent_forge_root,
        'parent_project_root': derivation.parent_project_root,
    },
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["parent_name"] == "parent-session"
        assert result.data["fork_name"] == "fork-session"
        assert result.data["is_fork"] is True
        assert result.data["parent_session"] == "parent-session"
        assert result.data["has_worktree"] is True
        assert result.data["is_worktree"] is True
        assert result.data["worktree_exists"] is True
        assert result.data["branch_exists"] is True
        assert result.data["derivation"]["parent_session"] == "parent-session"
        assert result.data["derivation"]["resume_mode"] == "transfer"
        assert result.data["derivation"]["strategy"] is None
        assert result.data["derivation"]["depth"] == 1
        assert result.data["derivation"]["lineage"] == ["parent-session"]
        assert result.data["derivation"]["parent_forge_root"] == "/workspace"
        assert result.data["derivation"]["parent_project_root"] == "/workspace"

    def test_force_worktree_fork_keeps_same_name_session_in_parent_root(
        self, manager_workspace: "WorktreeWorkspace"
    ) -> None:
        """Force worktree fork should not delete a same-name session in the parent forge_root."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())
manager.start_session(name='parent-session', worktree_path='/workspace')
manager.start_session(name='fork-session', worktree_path='/workspace')

_, fork = manager.fork_session('parent-session', 'fork-session', create_worktree=True, force=True)

parent_entry = manager.index_store.get_session('fork-session', forge_root='/workspace')
child_entry = manager.index_store.get_session('fork-session', forge_root=fork.forge_root)

print(json.dumps({
    'parent_root': parent_entry.forge_root,
    'child_root': child_entry.forge_root,
    'roots_differ': parent_entry.forge_root != child_entry.forge_root,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["parent_root"] == "/workspace"
        assert result.data["roots_differ"] is True

    def test_force_worktree_fork_replaces_stale_child_without_deleting_new_worktree(
        self, manager_workspace: "WorktreeWorkspace"
    ) -> None:
        """Force retry should replace stale child state without removing the new worktree."""
        result = manager_workspace.run_python(
            """
import json
from pathlib import Path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())
manager.start_session(name='parent-session', worktree_path='/workspace')
_, first = manager.fork_session('parent-session', 'fork-session', create_worktree=True)
_, second = manager.fork_session('parent-session', 'fork-session', create_worktree=True, force=True)

entry = manager.index_store.get_session('fork-session', forge_root=second.forge_root)

print(json.dumps({
    'first_path': first.worktree.path,
    'second_path': second.worktree.path,
    'worktree_exists': Path(second.worktree.path).exists(),
    'entry_path': entry.worktree_path,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["first_path"] == result.data["second_path"]
        assert result.data["worktree_exists"] is True
        assert result.data["entry_path"] == result.data["second_path"]

    def test_force_worktree_fork_rolls_back_created_worktree_on_index_failure(
        self, manager_workspace: "WorktreeWorkspace"
    ) -> None:
        """If fork commit fails after worktree creation, the new worktree/branch should be removed."""
        result = manager_workspace.run_python(
            """
import json
from pathlib import Path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.worktree import branch_exists, resolve_worktree_path
from forge.session.worktree.create import get_repo_root

index_store = IndexStore()
manager = SessionManager(index_store=index_store)
manager.start_session(name='parent-session', worktree_path='/workspace')

repo_root = get_repo_root(Path('/workspace'))
expected_worktree = resolve_worktree_path(repo_root, 'fork-session')

# Inject at the commit transaction: row and manifest publication is atomic under
# create_session_txn's index lock.
original_txn = index_store.create_session_txn

def fail_commit(state, *args, **kwargs):
    if state.name == 'fork-session':
        raise RuntimeError('boom')
    return original_txn(state, *args, **kwargs)

index_store.create_session_txn = fail_commit

error = None
try:
    manager.fork_session('parent-session', 'fork-session', create_worktree=True)
except Exception as e:
    error = type(e).__name__

session_exists = manager.session_exists('fork-session', forge_root=str(expected_worktree))

print(json.dumps({
    'error': error,
    'worktree_exists': expected_worktree.exists(),
    'branch_exists': branch_exists('fork-session', Path('/workspace')),
    'session_exists': session_exists,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "RuntimeError"
        assert result.data["worktree_exists"] is False
        assert result.data["branch_exists"] is False
        assert result.data["session_exists"] is False

    def test_force_same_dir_fork_replaces_matching_stale_child(self, manager_workspace: "WorktreeWorkspace") -> None:
        """Force same-dir fork should retry only the stale child it previously created."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())
manager.start_session(name='parent-session', worktree_path='/workspace')
_, first = manager.fork_session('parent-session', 'fork-session')
_, second = manager.fork_session('parent-session', 'fork-session', force=True)

entry = manager.index_store.get_session('fork-session', forge_root='/workspace')
current = manager.get_session('fork-session', forge_root='/workspace')

print(json.dumps({
    'first_parent': first.parent_session,
    'second_parent': second.parent_session,
    'is_fork': current.is_fork,
    'entry_parent': entry.parent_session,
    'worktree_path': second.worktree.path if second.worktree else None,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["first_parent"] == "parent-session"
        assert result.data["second_parent"] == "parent-session"
        assert result.data["is_fork"] is True
        assert result.data["entry_parent"] == "parent-session"
        assert result.data["worktree_path"] == "/workspace"

    def test_force_same_dir_fork_rejects_unrelated_existing_session(
        self, manager_workspace: "WorktreeWorkspace"
    ) -> None:
        """Force same-dir fork must not delete a non-fork session that shares the target name."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session import SessionExistsError

manager = SessionManager(index_store=IndexStore())
manager.start_session(name='parent-session', worktree_path='/workspace')
manager.start_session(name='fork-session', worktree_path='/workspace')

error = None
try:
    manager.fork_session('parent-session', 'fork-session', force=True)
except SessionExistsError:
    error = 'SessionExistsError'

existing = manager.get_session('fork-session', forge_root='/workspace')
entry = manager.index_store.get_session('fork-session', forge_root='/workspace')

print(json.dumps({
    'error': error,
    'is_fork': existing.is_fork,
    'parent_session': existing.parent_session,
    'entry_parent': entry.parent_session,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "SessionExistsError"
        assert result.data["is_fork"] is False
        assert result.data["parent_session"] is None
        assert result.data["entry_parent"] is None

    def test_fork_auto_generates_name(self, manager_workspace: "WorktreeWorkspace") -> None:
        """fork_session should auto-generate fork name if not provided."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(
    index_store=IndexStore(),
)

manager.start_session(
    name='parent-session',
    worktree_path='/workspace',
)

_, fork = manager.fork_session('parent-session')

print(json.dumps({
    'fork_name': fork.name,
    'has_hyphen': '-' in fork.name if fork.name else False
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["fork_name"] is not None
        assert result.data["has_hyphen"] is True  # adjective-noun format

    def test_fork_raises_for_missing_parent(self, manager_workspace: "WorktreeWorkspace") -> None:
        """fork_session should raise SessionNotFoundError for missing parent."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session import SessionNotFoundError

manager = SessionManager(
    index_store=IndexStore(),
)

error = None
try:
    manager.fork_session('nonexistent-parent', 'child')
except SessionNotFoundError:
    error = 'SessionNotFoundError'

print(json.dumps({'error': error}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "SessionNotFoundError"

    def test_fork_raises_for_incognito_parent(self, manager_workspace: "WorktreeWorkspace") -> None:
        """fork_session should raise CannotForkIncognitoError for incognito parent."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.exceptions import CannotForkIncognitoError

manager = SessionManager(
    index_store=IndexStore(),
)

# Create incognito parent session
manager.start_session(
    name='incognito-parent',
    worktree_path='/workspace',
    is_incognito=True,
)

error = None
try:
    manager.fork_session('incognito-parent', 'child')
except CannotForkIncognitoError:
    error = 'CannotForkIncognitoError'

print(json.dumps({'error': error}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "CannotForkIncognitoError"


class TestSessionManagerRelaunchSession:
    """Tests for SessionManager.relaunch_session()."""

    def test_relaunch_inherits_overrides(self, manager_workspace: "WorktreeWorkspace") -> None:
        """relaunch_session should preserve parent overrides for the child."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.store import SessionStore

manager = SessionManager(index_store=IndexStore())
manager.start_session(
    name='parent-session',
    proxy_template='litellm-openai',
    proxy_base_url='http://localhost:8085',
    worktree_path='/workspace',
)

store = SessionStore('/workspace', 'parent-session')

def _set_overrides(manifest):
    manifest.overrides = {
        'verification': {'bypass': True},
        'proxy': {'base_url': 'http://localhost:9090'},
    }

store.update(timeout_s=5.0, mutate=_set_overrides)

_, child = manager.relaunch_session('parent-session', child_name='child-session')

print(json.dumps({'overrides': child.overrides}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["overrides"] == {
            "verification": {"bypass": True},
            "proxy": {"base_url": "http://localhost:9090"},
        }


class TestSessionManagerDerivedOverrideValidation:
    """Persisted parent validation and inherited layers in the isolated runtime."""

    @pytest.mark.parametrize("operation", ["fork", "fresh", "relaunch"])
    @pytest.mark.parametrize("invalid_path", ["verification.bypass", "launch.runtime", "policy.supervisor"])
    def test_invalid_parent_never_publishes_child(
        self, manager_workspace: "WorktreeWorkspace", operation: str, invalid_path: str
    ) -> None:
        result = manager_workspace.run_python(
            f"operation = {operation!r}\ninvalid_path = {invalid_path!r}\n" + """
import json
from pathlib import Path
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.exceptions import ForgeSessionError
from forge.session.models import LaunchIntent
from forge.session.prev_sessions import parent_dir
from tests.fixtures.session_state import publish_session

root = Path('/workspace')
index = IndexStore()
parent = create_session_state('parent', worktree_path=str(root))
parent.intent.launch = LaunchIntent()
publish_session(index, parent, root)
store = SessionStore(str(root), 'parent')
# Deliberately corrupt one override only after coherent publication.
raw = json.loads(store.manifest_path.read_text())
raw['overrides'] = {
    'verification.bypass': {'verification': {'bypass': 'bad'}},
    'launch.runtime': {'launch': {'runtime': 'codex'}},
    'policy.supervisor': {'policy': {'supervisor': 'bad'}},
}[invalid_path]
store.manifest_path.write_text(json.dumps(raw))
before = store.manifest_path.read_bytes()
index_before = index.index_path.read_bytes()
manager = SessionManager(index)
error = None
try:
    if operation == 'fork':
        manager.fork_session('parent', 'child', forge_root=str(root))
    elif operation == 'fresh':
        manager.resume_session('parent', child_name='child', forge_root=str(root))
    else:
        manager.relaunch_session('parent', child_name='child', forge_root=str(root))
except ForgeSessionError as exc:
    error = str(exc)
print(json.dumps({
    'error': error,
    'parent_unchanged': store.manifest_path.read_bytes() == before,
    'index_unchanged': index.index_path.read_bytes() == index_before,
    'child_exists': SessionStore(str(root), 'child').exists(),
    'transfer_exists': parent_dir(root, 'parent').exists(),
}))
""",
            home=HOME,
        )
        assert result.ok, result.stderr
        assert result.data is not None
        assert invalid_path in result.data["error"]
        assert result.data["parent_unchanged"] and result.data["index_unchanged"]
        assert not result.data["child_exists"] and not result.data["transfer_exists"]

    @pytest.mark.parametrize("operation", ["fork", "fresh", "relaunch"])
    def test_valid_layers_persist_and_reset_independently(
        self, manager_workspace: "WorktreeWorkspace", operation: str
    ) -> None:
        result = manager_workspace.run_python(
            f"operation = {operation!r}\n" + """
import json
from pathlib import Path
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import reset_session_overrides
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.effective import compute_effective_intent
from forge.session.models import MemoryIntent, MemoryWriterConfig, PolicyIntent, SupervisorConfig
from tests.fixtures.session_state import publish_session

root = Path('/workspace')
index = IndexStore()
parent = create_session_state('parent', worktree_path=str(root))
parent.intent.policy = PolicyIntent(enabled=True, supervisor=SupervisorConfig(resume_id='planner', suspended=True))
parent.intent.memory = MemoryIntent(auto_update=MemoryWriterConfig(enabled=False))
parent.overrides = {'policy': {'enabled': False}, 'verification': {'bypass': True},
                    'memory': {'auto_update': {'enabled': True, 'mode': 'review-only', 'min_turns': 9}}}
publish_session(index, parent, root)
store = SessionStore(str(root), 'parent')
before = store.manifest_path.read_bytes()
manager = SessionManager(index)
if operation == 'fork':
    manager.fork_session('parent', 'child', forge_root=str(root))
elif operation == 'fresh':
    manager.resume_session('parent', child_name='child', forge_root=str(root))
else:
    manager.relaunch_session('parent', child_name='child', forge_root=str(root))
child_store = SessionStore(str(root), 'child')
child = child_store.read()
effective = compute_effective_intent(child)
result = {
    'policy_enabled': effective.policy.enabled,
    'suspended': effective.policy.supervisor.suspended,
    'verification': effective.verification is not None,
    'overrides_retained': child.overrides == parent.overrides,
    'writer': [effective.memory.auto_update.enabled, effective.memory.auto_update.mode,
               effective.memory.auto_update.min_turns],
}
reset_session_overrides(ctx=ExecutionContext(root, root, root, root), session_name='child')
reset = compute_effective_intent(child_store.read())
result.update({'reset_policy': reset.policy.enabled, 'reset_suspended': reset.policy.supervisor.suspended,
               'reset_verification': reset.verification is None,
               'reset_writer': reset.memory.auto_update.enabled,
               'parent_unchanged': store.manifest_path.read_bytes() == before})
print(json.dumps(result))
""",
            home=HOME,
        )
        assert result.ok, result.stderr
        assert result.data is not None
        assert result.data["policy_enabled"] == (operation != "relaunch")
        assert result.data["verification"] == (operation == "relaunch")
        assert result.data["overrides_retained"] == (operation == "relaunch")
        assert result.data["writer"] == [True, "review-only", 9]
        assert result.data["suspended"] and result.data["reset_suspended"]
        assert result.data["reset_policy"] and result.data["reset_verification"] and result.data["parent_unchanged"]
        assert result.data["reset_writer"] == (operation != "relaunch")


class TestNativeSourceOverrideAuthoring:
    """Installed CLI authoring refuses native identity while retaining legal clears."""

    @pytest.mark.parametrize("has_supervisor", [False, True], ids=["no-supervisor", "plan-supervisor"])
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("policy.supervisor.native_source", None),
            ("policy.supervisor", {"native_source": None}),
            ("policy", {"supervisor": {"native_source": None}}),
            ("policy.*", None),
        ],
        ids=["direct-null", "supervisor-object", "policy-object", "policy-wildcard"],
    )
    def test_native_source_writes_preserve_published_parent(
        self,
        manager_workspace: "WorktreeWorkspace",
        has_supervisor: bool,
        key: str,
        value: dict[str, object] | None,
    ) -> None:
        result = manager_workspace.run_python(
            f"has_supervisor = {has_supervisor!r}\nkey = {key!r}\nvalue = {value!r}\n" + """
import json
import os
from pathlib import Path
from click.testing import CliRunner
from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import PolicyIntent, SupervisorConfig
from tests.fixtures.session_state import publish_session

root = Path('/workspace')
os.chdir(root)
plan = root / 'approved.md'
plan.write_text('Only change files named by the approved task.')
index = IndexStore()
parent = create_session_state('parent', worktree_path=str(root))
parent.intent.policy = PolicyIntent(
    enabled=True,
    supervisor=SupervisorConfig(plan_override_path=str(plan), supervisor_model='opus') if has_supervisor else None,
)
publish_session(index, parent, root)
store = SessionStore(str(root), parent.name)
before = store.manifest_path.read_bytes()
index_before = index.index_path.read_bytes()
invoked = CliRunner().invoke(main, ['session', 'set', '--session', parent.name, key, json.dumps(value)])
print(json.dumps({
    'exit_code': invoked.exit_code,
    'stdout': invoked.stdout,
    'stderr': invoked.stderr,
    'parent_unchanged': store.manifest_path.read_bytes() == before,
    'index_unchanged': index.index_path.read_bytes() == index_before,
}))
""",
            home=HOME,
        )
        assert result.ok, result.stderr
        assert result.data is not None
        assert result.data["exit_code"] == 1, result.data
        assert result.data["stdout"] == ""
        error = " ".join(result.data["stderr"].split())
        assert "native_source is supervisor identity" in error
        assert "forge policy supervisor set" in error
        assert result.data["parent_unchanged"] and result.data["index_unchanged"]

    @pytest.mark.parametrize("has_supervisor", [False, True], ids=["no-supervisor", "plan-supervisor"])
    def test_nullable_parent_clears_remain_derivable(
        self, manager_workspace: "WorktreeWorkspace", has_supervisor: bool
    ) -> None:
        result = manager_workspace.run_python(
            f"has_supervisor = {has_supervisor!r}\n" + """
import json
import os
from pathlib import Path
from click.testing import CliRunner
from forge.cli.main import main
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.effective import compute_effective_intent
from forge.session.models import PolicyIntent, SupervisorConfig
from tests.fixtures.session_state import publish_session

root = Path('/workspace')
os.chdir(root)
plan = root / 'approved.md'
plan.write_text('Only change files named by the approved task.')
index = IndexStore()
manager = SessionManager(index)
results = []
for position, key in enumerate(('policy', 'policy.supervisor')):
    name = f'parent-{position}'
    parent = create_session_state(name, worktree_path=str(root))
    parent.intent.policy = PolicyIntent(
        enabled=True,
        supervisor=SupervisorConfig(plan_override_path=str(plan), supervisor_model='opus') if has_supervisor else None,
    )
    publish_session(index, parent, root)
    invoked = CliRunner().invoke(main, ['session', 'set', '--session', name, key, 'null'])
    assert invoked.exit_code == 0, invoked.output
    assert invoked.stderr == '', invoked.stderr
    store = SessionStore(str(root), name)
    before_derivation = store.manifest_path.read_bytes()
    _, child = manager.relaunch_session(name, child_name=f'child-{position}', forge_root=str(root))
    persisted = SessionStore(str(root), child.name).read()
    expected_overrides = {'policy': None if key == 'policy' else {'supervisor': None}}
    effective = compute_effective_intent(persisted)
    results.append({
        'overrides_preserved': persisted.overrides == expected_overrides,
        'cleared': effective.policy is None if key == 'policy' else effective.policy.supervisor is None,
        'parent_unchanged': store.manifest_path.read_bytes() == before_derivation,
    })
print(json.dumps({'results': results}))
""",
            home=HOME,
        )
        assert result.ok, result.stderr
        assert result.data is not None
        assert len(result.data["results"]) == 2
        assert all(all(checks.values()) for checks in result.data["results"])


class TestSessionManagerDeleteSession:
    """Tests for SessionManager.delete_session()."""

    def test_delete_removes_from_index(self, manager_workspace: "WorktreeWorkspace") -> None:
        """delete_session should remove session from index."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())
manager.start_session(
    name='delete-test',
    worktree_path='/workspace',
)

manager.delete_session('delete-test', force=True)
exists = manager.session_exists('delete-test')
print(json.dumps({'exists': exists}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["exists"] is False

    def test_delete_removes_manifest(self, manager_workspace: "WorktreeWorkspace") -> None:
        """delete_session should remove manifest file."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.store import SessionStore

manager = SessionManager(index_store=IndexStore())
manager.start_session(
    name='manifest-delete-test',
    worktree_path='/workspace',
)

store = SessionStore('/workspace', 'manifest-delete-test')
exists_before = store.exists()

manager.delete_session('manifest-delete-test', force=True)

exists_after = store.exists()
print(json.dumps({
    'exists_before': exists_before,
    'exists_after': exists_after
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["exists_before"] is True
        assert result.data["exists_after"] is False

    def test_delete_raises_when_not_found(self, manager_workspace: "WorktreeWorkspace") -> None:
        """delete_session should raise SessionNotFoundError."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session import SessionNotFoundError

manager = SessionManager(index_store=IndexStore())

error = None
try:
    manager.delete_session('nonexistent')
except SessionNotFoundError:
    error = 'SessionNotFoundError'

print(json.dumps({'error': error}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] == "SessionNotFoundError"

    def test_delete_preserves_native_transcript(self, manager_workspace: "WorktreeWorkspace") -> None:
        """Ordinary deletion preserves native bytes without an opt-out flag."""
        result = manager_workspace.run_python(
            """
import json
from forge.session.claude.paths import get_transcript_path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())
conversation = 'aaaaaaaa-1111-4111-8111-111111111111'
manager.start_session(name='preserve-native', worktree_path='/workspace', claude_session_id=conversation)
transcript = get_transcript_path('/workspace', conversation)
transcript.parent.mkdir(parents=True, exist_ok=True)
transcript.write_bytes(b'native conversation remains byte-identical')
before = transcript.read_bytes()

manager.delete_session('preserve-native', force=True)
print(json.dumps({
    'exists': manager.session_exists('preserve-native'),
    'native_unchanged': transcript.read_bytes() == before,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["exists"] is False
        assert result.data["native_unchanged"] is True

    def test_delete_preserves_rollovers_and_removes_forge_copies(self, manager_workspace: "WorktreeWorkspace") -> None:
        """Rollover references retain native transcripts while owned copies are removed."""
        result = manager_workspace.run_python(
            """
import json
from pathlib import Path
from forge.session.claude.paths import get_transcript_path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.store import SessionStore

manager = SessionManager(index_store=IndexStore())
current = 'aaaaaaaa-1111-4111-8111-111111111111'
rollover = 'bbbbbbbb-2222-4222-8222-222222222222'
manager.start_session(name='rollover-cleanup', worktree_path='/workspace', claude_session_id=current)
store = SessionStore('/workspace', 'rollover-cleanup')
artifacts = Path('/workspace/.forge/artifacts/rollover-cleanup')
copy_root = artifacts / 'transcripts'
copy_root.mkdir(parents=True)
paths = []
for native_id in (current, rollover):
    path = get_transcript_path('/workspace', native_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(native_id)
    paths.append(path)
    (copy_root / f'{native_id}.jsonl').write_bytes(path.read_bytes())

def record_copies(manifest):
    manifest.confirmed.artifacts = {'transcripts': [
        {'session_id': native_id,
         'copied_path': f'.forge/artifacts/rollover-cleanup/transcripts/{native_id}.jsonl'}
        for native_id in (rollover, current, rollover)
    ]}

store.update(timeout_s=5.0, mutate=record_copies)
manager.delete_session('rollover-cleanup', force=True)
print(json.dumps({
    'native_contents': [path.read_text() for path in paths],
    'artifacts_exist': artifacts.exists(),
    'manifest_exists': store.exists(),
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["native_contents"] == [
            "aaaaaaaa-1111-4111-8111-111111111111",
            "bbbbbbbb-2222-4222-8222-222222222222",
        ]
        assert result.data["artifacts_exist"] is False
        assert result.data["manifest_exists"] is False

    def test_delete_refuses_dirty_worktree_before_removing_content(
        self, manager_workspace: "WorktreeWorkspace"
    ) -> None:
        """Dirty-worktree refusal preserves the checkout, manifest and owned artifacts."""
        result = manager_workspace.run_python(
            """
import json
import os
from pathlib import Path
from forge.session.exceptions import ForgeSessionError
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.store import SessionStore

manager = SessionManager(index_store=IndexStore())
os.chdir('/workspace')
state = manager.start_session(name='dirty-delete-test', create_worktree=True)
store = SessionStore(state.forge_root, state.name)
checkout = Path(state.worktree.path)
(checkout / 'uncommitted.txt').write_text('keep dirty work')
artifact = Path(state.forge_root) / '.forge/artifacts/dirty-delete-test/keep.md'
artifact.parent.mkdir(parents=True, exist_ok=True)
artifact.write_text('owned content must survive refusal')
error = None
try:
    manager.delete_session(state.name, force=False, forge_root=state.forge_root)
except ForgeSessionError as exc:
    error = str(exc)

print(json.dumps({
    'error': error,
    'checkout_exists': checkout.exists(),
    'manifest_exists': store.exists(),
    'artifact': artifact.read_text(),
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error"] is not None
        assert "dirty" in result.data["error"].lower()
        assert result.data["checkout_exists"] is True
        assert result.data["manifest_exists"] is True
        assert result.data["artifact"] == "owned content must survive refusal"
