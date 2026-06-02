"""Regression: resume auto-name retry must retarget child handoff context."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session import SessionManager, SessionStore, create_session_state
from forge.session.exceptions import SessionExistsError
from forge.session.prev_sessions import child_path, child_path_rel

pytestmark = pytest.mark.regression


def test_resume_autoname_retry_updates_context_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    parent = create_session_state(
        "parent",
        proxy_template="litellm-openai",
        proxy_base_url="http://localhost:8085",
        worktree_path=str(project),
    )
    parent.forge_root = str(project)

    manager = SessionManager()
    SessionStore(str(project), "parent").write(parent)
    manager.index_store.add_from_state(
        parent,
        str(project),
        checkout_root=str(project),
        forge_root=str(project),
        relative_path=".",
    )

    original_add = manager.index_store.add_from_state
    failed_once = False

    def fail_base_name_once(state, *args, **kwargs):
        nonlocal failed_once
        if state.name == "parent-resumed" and not failed_once:
            failed_once = True
            manager.index_store.add_session(
                name="parent-resumed",
                worktree_path=str(project),
                project_root=str(project),
                forge_root=str(project),
                checkout_root=str(project),
                relative_path=".",
                is_incognito=False,
                is_fork=False,
                parent_session="parent",
            )
            raise SessionExistsError("parent-resumed")
        return original_add(state, *args, **kwargs)

    manager.index_store.add_from_state = fail_base_name_once  # type: ignore[method-assign]

    child, handoff = manager.resume_session("parent")

    assert failed_once is True
    assert child.name.startswith("parent-resumed-")
    expected_rel = child_path_rel("parent", child.name)
    expected_path = child_path(project, "parent", child.name)
    original_path = child_path(project, "parent", "parent-resumed")
    assert child.confirmed.derivation is not None
    assert child.confirmed.derivation.context_file == expected_rel
    assert handoff.context_file_rel == expected_rel
    assert handoff.context_file == expected_path
    assert expected_path.is_file()
    # The winning `parent-resumed` owns its snapshot path, so it is PRESERVED: in a real race
    # the byte-identical file at original_path IS the winner's snapshot, and deleting it was the
    # data-loss bug (audit P3/#2). The loser retargets to its own fresh name instead.
    assert original_path.exists()

    persisted = SessionStore(str(project), child.name).read()
    assert persisted.confirmed.derivation is not None
    assert persisted.confirmed.derivation.context_file == expected_rel


def test_resume_autoname_collision_preserves_winner_curated_context(tmp_path: Path) -> None:
    """Audit P3/#2: a colliding concurrent resume must NOT delete the winner's curated snapshot.

    Reproduces the data-loss race: two resumes of the same parent auto-name `parent-resumed`;
    the loser's retry-cleanup byte-compare cannot distinguish its throwaway copy from the
    winner's byte-identical (or curated) snapshot, so it used to unlink the winner's file.
    """
    project = tmp_path / "project"
    project.mkdir()

    parent = create_session_state(
        "parent",
        proxy_template="litellm-openai",
        proxy_base_url="http://localhost:8085",
        worktree_path=str(project),
    )
    parent.forge_root = str(project)

    manager = SessionManager()
    SessionStore(str(project), "parent").write(parent)
    manager.index_store.add_from_state(
        parent, str(project), checkout_root=str(project), forge_root=str(project), relative_path="."
    )

    # Pre-seed the WINNER: an indexed `parent-resumed` whose curated snapshot already exists.
    manager.index_store.add_session(
        name="parent-resumed",
        worktree_path=str(project),
        project_root=str(project),
        forge_root=str(project),
        checkout_root=str(project),
        relative_path=".",
        is_incognito=False,
        is_fork=False,
        parent_session="parent",
    )
    winner_snapshot = child_path(project, "parent", "parent-resumed")
    winner_snapshot.parent.mkdir(parents=True, exist_ok=True)
    winner_snapshot.write_text("WINNER CURATED CONTEXT\n")

    # The loser resumes; its auto-name collides on `parent-resumed` at add_from_state.
    child, _ = manager.resume_session("parent")

    assert child.name.startswith("parent-resumed-"), "loser must retry under a fresh unique name"
    assert winner_snapshot.exists(), "winner's curated snapshot must be preserved"
    assert winner_snapshot.read_text() == "WINNER CURATED CONTEXT\n", "winner's snapshot must be unmodified"
