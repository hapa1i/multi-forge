"""Regression: forking a Codex parent created orphaned child state.

Bug: ``forge session fork`` is Claude-specific but did not reject a Codex parent before
``manager.fork_session()``. It created the child manifest (and worktree), then failed at the
"Parent session has no UUID" check (Codex sessions have no ``claude_session_id``), leaving an
orphan and a misleading "may not have been started yet" error.

Fix, two layers: the CLI preflights a Codex parent with an actionable message
(src/forge/cli/session_fork.py), and ``SessionManager.fork_session`` enforces the invariant at
the internal boundary -- rejecting a Codex parent before any child state is created, so no
caller can orphan a child (src/forge/session/manager.py).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session.exceptions import CannotForkCodexParentError
from forge.session.manager import SessionManager
from forge.session.models import LaunchIntent
from forge.session.store import SessionStore

pytestmark = pytest.mark.regression


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.co"], capture_output=True, check=True, cwd=str(path))
    subprocess.run(["git", "config", "user.name", "T"], capture_output=True, check=True, cwd=str(path))


def _enable_forge(path: Path) -> None:
    (path / ".claude").mkdir(exist_ok=True)
    (path / ".forge").mkdir(exist_ok=True)


def test_fork_rejects_codex_parent_before_creating_state(monkeypatch) -> None:
    codex_state = MagicMock()
    codex_state.intent.launch.runtime = "codex"
    manager = MagicMock()
    manager.get_session.return_value = codex_state

    # Patch the seams the guard reaches before fork_session(): the manager, the forge-root
    # resolver, and the cwd guard (so the command runs outside a real repo).
    monkeypatch.setattr("forge.cli.session.SessionManager", lambda: manager)
    monkeypatch.setattr("forge.cli.session_fork._cwd_forge_root", lambda: "/fake/forge/root")
    monkeypatch.setattr("forge.cli.guards.require_repo_root", lambda: None)

    result = CliRunner().invoke(main, ["session", "fork", "planner"])

    assert result.exit_code == 1
    assert "Codex session" in result.output
    # The guard fires BEFORE fork_session(), so no child manifest/worktree is ever created.
    manager.fork_session.assert_not_called()


def test_manager_fork_session_rejects_codex_parent(tmp_path: Path, monkeypatch) -> None:
    """Internal-boundary guard: fork_session itself (not just the CLI) rejects a Codex parent.

    Direct callers bypass the CLI preflight, so the invariant must live in the manager -- and it
    must fire before any child manifest is written, or the orphan the bug described still happens.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _enable_forge(repo)

    manager = SessionManager()
    manager.start_session(name="planner", worktree_path=str(repo))

    # Promote 'planner' to a Codex session (runtime=codex on the launch intent).
    store = SessionStore(str(repo), "planner")
    state = store.read()
    state.intent.launch = LaunchIntent(runtime="codex")
    store.write(state)

    with pytest.raises(CannotForkCodexParentError):
        manager.fork_session("planner", "child")

    # The guard fires before child creation: no orphaned manifest for 'child'.
    assert not SessionStore(str(repo), "child").exists()
