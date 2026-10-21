"""Selected transfer files and search keys keep their session ownership on retry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.search.bm25_store import BM25IndexStore
from forge.search.cleanup import search_store_paths
from forge.search.content_store import ContentStore
from forge.search.extractor import SearchDocumentMeta
from forge.search.index_state import IndexStateStore
from forge.search.store import SearchDocumentStore
from forge.session import IndexStore, SessionStore
from forge.session.cleanup_state import cleanup_state_path
from forge.session.deletion import (
    SessionDeletionPlan,
    apply_session_deletion,
    plan_session_deletion,
)
from forge.session.exceptions import ForgeSessionError
from forge.session.models import Derivation, create_session_state
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("phase", ["preview", "apply", "retry"])
@pytest.mark.parametrize("reference", ["snapshot", "notes"])
@pytest.mark.parametrize("relative", [False, True])
def test_borrowed_ancestor_child_content_refuses_before_any_removal(tmp_path, monkeypatch, phase, reference, relative):
    from forge.session import deletion

    root = tmp_path / "project"
    root.mkdir()
    index = IndexStore()
    snapshot = root / ".forge/prev_sessions/ancestor/children/subject.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("shared snapshot")
    notes = snapshot.with_name("subject.notes.md")
    notes.write_text("user notes")
    subject = create_session_state("subject", worktree_path=str(root))
    subject.forge_root = str(root)
    subject.confirmed.derivation = Derivation(
        parent_session="ancestor",
        parent_forge_root=str(root),
        context_file=str(snapshot.relative_to(root) if relative else snapshot),
    )
    publish_session(index, subject, root)

    def add_borrower():
        borrowed = snapshot if reference == "snapshot" else notes
        state = create_session_state("borrower", worktree_path=str(root))
        state.forge_root = str(root)
        state.confirmed.derivation = Derivation(
            parent_session="ancestor",
            parent_forge_root=str(root),
            context_file=str(borrowed.relative_to(root) if relative else borrowed),
        )
        publish_session(index, state, root)

    if phase == "preview":
        add_borrower()
    plan = plan_session_deletion(index, "subject", forge_root=str(root), delete_worktree=False)
    retry_path = cleanup_state_path(root, "subject")
    if phase == "retry":
        with monkeypatch.context() as context:
            context.setattr(deletion, "apply_forge_content", Mock(side_effect=OSError("interrupted cleanup")))
            with pytest.raises(ForgeSessionError, match="interrupted cleanup"):
                apply_session_deletion(index, plan)
        assert retry_path.exists()
    if phase != "preview":
        add_borrower()
    if phase == "retry":
        plan = plan_session_deletion(index, "subject", forge_root=str(root), delete_worktree=False)
        assert plan.retry
    if phase != "apply":
        assert any("borrower" in reason and "content reference" in reason for reason in plan.refusals)
    before = {path: path.read_bytes() for path in (snapshot, notes, index.index_path)}
    with pytest.raises(ForgeSessionError, match="borrower.*content reference"):
        apply_session_deletion(index, plan)
    assert all(path.read_bytes() == value for path, value in before.items())
    assert SessionStore(str(root), "subject").exists()
    assert retry_path.exists() == (phase == "retry")


@pytest.mark.parametrize("other_location", ["other-artifact", "external"])
def test_retry_inventory_rejects_unrelated_search_keys_without_mutation(tmp_path: Path, other_location: str) -> None:
    root = tmp_path / "project"
    root.mkdir()
    index = IndexStore()
    state = create_session_state("subject", worktree_path=str(root))
    state.forge_root = str(root)
    publish_session(index, state, root)
    other = (
        root / ".forge/artifacts/other/transcripts/other.jsonl"
        if other_location == "other-artifact"
        else tmp_path / "native/other.jsonl"
    )
    other.parent.mkdir(parents=True)
    other.write_text("unrelated transcript")
    key = str(other)
    SearchDocumentStore(root).add(SearchDocumentMeta(key, "other", "other-id", "2026-10-20"))
    ContentStore(root).add(key, "unrelated content")
    BM25IndexStore(root).upsert_document(key, {"unrelated": 1}, 1)
    IndexStateStore(root).mark_indexed(other)
    plan = plan_session_deletion(index, "subject", forge_root=str(root), delete_worktree=False)
    raw = json.loads(json.dumps(plan.to_dict()))
    raw["content"]["search_keys"].append(key)
    before = {path: path.read_bytes() for path in (*search_store_paths(root), index.index_path, other)}
    with pytest.raises(ValueError, match="search keys differ"):
        SessionDeletionPlan.from_dict(raw)
    assert all(path.read_bytes() == value for path, value in before.items())
    assert SessionStore(str(root), "subject").exists()
