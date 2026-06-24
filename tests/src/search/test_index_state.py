"""Tests for the search index state (forge.search.index_state).

Covers: IndexedFileEntry construction, IndexState pure operations
(needs_reindex, mark_indexed, prune_missing), IndexStateStore persistence
(read, write, update), convenience wrappers, and error handling.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from forge.core.state import SchemaVersionError
from forge.search.exceptions import IndexStateCorruptedError
from forge.search.index_state import (
    INDEX_STATE_VERSION,
    IndexedFileEntry,
    IndexState,
    IndexStateStore,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    """Isolated state file path (parent dir does not exist yet)."""
    return tmp_path / "search-index" / "state.json"


@pytest.fixture
def store(state_path: Path) -> IndexStateStore:
    """IndexStateStore with isolated path."""
    return IndexStateStore(state_path=state_path)


@pytest.fixture
def transcript_file(tmp_path: Path) -> Path:
    """Create a sample transcript JSONL file for indexing tests."""
    f = tmp_path / "artifacts" / "session-1" / "transcripts" / "uuid-123.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text('{"role":"user","content":"hello"}\n')
    return f


@pytest.fixture
def second_transcript(tmp_path: Path) -> Path:
    """Create a second transcript file."""
    f = tmp_path / "artifacts" / "session-2" / "transcripts" / "uuid-456.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text('{"role":"user","content":"world"}\n')
    return f


# ---------------------------------------------------------------------------
# IndexedFileEntry
# ---------------------------------------------------------------------------


class TestIndexedFileEntry:
    def test_create_with_all_fields(self) -> None:
        entry = IndexedFileEntry(mtime=1738800000.5, size=1024, indexed_at="2026-02-06T10:00:00+00:00")
        assert entry.mtime == 1738800000.5
        assert entry.size == 1024
        assert entry.indexed_at == "2026-02-06T10:00:00+00:00"

    def test_fields_are_correct_types(self) -> None:
        entry = IndexedFileEntry(mtime=1.0, size=0, indexed_at="")
        assert isinstance(entry.mtime, float)
        assert isinstance(entry.size, int)
        assert isinstance(entry.indexed_at, str)


# ---------------------------------------------------------------------------
# IndexState.needs_reindex
# ---------------------------------------------------------------------------


class TestIndexStateNeedsReindex:
    def test_new_file_returns_true(self, transcript_file: Path) -> None:
        """File not in index → needs reindexing."""
        state = IndexState()
        assert state.needs_reindex(transcript_file) is True

    def test_unchanged_file_returns_false(self, transcript_file: Path) -> None:
        """File in index with matching mtime/size → no reindex needed."""
        stat = os.stat(transcript_file)
        state = IndexState(
            indexed_files={
                str(transcript_file): IndexedFileEntry(mtime=stat.st_mtime, size=stat.st_size, indexed_at="t")
            }
        )
        assert state.needs_reindex(transcript_file) is False

    def test_mtime_changed_returns_true(self, transcript_file: Path) -> None:
        """File mtime differs from stored → needs reindexing."""
        state = IndexState(
            indexed_files={
                str(transcript_file): IndexedFileEntry(mtime=0.0, size=os.stat(transcript_file).st_size, indexed_at="t")
            }
        )
        assert state.needs_reindex(transcript_file) is True

    def test_size_changed_returns_true(self, transcript_file: Path) -> None:
        """File size differs from stored → needs reindexing."""
        state = IndexState(
            indexed_files={
                str(transcript_file): IndexedFileEntry(mtime=os.stat(transcript_file).st_mtime, size=0, indexed_at="t")
            }
        )
        assert state.needs_reindex(transcript_file) is True

    def test_missing_file_no_entry_returns_false(self, tmp_path: Path) -> None:
        """File not on disk and not in index → False (nothing to do)."""
        state = IndexState()
        missing = tmp_path / "does-not-exist.jsonl"
        assert state.needs_reindex(missing) is False

    def test_missing_file_with_entry_returns_false(self, tmp_path: Path) -> None:
        """File not on disk but in index → False (prune_missing handles it)."""
        missing = tmp_path / "gone.jsonl"
        state = IndexState(indexed_files={str(missing): IndexedFileEntry(mtime=1.0, size=100, indexed_at="t")})
        assert state.needs_reindex(missing) is False

    def test_relative_path_raises_valueerror(self) -> None:
        """Relative paths are rejected at the boundary."""
        state = IndexState()
        with pytest.raises(ValueError, match="path must be absolute"):
            state.needs_reindex(Path("relative/path.jsonl"))


# ---------------------------------------------------------------------------
# IndexState.mark_indexed
# ---------------------------------------------------------------------------


class TestIndexStateMarkIndexed:
    def test_new_file_adds_entry(self, transcript_file: Path) -> None:
        state = IndexState()
        state.mark_indexed(transcript_file)
        assert str(transcript_file) in state.indexed_files

    def test_update_existing_entry(self, transcript_file: Path) -> None:
        """Calling mark_indexed on an already-indexed file updates the entry."""
        state = IndexState(indexed_files={str(transcript_file): IndexedFileEntry(mtime=0.0, size=0, indexed_at="old")})
        state.mark_indexed(transcript_file)
        entry = state.indexed_files[str(transcript_file)]
        assert entry.mtime != 0.0
        assert entry.indexed_at != "old"

    def test_records_correct_mtime_and_size(self, transcript_file: Path) -> None:
        stat = os.stat(transcript_file)
        state = IndexState()
        state.mark_indexed(transcript_file)
        entry = state.indexed_files[str(transcript_file)]
        assert entry.mtime == stat.st_mtime
        assert entry.size == stat.st_size

    def test_sets_indexed_at_timestamp(self, transcript_file: Path) -> None:
        state = IndexState()
        state.mark_indexed(transcript_file)
        entry = state.indexed_files[str(transcript_file)]
        assert entry.indexed_at  # Non-empty
        assert "T" in entry.indexed_at  # ISO8601 format

    def test_relative_path_raises_valueerror(self) -> None:
        state = IndexState()
        with pytest.raises(ValueError, match="path must be absolute"):
            state.mark_indexed(Path("relative/path.jsonl"))

    def test_missing_file_raises_filenotfounderror(self, tmp_path: Path) -> None:
        state = IndexState()
        missing = tmp_path / "does-not-exist.jsonl"
        with pytest.raises(FileNotFoundError):
            state.mark_indexed(missing)


# ---------------------------------------------------------------------------
# IndexState.prune_missing
# ---------------------------------------------------------------------------


class TestIndexStatePruneMissing:
    def test_removes_deleted_files(self, tmp_path: Path) -> None:
        gone = tmp_path / "gone.jsonl"
        state = IndexState(indexed_files={str(gone): IndexedFileEntry(mtime=1.0, size=100, indexed_at="t")})
        removed = state.prune_missing()
        assert str(gone) in removed
        assert str(gone) not in state.indexed_files

    def test_keeps_existing_files(self, transcript_file: Path) -> None:
        stat = os.stat(transcript_file)
        state = IndexState(
            indexed_files={
                str(transcript_file): IndexedFileEntry(mtime=stat.st_mtime, size=stat.st_size, indexed_at="t")
            }
        )
        removed = state.prune_missing()
        assert removed == []
        assert str(transcript_file) in state.indexed_files

    def test_returns_removed_paths(self, tmp_path: Path) -> None:
        gone1 = tmp_path / "a.jsonl"
        gone2 = tmp_path / "b.jsonl"
        state = IndexState(
            indexed_files={
                str(gone1): IndexedFileEntry(mtime=1.0, size=1, indexed_at="t"),
                str(gone2): IndexedFileEntry(mtime=2.0, size=2, indexed_at="t"),
            }
        )
        removed = state.prune_missing()
        assert sorted(removed) == sorted([str(gone1), str(gone2)])

    def test_empty_state_is_noop(self) -> None:
        state = IndexState()
        removed = state.prune_missing()
        assert removed == []

    def test_idempotent_second_call_returns_empty(self, tmp_path: Path) -> None:
        """Second prune returns empty — entries were actually deleted."""
        gone = tmp_path / "gone.jsonl"
        state = IndexState(indexed_files={str(gone): IndexedFileEntry(mtime=1.0, size=100, indexed_at="t")})
        state.prune_missing()
        removed = state.prune_missing()
        assert removed == []


# ---------------------------------------------------------------------------
# IndexStateStore.read
# ---------------------------------------------------------------------------


class TestIndexStateStoreRead:
    def test_missing_file_returns_empty_state(self, store: IndexStateStore) -> None:
        """No state file → empty IndexState (self-healing)."""
        state = store.read()
        assert state.schema_version == INDEX_STATE_VERSION
        assert state.indexed_files == {}

    def test_valid_roundtrip(self, store: IndexStateStore, transcript_file: Path) -> None:
        """Write then read produces equivalent state."""
        state = IndexState()
        state.mark_indexed(transcript_file)
        store.write(state)

        loaded = store.read()
        assert str(transcript_file) in loaded.indexed_files
        entry = loaded.indexed_files[str(transcript_file)]
        assert entry.mtime == os.stat(transcript_file).st_mtime
        assert entry.size == os.stat(transcript_file).st_size

    def test_corrupted_json_raises(self, store: IndexStateStore) -> None:
        store.state_path.parent.mkdir(parents=True, exist_ok=True)
        store.state_path.write_text("not json{{{")
        with pytest.raises(IndexStateCorruptedError, match="invalid JSON"):
            store.read()

    def test_wrong_version_raises_schema_version_error(self, store: IndexStateStore) -> None:
        store.state_path.parent.mkdir(parents=True, exist_ok=True)
        store.state_path.write_text(json.dumps({"schema_version": 99}))
        with pytest.raises(SchemaVersionError) as exc_info:
            store.read()
        assert exc_info.value.actual == 99
        assert INDEX_STATE_VERSION in exc_info.value.expected

    def test_missing_version_raises(self, store: IndexStateStore) -> None:
        store.state_path.parent.mkdir(parents=True, exist_ok=True)
        store.state_path.write_text(json.dumps({"indexed_files": {}}))
        with pytest.raises(IndexStateCorruptedError, match="missing schema_version"):
            store.read()


# ---------------------------------------------------------------------------
# IndexStateStore.write
# ---------------------------------------------------------------------------


class TestIndexStateStoreWrite:
    def test_creates_parent_dirs(self, store: IndexStateStore) -> None:
        """write() creates ~/.forge/search-index/ if missing."""
        assert not store.state_path.parent.exists()
        store.write(IndexState())
        assert store.state_path.is_file()

    def test_sets_updated_at(self, store: IndexStateStore) -> None:
        state = IndexState()
        assert state.updated_at == ""
        store.write(state)
        assert state.updated_at != ""
        assert "T" in state.updated_at  # ISO8601

    def test_roundtrip(self, store: IndexStateStore) -> None:
        """Write and read produce consistent state."""
        original = IndexState()
        store.write(original)
        loaded = store.read()
        assert loaded.schema_version == INDEX_STATE_VERSION
        assert loaded.updated_at == original.updated_at
        assert loaded.indexed_files == {}


# ---------------------------------------------------------------------------
# IndexStateStore.update
# ---------------------------------------------------------------------------


class TestIndexStateStoreUpdate:
    def test_locked_rmw_cycle(self, store: IndexStateStore, transcript_file: Path) -> None:
        """update() performs locked read-modify-write."""
        store.write(IndexState())

        def add_file(state: IndexState) -> None:
            state.mark_indexed(transcript_file)

        result = store.update(timeout_s=5.0, mutate=add_file)
        assert str(transcript_file) in result.indexed_files

        # Verify persisted
        loaded = store.read()
        assert str(transcript_file) in loaded.indexed_files

    def test_mutate_exception_propagates(self, store: IndexStateStore) -> None:
        """Exceptions from mutate are not swallowed."""
        store.write(IndexState())

        def bad_mutate(state: IndexState) -> None:
            raise RuntimeError("intentional error")

        with pytest.raises(RuntimeError, match="intentional error"):
            store.update(timeout_s=5.0, mutate=bad_mutate)


# ---------------------------------------------------------------------------
# IndexStateStore convenience wrappers
# ---------------------------------------------------------------------------


class TestIndexStateStoreConvenience:
    def test_mark_indexed_persists(self, store: IndexStateStore, transcript_file: Path) -> None:
        """store.mark_indexed() persists to disk."""
        store.mark_indexed(transcript_file)

        loaded = store.read()
        assert str(transcript_file) in loaded.indexed_files
        entry = loaded.indexed_files[str(transcript_file)]
        assert entry.size == os.stat(transcript_file).st_size

    def test_prune_missing_persists_and_returns_removed(
        self, store: IndexStateStore, transcript_file: Path, tmp_path: Path
    ) -> None:
        """store.prune_missing() removes deleted files and persists."""
        gone = tmp_path / "gone.jsonl"

        # Seed state with one existing + one missing file
        state = IndexState()
        state.mark_indexed(transcript_file)
        state.indexed_files[str(gone)] = IndexedFileEntry(mtime=1.0, size=100, indexed_at="t")
        store.write(state)

        removed = store.prune_missing()
        assert str(gone) in removed
        assert str(transcript_file) not in removed

        # Verify persisted
        loaded = store.read()
        assert str(gone) not in loaded.indexed_files
        assert str(transcript_file) in loaded.indexed_files

    def test_find_missing_returns_orphans_without_mutating(
        self, store: IndexStateStore, transcript_file: Path, tmp_path: Path
    ) -> None:
        """store.find_missing() reports deleted files without persisting any change."""
        gone = tmp_path / "gone.jsonl"
        state = IndexState()
        state.mark_indexed(transcript_file)
        state.indexed_files[str(gone)] = IndexedFileEntry(mtime=1.0, size=100, indexed_at="t")
        store.write(state)

        missing = store.find_missing()
        assert str(gone) in missing
        assert str(transcript_file) not in missing

        # Nothing removed: the missing entry is still present on disk
        loaded = store.read()
        assert str(gone) in loaded.indexed_files
        assert str(transcript_file) in loaded.indexed_files
