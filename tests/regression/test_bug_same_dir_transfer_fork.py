"""Regression: same-directory transfer forks must not silently native-resume.

Bug (card same_dir_transfer_forks): decoupling transfer mode from worktree isolation
introduced a hole. The child UUID pre-seed at fork time is best-effort, so a --no-launch
same-dir transfer fork can end up with NO claude_session_id. The existing confirmed-state
guard in _get_deferred_same_dir_fork_resume_id then does not fire, and the helper would
return the PARENT uuid -> a silent native `--resume --fork-session`, bypassing the requested
transfer entirely.

Root cause / fix: _get_deferred_same_dir_fork_resume_id now returns None whenever the child's
confirmed derivation records resume_mode == "transfer", BEFORE the confirmed-state guard.
Recorded transfer intent is authoritative over the absence of launch evidence. The manager
(fork_session) writes that "transfer" baseline so the guard has something reliable to read.

Affected files:
- src/forge/cli/session_lifecycle.py (_get_deferred_same_dir_fork_resume_id)
- src/forge/session/manager.py (fork_session transfer-derivation baseline)
- src/forge/cli/session_fork.py (same-dir transfer launch branch)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.cli.session_lifecycle import _get_deferred_same_dir_fork_resume_id
from forge.session import SessionStore, create_session_state
from forge.session.models import Derivation

pytestmark = pytest.mark.regression


class _ParentManager:
    """Minimal SessionManager stub: get_session returns a parent carrying a UUID."""

    def __init__(self, parent_uuid: str) -> None:
        self._parent_uuid = parent_uuid
        self.calls = 0

    def get_session(self, name: str, forge_root: str | None = None) -> object:
        self.calls += 1
        parent = create_session_state(name)
        parent.confirmed.claude_session_id = self._parent_uuid
        return parent


def _samedir_fork(tmp_path: Path, *, resume_mode: str) -> object:
    """A same-dir fork whose UUID pre-seed FAILED: derivation recorded, but no launch evidence
    (no claude_session_id / transcript_path / confirmed_by)."""
    child = create_session_state("child", parent_session="parent", is_fork=True, worktree_path=str(tmp_path))
    assert child.worktree is not None
    child.worktree.is_worktree = False  # same-directory fork (path is the shared parent checkout)
    child.confirmed.derivation = Derivation(parent_session="parent", resume_mode=resume_mode)
    assert child.confirmed.claude_session_id is None
    assert child.confirmed.transcript_path is None
    assert child.confirmed.confirmed_by is None
    return child


def test_get_deferred_resume_id_returns_none_for_transfer_derivation(tmp_path: Path) -> None:
    """The new guard: a same-dir TRANSFER fork with a failed pre-seed must NOT native-resume."""
    child = _samedir_fork(tmp_path, resume_mode="transfer")
    manager = _ParentManager("parent-uuid-xyz")

    result = _get_deferred_same_dir_fork_resume_id(manager=manager, manifest=child)  # type: ignore[arg-type]

    assert result is None
    # The guard short-circuits BEFORE consulting the parent -- no native fallback path is taken.
    assert manager.calls == 0


def test_get_deferred_resume_id_native_fork_still_resumes_parent(tmp_path: Path) -> None:
    """Control: a same-dir NATIVE fork (no launch evidence) still deferred-resumes the parent UUID.

    Proves the guard is transfer-specific and does not break native deferred-resume.
    """
    child = _samedir_fork(tmp_path, resume_mode="native")
    manager = _ParentManager("parent-uuid-xyz")

    result = _get_deferred_same_dir_fork_resume_id(manager=manager, manifest=child)  # type: ignore[arg-type]

    assert result == "parent-uuid-xyz"
    assert manager.calls == 1


def test_samedir_transfer_no_launch_then_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy-path E2E: a --no-launch same-dir transfer fork, when resumed, launches a fresh Claude
    session with assembled parent context -- NOT a native `--resume <parent> --fork-session`.

    This reaches the None path via the EXISTING confirmed-state guard (the pre-seed succeeds here
    and sets claude_session_id), which is why the direct-guard test above is kept separately.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("COLUMNS", "500")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)

    runner = CliRunner()

    with patch("forge.cli.session.invoke_claude", return_value=0):
        start = runner.invoke(main, ["session", "start", "parent", "--no-launch"])
    assert start.exit_code == 0, start.output

    # Give the parent a confirmed UUID so a native resume would be observably distinct.
    store = SessionStore(str(project), "parent")
    store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "claude_session_id", "parent-uuid"))

    fork = runner.invoke(main, ["session", "fork", "parent", "-n", "child", "--resume-mode", "transfer", "--no-launch"])
    assert fork.exit_code == 0, fork.output

    with patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke:
        resume = runner.invoke(main, ["session", "resume", "child"])
    assert resume.exit_code == 0, resume.output

    kwargs = mock_invoke.call_args.kwargs
    # Transfer launch: a fresh child session_id, never the parent's native resume.
    assert kwargs.get("session_id") is not None
    assert kwargs.get("session_id") != "parent-uuid"
    assert kwargs.get("resume_id") is None
    assert kwargs.get("fork_session") is not True
    assert "parent context" in resume.output.lower()


def test_cleared_uuid_transfer_fork_resumes_fresh_not_native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end proof of the headline fix via the REAL resume command, exercising the NEW guard.

    Unlike the happy-path E2E above, this clears the child's pre-seeded claude_session_id to
    simulate the failed/lost UUID pre-seed. With no launch evidence, the OLD confirmed-state guard
    cannot fire -- only the new `derivation.resume_mode == "transfer"` guard prevents resume from
    returning the parent UUID and silently native-resuming. The fork must still launch fresh transfer.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("COLUMNS", "500")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)

    runner = CliRunner()

    with patch("forge.cli.session.invoke_claude", return_value=0):
        start = runner.invoke(main, ["session", "start", "parent", "--no-launch"])
    assert start.exit_code == 0, start.output

    parent_store = SessionStore(str(project), "parent")
    parent_store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "claude_session_id", "parent-uuid"))

    fork = runner.invoke(main, ["session", "fork", "parent", "-n", "child", "--resume-mode", "transfer", "--no-launch"])
    assert fork.exit_code == 0, fork.output

    # Simulate the failed pre-seed: clear the child's UUID while keeping the transfer derivation.
    child_store = SessionStore(str(project), "child")
    child_store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "claude_session_id", None))
    cleared = child_store.read()
    assert cleared.confirmed.claude_session_id is None
    assert cleared.confirmed.derivation is not None
    assert cleared.confirmed.derivation.resume_mode == "transfer"

    with patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke:
        resume = runner.invoke(main, ["session", "resume", "child"])
    assert resume.exit_code == 0, resume.output

    kwargs = mock_invoke.call_args.kwargs
    # Without the guard this would be resume_id=="parent-uuid" + fork_session=True (silent native).
    assert kwargs.get("resume_id") is None
    assert kwargs.get("fork_session") is not True
    assert kwargs.get("session_id") is not None
    assert kwargs.get("session_id") != "parent-uuid"
    assert "Fork parent Claude conversation" not in resume.output
