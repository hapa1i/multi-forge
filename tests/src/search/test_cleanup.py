"""Cross-store removal preserves unrelated search documents and corpus statistics."""

import json
from pathlib import Path

import pytest

from forge.search.bm25_store import BM25IndexStore
from forge.search.cleanup import (
    indexed_transcript_paths,
    remove_transcript_paths,
    search_store_paths,
)
from forge.search.content_store import ContentStore
from forge.search.extractor import SearchDocumentMeta
from forge.search.index_state import IndexStateStore
from forge.search.store import SearchDocumentStore
from forge.session.cleanup_content import (
    ForgeContentPlan,
    apply_forge_content,
    plan_forge_content,
    validate_forge_content_scope,
)
from forge.session.models import create_session_state


def _index(root: Path, session: str, *, path: Path | None = None) -> str:
    path = path or root / ".forge/artifacts" / session / "transcripts/test.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("shared unique")
    key = str(path)
    SearchDocumentStore(root).add(SearchDocumentMeta(key, session, f"{session}-id", "2026-10-20"))
    ContentStore(root).add(key, f"shared {session}")
    BM25IndexStore(root).upsert_document(key, {"shared": 1, session: 1}, 2)
    IndexStateStore(root).mark_indexed(path)
    return key


def test_remove_all_representations_and_recompute_bm25(tmp_path: Path) -> None:
    subject, other = _index(tmp_path, "subject"), _index(tmp_path, "other")
    remove_transcript_paths(tmp_path, (subject,))
    assert indexed_transcript_paths(tmp_path) == {other}
    assert [doc.transcript_path for doc in SearchDocumentStore(tmp_path).read()] == [other]
    assert ContentStore(tmp_path).read_all() == {other: "shared other"}
    index = BM25IndexStore(tmp_path).read()
    assert index is not None
    assert index.doc_keys == [other]
    assert index.doc_freqs == {"shared": 1, "other": 1}
    assert index.avgdl == 2
    before = {path: path.read_bytes() for path in search_store_paths(tmp_path)}
    remove_transcript_paths(tmp_path, (subject,))
    assert {path: path.read_bytes() for path in search_store_paths(tmp_path)} == before


def test_session_plan_removes_orphan_content_keys_without_metadata(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    key = str(root / ".forge/artifacts/subject/transcripts/missing.jsonl")
    ContentStore(root).add(key, "private orphan content")
    state = create_session_state("subject", worktree_path=str(root))
    plan = plan_forge_content(state, forge_root=root, forge_home=tmp_path / "home")
    assert plan.search_keys == (key,)
    apply_forge_content(plan)
    assert ContentStore(root).read_all() == {}


def test_corruption_in_final_store_prevents_any_removal(tmp_path: Path) -> None:
    key = _index(tmp_path, "subject")
    IndexStateStore(tmp_path).state_path.write_text(json.dumps({"schema_version": 1, "indexed_files": {"bad": {}}}))
    before = {path: path.read_bytes() for path in search_store_paths(tmp_path)}
    with pytest.raises(ValueError, match="Malformed search fingerprints"):
        remove_transcript_paths(tmp_path, (key,))
    assert {path: path.read_bytes() for path in search_store_paths(tmp_path)} == before


def test_partial_store_failure_retries_to_coherent_final_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subject, other = _index(tmp_path, "subject"), _index(tmp_path, "other")
    original = ContentStore.write

    def fail_write(self, content):
        raise PermissionError("injected search write failure")

    monkeypatch.setattr(ContentStore, "write", fail_write)
    with pytest.raises(PermissionError, match="injected"):
        remove_transcript_paths(tmp_path, (subject,))
    assert [doc.transcript_path for doc in SearchDocumentStore(tmp_path).read()] == [other]
    assert subject in ContentStore(tmp_path).read_all()
    monkeypatch.setattr(ContentStore, "write", original)
    remove_transcript_paths(tmp_path, (subject,))
    assert indexed_transcript_paths(tmp_path) == {other}


@pytest.mark.parametrize("external", [False, True])
def test_saved_owned_search_keys_survive_missing_file_and_partial_metadata_removal(tmp_path, monkeypatch, external):
    root = tmp_path / "project"
    override = tmp_path / "historical/subject.jsonl" if external else None
    subject = _index(root, "subject", path=override)
    other = _index(root, "other")
    state = create_session_state("subject", worktree_path=str(root))
    state.forge_root = str(root)
    state.confirmed.claude_session_id = "subject-id"
    state.confirmed.artifacts["transcripts"] = [{"session_id": "subject-id", "copied_path": subject}]
    plan = plan_forge_content(state, forge_root=root)
    assert not plan.refusals
    assert plan.search_keys == (subject,)
    Path(subject).unlink()

    def fail_write(self, content):
        raise OSError("interrupted write")

    with monkeypatch.context() as context:
        context.setattr(ContentStore, "write", fail_write)
        with pytest.raises(OSError, match="interrupted write"):
            apply_forge_content(plan)
    assert [doc.transcript_path for doc in SearchDocumentStore(root).read()] == [other]
    assert subject in ContentStore(root).read_all()
    restored = ForgeContentPlan.from_dict(json.loads(json.dumps(plan.to_dict())))
    validate_forge_content_scope(restored, state)
    apply_forge_content(restored)
    assert indexed_transcript_paths(root) == {other}
    assert Path(other).exists()


def test_external_search_metadata_without_recorded_path_refuses(tmp_path: Path) -> None:
    root = tmp_path / "project"
    key = _index(root, "subject", path=tmp_path / "unrecorded/transcript.jsonl")
    state = create_session_state("subject", worktree_path=str(root))
    state.confirmed.claude_session_id = "subject-id"
    plan = plan_forge_content(state, forge_root=root)
    assert any(key in reason and "no recorded session ownership" in reason for reason in plan.refusals)
    with pytest.raises(ValueError, match="no recorded session ownership"):
        apply_forge_content(plan)
    assert indexed_transcript_paths(root) == {key}


def test_external_search_metadata_reassignment_refuses_saved_inventory(tmp_path: Path) -> None:
    root = tmp_path / "project"
    key = _index(root, "subject", path=tmp_path / "historical/transcript.jsonl")
    state = create_session_state("subject", worktree_path=str(root))
    state.forge_root = str(root)
    state.confirmed.claude_session_id = "subject-id"
    state.confirmed.artifacts["transcripts"] = [{"session_id": "subject-id", "copied_path": key}]
    plan = plan_forge_content(state, forge_root=root)
    SearchDocumentStore(root).add(SearchDocumentMeta(key, "other", "other-id", "2026-10-20"))
    before = {path: path.read_bytes() for path in search_store_paths(root)}
    with pytest.raises(ValueError, match="search ownership changed"):
        validate_forge_content_scope(plan, state)
    assert {path: path.read_bytes() for path in search_store_paths(root)} == before
