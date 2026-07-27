"""Regression: a losing concurrent create clobbered then deleted the winner's manifest.

Bug: native_session_adoption Slice 2 review, HIGH.
Root cause: `SessionManager.start_session` checked `session_exists` outside the
index lock (manager.py:498) but wrote the manifest *before* reserving the index
name. Two concurrent creates of one name both passed the stale pre-check; the
loser overwrote the winner's manifest, hit `SessionExistsError` inside
`add_session`'s lock, and its rollback deleted that manifest -- leaving the
winner indexed with no state.

Fix: reserve the index name before writing the manifest, matching the ordering
`create_child_session` already documents in its `SessionExistsError` handler.

Affected: src/forge/session/manager.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session import SessionManager, SessionStore
from forge.session.exceptions import SessionExistsError

pytestmark = pytest.mark.regression


def test_losing_a_name_race_leaves_the_winners_manifest_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()

    manager = SessionManager()
    manager.start_session("shared", worktree_path=str(project), direct=True, claude_session_id="w" * 8)
    winner = SessionStore(str(project), "shared").read()

    # start_session guards the name twice before committing: the index
    # (manager.py:498) and the manifest file (manager.py:599). A loser that read
    # both before the winner wrote anything passes both, which is the window this
    # bug lives in. Both stale reads are forced here; everything after them is the
    # real code path.
    real_index_exists = manager.index_store.session_exists
    monkeypatch.setattr(
        manager.index_store,
        "session_exists",
        lambda name, **kw: False if name == "shared" else real_index_exists(name, **kw),
    )

    real_store_exists = SessionStore.exists
    seen: dict[str, int] = {"shared": 0}

    def _first_look_misses(self: SessionStore) -> bool:
        """Miss only the pre-check, not the rollback's own `store.exists()`.

        Patching every call would make the buggy ordering skip its manifest
        delete and pass this test for the wrong reason.
        """
        if self._session_name == "shared":
            seen["shared"] += 1
            if seen["shared"] == 1:
                return False
        return bool(real_store_exists(self))

    monkeypatch.setattr(SessionStore, "exists", _first_look_misses)

    with pytest.raises(SessionExistsError):
        manager.start_session("shared", worktree_path=str(project), direct=True, claude_session_id="l" * 8)

    survivor = SessionStore(str(project), "shared").read()
    assert survivor.confirmed.claude_session_id == winner.confirmed.claude_session_id
    assert survivor.created_at == winner.created_at
    assert manager.index_store.get_session("shared", forge_root=str(project))
