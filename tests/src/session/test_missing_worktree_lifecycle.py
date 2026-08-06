"""Lifecycle contracts for live sessions whose recorded worktree disappeared."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from forge.core.ops.session_context import collect_bound_uuids
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.exceptions import SessionWorktreeMissingError


def _seed_degraded_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SessionManager, Path, Path]:
    forge_home = tmp_path / "forge-home"
    forge_root = tmp_path / "project"
    missing = tmp_path / "deleted-worktree"
    forge_root.mkdir()
    monkeypatch.setenv("FORGE_HOME", str(forge_home))

    state = create_session_state("degraded", worktree_path=str(missing))
    assert state.worktree is not None
    state.worktree.is_worktree = True
    state.forge_root = str(forge_root)
    state.confirmed.claude_session_id = "uuid-degraded"
    SessionStore(str(forge_root), state.name).write(state)
    index = IndexStore()
    index.add_from_state(
        state,
        project_root=str(forge_root),
        forge_root=str(forge_root),
        checkout_root=str(missing),
    )
    return SessionManager(index_store=index), forge_root, missing


@pytest.mark.parametrize(
    ("action", "invoke"),
    [
        (
            "launch",
            lambda manager, root: manager.switch_session("degraded", forge_root=str(root)),
        ),
        (
            "resume",
            lambda manager, root: manager.resume_session(
                "degraded",
                child_name="resume-child",
                forge_root=str(root),
            ),
        ),
        (
            "fork",
            lambda manager, root: manager.fork_session(
                "degraded",
                fork_name="fork-child",
                forge_root=str(root),
            ),
        ),
        (
            "launch",
            lambda manager, root: manager.relaunch_session(
                "degraded",
                child_name="launch-child",
                forge_root=str(root),
            ),
        ),
    ],
)
def test_checkout_dependent_operations_refuse_before_state_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    invoke: Callable[[SessionManager, Path], object],
) -> None:
    manager, forge_root, missing = _seed_degraded_session(tmp_path, monkeypatch)
    manifest = SessionStore(str(forge_root), "degraded").manifest_path
    index_path = manager.index_store.index_path
    manifest_before = manifest.read_bytes()
    index_before = index_path.read_bytes()

    with pytest.raises(SessionWorktreeMissingError) as exc_info:
        invoke(manager, forge_root)

    message = str(exc_info.value)
    assert f"cannot {action}" in message
    assert str(missing) in message
    assert "forge session delete degraded" in message
    assert manifest.read_bytes() == manifest_before
    assert index_path.read_bytes() == index_before
    assert not SessionStore(str(forge_root), "resume-child").exists()
    assert not SessionStore(str(forge_root), "fork-child").exists()
    assert not SessionStore(str(forge_root), "launch-child").exists()


def test_degraded_session_keeps_name_and_conversation_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, forge_root, _missing = _seed_degraded_session(tmp_path, monkeypatch)

    assert manager.index_store.live_session_exists("degraded", forge_root=str(forge_root))
    assert collect_bound_uuids()["uuid-degraded"] == "degraded"


def test_explicit_delete_removes_degraded_reservation_without_requiring_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, forge_root, missing = _seed_degraded_session(tmp_path, monkeypatch)

    manager.delete_session(
        "degraded",
        forge_root=str(forge_root),
        delete_transcripts=False,
        delete_worktree=True,
    )

    assert not missing.exists()
    assert not SessionStore(str(forge_root), "degraded").exists()
    assert not manager.index_store.session_exists("degraded", forge_root=str(forge_root))
