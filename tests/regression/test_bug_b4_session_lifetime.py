"""B4 #4: retained artifacts from a deleted session became a new session's operational state."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.policy.semantic import stop_review as review
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.manager import SessionManager
from tests.fixtures.session_state import publish_session
from tests.fixtures.stop_review import changed, context, deadline, git

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("another_checkout", [False, True])
def test_recreation_has_no_old_scope_or_spending(tmp_path: Path, monkeypatch, another_checkout: bool) -> None:
    old = context(tmp_path)
    changed(old)
    journal = old.storage.parent / "events.jsonl"
    saved = journal.read_bytes()
    SessionManager().delete_session(
        old.session,
        forge_root=str(old.forge_root),
        delete_worktree=False,
        delete_transcripts=False,
    )
    assert journal.read_bytes() == saved
    checkout = old.checkout
    if another_checkout:
        checkout = tmp_path / "new-checkout"
        git(old.checkout, "worktree", "add", "-qb", "replacement", str(checkout))
    state = create_session_state(old.session, worktree_path=str(checkout), runtime="codex")
    state.forge_root = str(old.forge_root)
    publish_session(IndexStore(), state, checkout, forge_root=old.forge_root)
    identity = SessionStore(str(old.forge_root), old.session).review_identity()
    assert identity is not None
    fresh = replace(
        old,
        checkout=checkout,
        thread_id="01900000-0000-7000-8000-000000000099",
        session_identity=identity,
    )
    assert fresh.session_identity != old.session_identity
    reviewer = Mock(side_effect=AssertionError("A new question-only session must not review old work"))
    monkeypatch.setattr(review, "run_supervisor_check", reviewer)
    review.begin_turn(fresh, deadline=deadline())
    assert (
        review.review_stop(fresh, deadline=deadline(), current_config=lambda: fresh.config_digest).status
        == "no_changes"
    )
    assert journal.read_bytes() == saved
    assert review.reset_review(fresh.forge_root, fresh.session, apply=True)["applied"]
    with pytest.raises(ValueError, match="deleted or replaced"):
        review.begin_turn(old, deadline=deadline())
    reviewer.assert_not_called()


def test_lost_owner_cannot_reopen_an_established_allowance(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    store = SessionStore(str(ctx.forge_root), ctx.session)
    (store.session_dir / "review-identity").unlink()
    with pytest.raises(ValueError, match="restore the owner"):
        store.review_identity(create=True)
    assert review.status(ctx.forge_root, ctx.session)["reason"] == "review_history_unavailable"


def test_same_second_recreation_uses_a_new_owner(tmp_path: Path) -> None:
    from tests.fixtures.session_state import delete_published_session

    ctx = context(tmp_path)
    store = SessionStore(str(ctx.forge_root), ctx.session)
    state = store.read()
    delete_published_session(IndexStore(), ctx.session, forge_root=ctx.forge_root)
    # Identical timestamps/content are not a lifetime identity.
    publish_session(IndexStore(), state, ctx.checkout, forge_root=ctx.forge_root)
    assert store.review_identity() != ctx.session_identity
