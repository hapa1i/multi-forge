"""Regression: a failed force-fork restored its stale target over a concurrent winner.

Bug: native_session_adoption Slice 3 review, HIGH.
Root cause: `fork_session(force=True)` deletes the stale target manifest and sets
`replaced_target_state = True` *before* claiming the name. If another creator won
the name in between, `create_exclusive` correctly refused -- but the exception
path ran `_restore_previous_target_state`, whose unconditional `write()` put the
stale manifest back on top of the winner's.

Fix: restore only over a path this fork owned, keyed on `wrote_manifest` (the
ownership token `create_exclusive` produces) and a now-free path.

Affected: src/forge/session/manager.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session import SessionManager, SessionStore, create_session_state

pytestmark = pytest.mark.regression


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_force_fork_losing_the_name_does_not_restore_over_the_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    repo = tmp_path / "repo"
    _init_git_repo(repo)
    (repo / ".forge").mkdir()

    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(repo))
    manager.fork_session("parent", "child")

    target_store = SessionStore(str(repo), "child")
    assert target_store.exists(), "the stale target this fork will try to replace"

    winner = create_session_state("child", worktree_path=str(repo))
    winner.forge_root = str(repo)
    winner.confirmed.claude_session_id = "winner-uuid-xyz"

    real_create = SessionStore.create_exclusive
    landed = False

    def winner_lands_first(self: SessionStore, manifest) -> None:
        """Claim `child` in the window between the stale delete and this create."""
        nonlocal landed
        if self._session_name == "child" and not landed:
            landed = True
            SessionStore(str(repo), "child").write(winner)
        real_create(self, manifest)

    monkeypatch.setattr(SessionStore, "create_exclusive", winner_lands_first)

    with pytest.raises(Exception):
        manager.fork_session("parent", "child", force=True)

    assert landed is True, "the fork must have reached the colliding create"
    assert target_store.exists(), "the winner's manifest must still be there"
    assert (
        target_store.read().confirmed.claude_session_id == "winner-uuid-xyz"
    ), "the stale target must not have been restored over the winner"
