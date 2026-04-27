"""Tests for the search document metadata store (v2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.core.state import SchemaVersionError
from forge.search.exceptions import SearchDocumentStoreCorruptedError
from forge.search.extractor import SearchDocumentMeta
from forge.search.store import DOCUMENT_STORE_VERSION, SearchDocumentStore


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "search-index" / "documents.json"


@pytest.fixture
def store(store_path: Path) -> SearchDocumentStore:
    return SearchDocumentStore(store_path=store_path)


@pytest.fixture
def sample_doc() -> SearchDocumentMeta:
    return SearchDocumentMeta(
        transcript_path="/tmp/artifacts/session/transcripts/uuid-123.jsonl",
        session_name="test-session",
        session_id="uuid-123",
        extracted_at="2026-02-08T10:00:00+00:00",
        metadata={"message_count": 5, "worktree_path": "/workspace"},
    )


class TestSearchDocumentStoreRead:
    """Tests for read behavior."""

    def test_missing_file_returns_empty_list(self, store: SearchDocumentStore) -> None:
        """Missing file returns empty list (self-healing)."""
        assert store.read() == []

    def test_valid_roundtrip(self, store: SearchDocumentStore, sample_doc: SearchDocumentMeta) -> None:
        """Write then read produces identical documents."""
        store.write([sample_doc])
        docs = store.read()
        assert len(docs) == 1
        assert docs[0].transcript_path == sample_doc.transcript_path
        assert docs[0].session_name == sample_doc.session_name

    def test_corrupted_json_raises(self, store: SearchDocumentStore) -> None:
        """Corrupted JSON raises SearchDocumentStoreCorruptedError."""
        store.store_path.parent.mkdir(parents=True, exist_ok=True)
        store.store_path.write_text("not valid json")
        with pytest.raises(SearchDocumentStoreCorruptedError):
            store.read()

    def test_wrong_version_raises(self, store: SearchDocumentStore) -> None:
        """Wrong schema version raises SchemaVersionError."""
        store.store_path.parent.mkdir(parents=True, exist_ok=True)
        store.store_path.write_text(json.dumps({"schema_version": 999, "documents": []}))
        with pytest.raises(SchemaVersionError):
            store.read()

    def test_non_list_documents_returns_empty_with_warning(
        self, store: SearchDocumentStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-list 'documents' field returns [] and logs a warning."""
        store.store_path.parent.mkdir(parents=True, exist_ok=True)
        store.store_path.write_text(json.dumps({"schema_version": DOCUMENT_STORE_VERSION, "documents": "not a list"}))
        import logging

        with caplog.at_level(logging.WARNING):
            docs = store.read()
        assert docs == []
        assert any("non-list" in record.message for record in caplog.records)


class TestSearchDocumentStoreWrite:
    """Tests for write behavior."""

    def test_creates_parent_dirs(self, store: SearchDocumentStore, sample_doc: SearchDocumentMeta) -> None:
        """Write creates parent directories if missing."""
        assert not store.store_path.parent.exists()
        store.write([sample_doc])
        assert store.store_path.is_file()

    def test_sets_updated_at(self, store: SearchDocumentStore) -> None:
        """Write sets updated_at timestamp."""
        store.write([])
        data = json.loads(store.store_path.read_text())
        assert "updated_at" in data
        assert data["updated_at"]  # Non-empty

    def test_schema_version_written(self, store: SearchDocumentStore) -> None:
        """Write includes correct schema_version."""
        store.write([])
        data = json.loads(store.store_path.read_text())
        assert data["schema_version"] == DOCUMENT_STORE_VERSION

    def test_no_content_or_tokens_in_output(self, store: SearchDocumentStore, sample_doc: SearchDocumentMeta) -> None:
        """V2 store does not write content or tokens fields."""
        store.write([sample_doc])
        data = json.loads(store.store_path.read_text())
        doc_data = data["documents"][0]
        assert "content" not in doc_data
        assert "tokens" not in doc_data


