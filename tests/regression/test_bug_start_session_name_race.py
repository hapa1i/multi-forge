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

Updated by session_create_crash_atomicity: both writes now share one index-lock
acquisition (`IndexStore.create_session_txn`), so the loser is stopped by the
row check *inside* that lock and never reaches the manifest at all. The pre-check
this test has to force stale is now `live_session_exists`. The assertions are
unchanged -- they are what the bug was about.

Affected: src/forge/session/manager.py, src/forge/session/index.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session import SessionManager, SessionStore
from forge.session.exceptions import SessionExistsError

pytestmark = pytest.mark.regression


def test_losing_a_name_race_leaves_the_winners_manifest_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()

    manager = SessionManager()
    manager.start_session("shared", worktree_path=str(project), direct=True, claude_session_id="w" * 8)
    winner = SessionStore(str(project), "shared").read()

    # start_session guards the name twice before committing: the index
    # (live_session_exists) and the manifest file (store.exists()). A loser that
    # read both before the winner wrote anything passes both, which is the window
    # this bug lives in. Both stale reads are forced here; everything after them
    # is the real code path, ending in create_session_txn's under-lock row check.
    real_live_exists = manager.index_store.live_session_exists
    monkeypatch.setattr(
        manager.index_store,
        "live_session_exists",
        lambda name, **kw: False if name == "shared" else real_live_exists(name, **kw),
    )

    real_store_exists = SessionStore.exists
    seen: dict[str, int] = {"shared": 0}

    def _first_look_misses(self: SessionStore) -> bool:
        """Miss only the pre-check, not any later `store.exists()`.

        Patching every call would make a buggy ordering skip its manifest
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
