"""Tests for ContentStore — lazy content loading for snippet extraction.

Tests cover:
- Read/write roundtrips and self-healing
- Add/remove operations (idempotent)
- read_keys returns only requested subset
- Prune by valid keys
- Corrupted file handling
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.core.state import SchemaVersionError
from forge.search.content_store import CONTENT_STORE_VERSION, ContentStore
from forge.search.exceptions import ContentStoreCorruptedError


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "search-index" / "content.json"


@pytest.fixture
def store(store_path: Path) -> ContentStore:
    return ContentStore(store_path=store_path)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class TestContentStoreRead:
    def test_missing_file_returns_empty(self, store: ContentStore) -> None:
        assert store.read_all() == {}

    def test_valid_roundtrip(self, store: ContentStore) -> None:
        content_map = {"doc1": "hello world", "doc2": "foo bar baz"}
        store.write(content_map)
        loaded = store.read_all()
        assert loaded == content_map

    def test_corrupted_json_raises(self, store_path: Path) -> None:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text("not json{{{")
        store = ContentStore(store_path=store_path)
        with pytest.raises(ContentStoreCorruptedError):
            store.read_all()

    def test_wrong_schema_version_raises(self, store_path: Path) -> None:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps({"schema_version": 999}))
        store = ContentStore(store_path=store_path)
        with pytest.raises(SchemaVersionError):
            store.read_all()

    def test_missing_schema_version_raises(self, store_path: Path) -> None:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps({"content": {}}))
        store = ContentStore(store_path=store_path)
        with pytest.raises(ContentStoreCorruptedError):
            store.read_all()

    def test_non_dict_content_returns_empty(self, store_path: Path) -> None:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps({"schema_version": CONTENT_STORE_VERSION, "content": "not a dict"}))
        store = ContentStore(store_path=store_path)
        assert store.read_all() == {}


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


class TestContentStoreWrite:
    def test_creates_parent_directories(self, store: ContentStore) -> None:
        store.write({})
        assert store.store_path.is_file()

    def test_includes_schema_version(self, store: ContentStore) -> None:
        store.write({})
        data = json.loads(store.store_path.read_text())
        assert data["schema_version"] == CONTENT_STORE_VERSION

    def test_includes_updated_at(self, store: ContentStore) -> None:
        store.write({"doc1": "content"})
        data = json.loads(store.store_path.read_text())
        assert "updated_at" in data


# ---------------------------------------------------------------------------
# Read keys (lazy loading)
# ---------------------------------------------------------------------------


class TestContentStoreReadKeys:
    def test_returns_only_requested_keys(self, store: ContentStore) -> None:
        store.write({"a": "alpha", "b": "beta", "c": "gamma"})
        result = store.read_keys(["a", "c"])
        assert result == {"a": "alpha", "c": "gamma"}

    def test_missing_keys_omitted(self, store: ContentStore) -> None:
        store.write({"a": "alpha"})
        result = store.read_keys(["a", "nonexistent"])
        assert result == {"a": "alpha"}

    def test_empty_keys_returns_empty(self, store: ContentStore) -> None:
        store.write({"a": "alpha"})
        assert store.read_keys([]) == {}

    def test_missing_file_returns_empty(self, store: ContentStore) -> None:
        assert store.read_keys(["a"]) == {}


# ---------------------------------------------------------------------------
# Add (idempotent upsert)
# ---------------------------------------------------------------------------


class TestContentStoreAdd:
    def test_add_to_empty(self, store: ContentStore) -> None:
        store.add("doc1", "content one")
        assert store.read_all() == {"doc1": "content one"}

    def test_add_second_key(self, store: ContentStore) -> None:
        store.add("doc1", "one")
        store.add("doc2", "two")
        assert store.read_all() == {"doc1": "one", "doc2": "two"}

    def test_add_replaces_existing(self, store: ContentStore) -> None:
        store.add("doc1", "old content")
        store.add("doc1", "new content")
        assert store.read_all() == {"doc1": "new content"}

    def test_add_same_content_is_idempotent(self, store: ContentStore) -> None:
        store.add("doc1", "same")
        store.add("doc1", "same")
        content = store.read_all()
        assert content == {"doc1": "same"}
        assert len(content) == 1


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


class TestContentStoreRemove:
    def test_remove_existing(self, store: ContentStore) -> None:
        store.add("doc1", "content")
        assert store.remove("doc1") is True
        assert store.read_all() == {}

    def test_remove_nonexistent(self, store: ContentStore) -> None:
        store.add("doc1", "content")
        assert store.remove("doc_missing") is False
        assert "doc1" in store.read_all()

    def test_remove_from_empty(self, store: ContentStore) -> None:
        assert store.remove("anything") is False


# ---------------------------------------------------------------------------
# Prune
# ---------------------------------------------------------------------------


class TestContentStorePrune:
    def test_prune_removes_invalid_keys(self, store: ContentStore) -> None:
        store.write({"keep": "yes", "remove1": "no", "remove2": "no"})
        removed = store.prune_keys({"keep"})
        assert set(removed) == {"remove1", "remove2"}
        assert store.read_all() == {"keep": "yes"}

    def test_prune_no_op_when_all_valid(self, store: ContentStore) -> None:
        store.write({"a": "alpha", "b": "beta"})
        removed = store.prune_keys({"a", "b"})
        assert removed == []

    def test_prune_empty_store(self, store: ContentStore) -> None:
        assert store.prune_keys(set()) == []
