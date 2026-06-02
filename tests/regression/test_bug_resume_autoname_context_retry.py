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
    """Audit dead-coverage fix: drive the REAL race and assert the winner's genuinely-curated
    (NON-byte-identical) snapshot survives the loser's collision retry.

    The prior version pre-seeded `parent-resumed` in the index BEFORE resume_session, so
    _generate_resume_name picked a fresh suffix and the collision -- and the entire
    `except SessionExistsError` fix branch -- never ran (it passed with the fix reverted). This
    version injects the winner mid-`add_from_state` (like the first test) so the loser actually hits
    the branch, and covers the case the first test does not: a winner that ran `forge transfer edit`
    has content != generated.md, and winner_owns must preserve it (the fix short-circuits the
    orphan-unlink before any byte-compare).
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

    winner_snapshot = child_path(project, "parent", "parent-resumed")
    curated = "WINNER-CURATED (user-edited via forge transfer edit)\n"

    original_add = manager.index_store.add_from_state
    failed_once = False

    def fail_base_name_once(state, *args, **kwargs):
        nonlocal failed_once
        if state.name == "parent-resumed" and not failed_once:
            failed_once = True
            # The winner wins the name AND has curated its snapshot (content != generated.md).
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
            winner_snapshot.parent.mkdir(parents=True, exist_ok=True)
            winner_snapshot.write_text(curated)
            raise SessionExistsError("parent-resumed")
        return original_add(state, *args, **kwargs)

    manager.index_store.add_from_state = fail_base_name_once  # type: ignore[method-assign]

    child, _ = manager.resume_session("parent")

    assert failed_once is True, "the loser must actually hit the SessionExistsError collision branch"
    assert child.name.startswith("parent-resumed-"), "loser must retry under a fresh unique name"
    assert winner_snapshot.exists(), "winner's curated snapshot must be preserved"
    assert (
        winner_snapshot.read_text() == curated
    ), "winner's curated snapshot must be unmodified (winner_owns short-circuits the orphan-unlink)"


def test_resume_autoname_collision_preserves_winner_manifest(tmp_path: Path) -> None:
    """Audit second-pass (HIGH): a losing concurrent resume must not overwrite the winner's MANIFEST.

    _persist_resume_child reserves the index name (add_from_state) BEFORE writing
    .forge/sessions/<child>/forge.session.json, so on a `parent-resumed` collision the loser never
    touches the winner's manifest path. Pre-fix the manifest was written at the TOP of the loop --
    before the collision was detected -- so the loser clobbered the winner's manifest. The
    snapshot/index-only tests above miss this because they never write a real winner manifest.
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

    # The winner's manifest is already on disk at the colliding name with a distinct marker,
    # simulating the winner's child_store.write having landed. NOT in the index yet, so
    # _generate_resume_name (index-only check) still picks "parent-resumed" and the collision fires.
    winner_store = SessionStore(str(project), "parent-resumed")
    winner_state = create_session_state(
        "parent-resumed",
        proxy_template="litellm-openai",
        proxy_base_url="http://localhost:8085",
        worktree_path=str(project),
    )
    winner_state.forge_root = str(project)
    winner_state.confirmed.claude_session_id = "winner-uuid-xyz"
    winner_store.write(winner_state)
    winner_manifest_bytes = winner_store.manifest_path.read_bytes()

    original_add = manager.index_store.add_from_state
    failed_once = False

    def fail_base_name_once(state, *args, **kwargs):
        nonlocal failed_once
        if state.name == "parent-resumed" and not failed_once:
            failed_once = True
            # Winner reserves the name in the index (its manifest is already on disk above).
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

    child, _ = manager.resume_session("parent")

    assert failed_once is True, "the loser must hit the SessionExistsError collision branch"
    assert child.name.startswith("parent-resumed-"), "loser must retry under a fresh unique name"
    assert (
        winner_store.manifest_path.read_bytes() == winner_manifest_bytes
    ), "winner's manifest must be byte-identical (loser must never write to the colliding path)"
    assert b"winner-uuid-xyz" in winner_store.manifest_path.read_bytes(), "winner's content survives, not the loser's"
