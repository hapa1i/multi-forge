"""D009 regression: a surviving manifest must outlive its missing worktree.

Root cause: ``IndexStore.list_sessions`` pruned rows when either the manifest or
recorded worktree was absent, while ``get_session`` treated the surviving
manifest as authoritative. The same session was therefore live by lookup but
silently deleted by listing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.identity import make_scoped_key

pytestmark = pytest.mark.regression


def test_list_retains_session_with_valid_manifest_and_missing_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_home = tmp_path / "forge-home"
    forge_root = tmp_path / "project"
    missing_worktree = tmp_path / "deleted-worktree"
    forge_root.mkdir()
    monkeypatch.setenv("FORGE_HOME", str(forge_home))

    state = create_session_state("degraded", worktree_path=str(missing_worktree))
    assert state.worktree is not None
    state.worktree.is_worktree = True
    state.forge_root = str(forge_root)
    SessionStore(str(forge_root), state.name).write(state)

    index = IndexStore()
    index.add_from_state(
        state,
        project_root=str(forge_root),
        forge_root=str(forge_root),
        checkout_root=str(missing_worktree),
    )

    assert index.get_session(state.name, forge_root=str(forge_root)).worktree_path == str(missing_worktree)
    assert [name for name, _entry in index.list_sessions()] == [state.name]
    assert make_scoped_key(state.name, str(forge_root)) in index.read().sessions
