"""Tests for BM25IndexStore — persistent BM25 index.

Tests cover:
- Read/write roundtrips and self-healing
- Upsert idempotency (critical for work queue retry safety)
- Incremental add/remove correctness
- Schema and tokenizer ID validation
- Corrupted file handling
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.core.state import SchemaVersionError
from forge.search.bm25_store import (
    BM25_INDEX_VERSION,
    TOKENIZER_ID,
    BM25IndexData,
    BM25IndexStore,
)
from forge.search.engine import BM25
from forge.search.exceptions import BM25IndexCorruptedError
from forge.search.tokenizer import tokenize


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "search-index" / "bm25_index.json"


@pytest.fixture
def store(store_path: Path) -> BM25IndexStore:
    return BM25IndexStore(store_path=store_path)


def _term_freq(tokens: list[str]) -> dict[str, int]:
    """Compute term frequency dict from token list."""
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class TestBM25IndexStoreRead:
    def test_missing_file_returns_none(self, store: BM25IndexStore) -> None:
        assert store.read() is None

    def test_valid_roundtrip(self, store: BM25IndexStore) -> None:
        data = BM25IndexData(
            doc_keys=["doc1", "doc2"],
            doc_lens=[10, 20],
            term_freqs=[{"hello": 2, "world": 1}, {"foo": 3}],
            doc_freqs={"hello": 1, "world": 1, "foo": 1},
            avgdl=15.0,
        )
        store.write(data)
        loaded = store.read()
        assert loaded is not None
        assert loaded.doc_keys == data.doc_keys
        assert loaded.doc_lens == data.doc_lens
        assert loaded.term_freqs == data.term_freqs
        assert loaded.doc_freqs == data.doc_freqs
        assert loaded.avgdl == data.avgdl
        assert loaded.k1 == 1.5
        assert loaded.b == 0.75

    def test_corrupted_json_raises(self, store_path: Path) -> None:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text("not valid json{{{")
        store = BM25IndexStore(store_path=store_path)
        with pytest.raises(BM25IndexCorruptedError):
            store.read()

    def test_wrong_schema_version_raises(self, store_path: Path) -> None:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps({"schema_version": 999}))
        store = BM25IndexStore(store_path=store_path)
        with pytest.raises(SchemaVersionError):
            store.read()

    def test_missing_schema_version_raises(self, store_path: Path) -> None:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps({"doc_keys": []}))
        store = BM25IndexStore(store_path=store_path)
        with pytest.raises(BM25IndexCorruptedError):
            store.read()

    def test_positional_array_mismatch_raises(self, store_path: Path) -> None:
        """Misaligned doc_keys/doc_lens/term_freqs raises BM25IndexCorruptedError."""
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "schema_version": BM25_INDEX_VERSION,
                    "tokenizer_id": TOKENIZER_ID,
                    "doc_keys": ["a", "b"],
                    "doc_lens": [10],  # only 1 entry — misaligned
                    "term_freqs": [{"x": 1}, {"y": 1}],
                    "doc_freqs": {"x": 1, "y": 1},
                    "avgdl": 10.0,
                }
            )
        )
        store = BM25IndexStore(store_path=store_path)
        with pytest.raises(BM25IndexCorruptedError, match="positional array length mismatch"):
            store.read()

    def test_tokenizer_mismatch_raises(self, store_path: Path) -> None:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "schema_version": BM25_INDEX_VERSION,
                    "tokenizer_id": "v0_old",
                    "doc_keys": [],
                    "doc_lens": [],
                    "term_freqs": [],
                    "doc_freqs": {},
                    "avgdl": 0.0,
                }
            )
        )
        store = BM25IndexStore(store_path=store_path)
        with pytest.raises(BM25IndexCorruptedError, match="tokenizer mismatch"):
            store.read()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


class TestBM25IndexStoreWrite:
    def test_creates_parent_directories(self, store: BM25IndexStore) -> None:
        store.write(BM25IndexData())
        assert store.store_path.is_file()

    def test_includes_schema_version(self, store: BM25IndexStore) -> None:
        store.write(BM25IndexData())
        data = json.loads(store.store_path.read_text())
        assert data["schema_version"] == BM25_INDEX_VERSION

    def test_includes_tokenizer_id(self, store: BM25IndexStore) -> None:
        store.write(BM25IndexData())
        data = json.loads(store.store_path.read_text())
        assert data["tokenizer_id"] == TOKENIZER_ID

    def test_includes_updated_at(self, store: BM25IndexStore) -> None:
        store.write(BM25IndexData())
        data = json.loads(store.store_path.read_text())
        assert "updated_at" in data


# ---------------------------------------------------------------------------
# Upsert (idempotency is critical for work queue retries)
# ---------------------------------------------------------------------------


class TestBM25IndexStoreUpsert:
    def test_add_to_empty_index(self, store: BM25IndexStore) -> None:
        tf = {"hello": 2, "world": 1}
        store.upsert_document("doc1", tf, 3)
        data = store.read()
        assert data is not None
        assert data.doc_keys == ["doc1"]
        assert data.doc_lens == [3]
        assert data.term_freqs == [tf]
        assert data.doc_freqs == {"hello": 1, "world": 1}
        assert data.avgdl == 3.0

    def test_add_second_document(self, store: BM25IndexStore) -> None:
        store.upsert_document("doc1", {"hello": 1}, 1)
        store.upsert_document("doc2", {"hello": 1, "foo": 2}, 3)
        data = store.read()
        assert data is not None
        assert data.doc_keys == ["doc1", "doc2"]
        assert data.doc_freqs == {"hello": 2, "foo": 1}
        assert data.avgdl == 2.0

    def test_upsert_same_content_is_idempotent(self, store: BM25IndexStore) -> None:
        """Upserting the same doc twice produces identical state to single upsert."""
        tf = {"hello": 2, "world": 1}

        # First upsert
        store.upsert_document("doc1", tf, 3)
        after_first = store.read()

        # Second upsert (same content)
        store.upsert_document("doc1", tf, 3)
        after_second = store.read()

        assert after_second is not None
        assert after_first is not None
        assert after_second.doc_keys == after_first.doc_keys
        assert after_second.doc_lens == after_first.doc_lens
        assert after_second.term_freqs == after_first.term_freqs
        assert after_second.doc_freqs == after_first.doc_freqs
        assert after_second.avgdl == after_first.avgdl

    def test_upsert_changed_content_updates_correctly(self, store: BM25IndexStore) -> None:
        """Upserting with new content removes old term_freqs and applies new."""
        store.upsert_document("doc1", {"hello": 1, "world": 1}, 2)
        store.upsert_document("doc2", {"hello": 1, "foo": 1}, 2)

        # doc1 changes content: "hello world" -> "foo bar"
        store.upsert_document("doc1", {"foo": 1, "bar": 1}, 2)

        data = store.read()
        assert data is not None
        assert len(data.doc_keys) == 2
        # hello was in doc1 (removed) and doc2 -> now only in doc2
        assert data.doc_freqs.get("hello") == 1
        # world was only in old doc1 -> gone
        assert "world" not in data.doc_freqs
        # foo is in doc2 and new doc1
        assert data.doc_freqs.get("foo") == 2
        # bar is only in new doc1
        assert data.doc_freqs.get("bar") == 1

    def test_upsert_idempotency_preserves_scores(self, store: BM25IndexStore) -> None:
        """Double-indexing produces identical BM25 scores to single indexing."""
        tokens_a = tokenize("python programming language fast")
        tokens_b = tokenize("java virtual machine enterprise")
        tf_a = _term_freq(tokens_a)
        tf_b = _term_freq(tokens_b)

        # Single add each
        store.upsert_document("a", tf_a, len(tokens_a))
        store.upsert_document("b", tf_b, len(tokens_b))
        data_single = store.read()

        # Double-add doc a (simulating retry)
        store.upsert_document("a", tf_a, len(tokens_a))
        data_double = store.read()

        assert data_single is not None
        assert data_double is not None

        # Compare scores by doc key (not position — upsert reorders)
        def _scores_by_key(data: BM25IndexData, query_tokens: list[str]) -> dict[str, float]:
            bm25 = BM25.from_precomputed(
                term_freqs=data.term_freqs,
                doc_freqs=data.doc_freqs,
                doc_lens=data.doc_lens,
                avgdl=data.avgdl,
            )
            scores = bm25.score(query_tokens)
            return {k: s for k, s in zip(data.doc_keys, scores)}

        query = tokenize("python")
        scores_single = _scores_by_key(data_single, query)
        scores_double = _scores_by_key(data_double, query)
        assert scores_single == pytest.approx(scores_double)


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


class TestBM25IndexStoreRemove:
    def test_remove_existing(self, store: BM25IndexStore) -> None:
        store.upsert_document("doc1", {"a": 1}, 1)
        store.upsert_document("doc2", {"b": 1}, 1)
        assert store.remove_document("doc1") is True
        data = store.read()
        assert data is not None
        assert data.doc_keys == ["doc2"]
        assert "a" not in data.doc_freqs

    def test_remove_nonexistent_returns_false(self, store: BM25IndexStore) -> None:
        store.upsert_document("doc1", {"a": 1}, 1)
        assert store.remove_document("doc_missing") is False

    def test_remove_from_empty_returns_false(self, store: BM25IndexStore) -> None:
        assert store.remove_document("anything") is False

    def test_remove_decrements_doc_freqs_correctly(self, store: BM25IndexStore) -> None:
        store.upsert_document("doc1", {"shared": 1, "unique1": 1}, 2)
        store.upsert_document("doc2", {"shared": 1, "unique2": 1}, 2)
        store.remove_document("doc1")
        data = store.read()
        assert data is not None
        assert data.doc_freqs.get("shared") == 1  # decremented, not deleted
        assert "unique1" not in data.doc_freqs  # was only in doc1
        assert data.doc_freqs.get("unique2") == 1

    def test_remove_recalculates_avgdl(self, store: BM25IndexStore) -> None:
        store.upsert_document("doc1", {"a": 1}, 10)
        store.upsert_document("doc2", {"b": 1}, 20)
        store.remove_document("doc1")
        data = store.read()
        assert data is not None
        assert data.avgdl == 20.0


# ---------------------------------------------------------------------------
# Replace all
# ---------------------------------------------------------------------------


class TestBM25IndexStoreReplaceAll:
    def test_replace_all_overwrites(self, store: BM25IndexStore) -> None:
        store.upsert_document("old", {"a": 1}, 1)
        new_data = BM25IndexData(
            doc_keys=["new1", "new2"],
            doc_lens=[5, 10],
            term_freqs=[{"x": 1}, {"y": 2}],
            doc_freqs={"x": 1, "y": 1},
            avgdl=7.5,
        )
        store.replace_all(new_data)
        loaded = store.read()
        assert loaded is not None
        assert loaded.doc_keys == ["new1", "new2"]


# ---------------------------------------------------------------------------
# Incremental vs bulk correctness
# ---------------------------------------------------------------------------


class TestIncrementalCorrectness:
    def test_incremental_matches_bulk(self, store: BM25IndexStore) -> None:
        """Documents added one-by-one produce identical BM25 scores as bulk construction."""
        doc_texts = [
            "python programming language fast efficient",
            "java virtual machine enterprise applications",
            "rust memory safety systems programming",
        ]
        all_tokens = [tokenize(t) for t in doc_texts]

        # Bulk: build BM25 directly from all token lists
        bm25_bulk = BM25(all_tokens)

        # Incremental: add one at a time via store
        for i, tokens in enumerate(all_tokens):
            store.upsert_document(f"doc_{i}", _term_freq(tokens), len(tokens))

        data = store.read()
        assert data is not None
        bm25_incremental = BM25.from_precomputed(
            term_freqs=data.term_freqs,
            doc_freqs=data.doc_freqs,
            doc_lens=data.doc_lens,
            avgdl=data.avgdl,
        )

        for query_text in ["python", "enterprise", "memory safety"]:
            query = tokenize(query_text)
            bulk_scores = bm25_bulk.score(query)
            incr_scores = bm25_incremental.score(query)
            assert bulk_scores == pytest.approx(incr_scores), f"Scores differ for query: {query_text}"