class TestSearchDocumentStoreAdd:
    """Tests for add (locked RMW) behavior."""

    def test_add_new_document(self, store: SearchDocumentStore, sample_doc: SearchDocumentMeta) -> None:
        """Add appends a new document."""
        store.add(sample_doc)
        docs = store.read()
        assert len(docs) == 1
        assert docs[0].session_id == "uuid-123"

    def test_add_replaces_existing_by_path(self, store: SearchDocumentStore, sample_doc: SearchDocumentMeta) -> None:
        """Add replaces existing document with same transcript_path."""
        store.add(sample_doc)

        updated = SearchDocumentMeta(
            transcript_path=sample_doc.transcript_path,
            session_name=sample_doc.session_name,
            session_id=sample_doc.session_id,
            extracted_at="2026-02-08T11:00:00+00:00",
            metadata={"message_count": 10},
        )
        store.add(updated)

        docs = store.read()
        assert len(docs) == 1
        assert docs[0].metadata["message_count"] == 10


class TestSearchDocumentStorePrune:
    """Tests for prune_missing behavior."""

    def _make_meta(self, transcript_path: str) -> SearchDocumentMeta:
        return SearchDocumentMeta(
            transcript_path=transcript_path,
            session_name="s",
            session_id="id",
            extracted_at="2026-01-01T00:00:00+00:00",
            metadata={},
        )

    def test_prune_removes_missing_files(self, store: SearchDocumentStore) -> None:
        """Documents with nonexistent transcript_path are removed."""
        doc = self._make_meta("/nonexistent/transcript.jsonl")
        store.write([doc])
        removed = store.prune_missing()
        assert removed == ["/nonexistent/transcript.jsonl"]
        assert store.read() == []

    def test_prune_keeps_existing_files(self, store: SearchDocumentStore, tmp_path: Path) -> None:
        """Documents with existing transcript_path are kept."""
        real_file = tmp_path / "real.jsonl"
        real_file.write_text("{}")
        doc = self._make_meta(str(real_file))
        store.write([doc])
        removed = store.prune_missing()
        assert removed == []
        assert len(store.read()) == 1

    def test_prune_mixed(self, store: SearchDocumentStore, tmp_path: Path) -> None:
        """Only documents with missing files are removed."""
        real_file = tmp_path / "real.jsonl"
        real_file.write_text("{}")
        kept_doc = self._make_meta(str(real_file))
        ghost_doc = self._make_meta("/nonexistent/ghost.jsonl")
        store.write([kept_doc, ghost_doc])

        removed = store.prune_missing()
        assert removed == ["/nonexistent/ghost.jsonl"]
        docs = store.read()
        assert len(docs) == 1
        assert docs[0].transcript_path == str(real_file)

    def test_prune_empty_store(self, store: SearchDocumentStore) -> None:
        """Empty store returns empty list."""
        removed = store.prune_missing()
        assert removed == []

    def test_prune_noop_skips_write(self, store: SearchDocumentStore, tmp_path: Path) -> None:
        """When all docs are valid, store file is not rewritten."""
        real_file = tmp_path / "real.jsonl"
        real_file.write_text("{}")
        doc = self._make_meta(str(real_file))
        store.write([doc])

        mtime_before = store.store_path.stat().st_mtime_ns
        removed = store.prune_missing()
        mtime_after = store.store_path.stat().st_mtime_ns

        assert removed == []
        assert mtime_before == mtime_after


class TestSearchDocumentStoreRemove:
    """Tests for remove behavior."""

    def test_remove_existing(self, store: SearchDocumentStore, sample_doc: SearchDocumentMeta) -> None:
        """Remove returns True and deletes the document."""
        store.add(sample_doc)
        assert store.remove(sample_doc.transcript_path) is True
        assert store.read() == []

    def test_remove_nonexistent_returns_false(self, store: SearchDocumentStore) -> None:
        """Remove returns False when document not found."""
        store.write([])
        assert store.remove("/nonexistent/path.jsonl") is False
