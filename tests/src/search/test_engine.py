"""Tests for the BM25 search engine."""

from __future__ import annotations

import pytest

from forge.search.engine import BM25, SNIPPET_LENGTH, search, search_from_index
from forge.search.exceptions import BM25IndexCorruptedError, ContentStoreCorruptedError
from forge.search.extractor import SearchDocument, SearchDocumentMeta
from forge.search.tokenizer import tokenize


def _make_doc(
    content: str,
    *,
    session_name: str = "session",
    session_id: str = "uuid",
    transcript_path: str = "/tmp/test.jsonl",
) -> SearchDocument:
    """Create a minimal SearchDocument for testing."""
    return SearchDocument(
        transcript_path=transcript_path,
        session_name=session_name,
        session_id=session_id,
        content=content,
        extracted_at="2026-01-01T00:00:00+00:00",
        metadata={"message_count": 1},
    )


class TestTokenize:
    """Tests for the tokenizer."""

    def test_lowercase(self) -> None:
        assert tokenize("Hello World") == ["hello", "world"]

    def test_strips_punctuation(self) -> None:
        result = tokenize("file.py, class!")
        assert "file" in result
        assert "py" in result
        assert "class" in result

    def test_filters_short_tokens(self) -> None:
        result = tokenize("I am a test")
        assert "am" in result
        assert "test" in result
        assert "I" not in result and "i" not in result
        assert "a" not in result

    def test_empty_string(self) -> None:
        assert tokenize("") == []

    def test_underscores_preserved(self) -> None:
        result = tokenize("my_variable = some_function()")
        assert "my_variable" in result
        assert "some_function" in result


class TestBM25:
    """Tests for the BM25 implementation."""

    def test_single_doc_matching_term(self) -> None:
        """Document containing query term scores > 0."""
        bm25 = BM25([["hello", "world"]])
        scores = bm25.score(["hello"])
        assert scores[0] > 0

    def test_multiple_docs_ranking(self) -> None:
        """Document with more relevant terms scores higher."""
        docs = [
            ["python", "java", "rust"],  # doc 0: no match
            ["python", "timeout", "config"],  # doc 1: one match
            ["timeout", "timeout", "config", "setting"],  # doc 2: two matches
        ]
        bm25 = BM25(docs)
        scores = bm25.score(["timeout"])
        assert scores[2] > scores[1]
        assert scores[0] == 0.0

    def test_term_not_in_corpus(self) -> None:
        """Query term not in any document produces zero scores."""
        bm25 = BM25([["hello", "world"]])
        scores = bm25.score(["nonexistent"])
        assert all(s == 0.0 for s in scores)

    def test_empty_corpus(self) -> None:
        """Empty corpus returns empty scores list."""
        bm25 = BM25([])
        scores = bm25.score(["hello"])
        assert scores == []

    def test_idf_weighting(self) -> None:
        """Rare terms score higher than common terms."""
        # "common" appears in both docs, "rare" only in doc 1
        docs = [
            ["common", "other"],
            ["common", "rare"],
        ]
        bm25 = BM25(docs)
        # Score doc 1 for "rare" vs "common"
        rare_scores = bm25.score(["rare"])
        common_scores = bm25.score(["common"])
        # "rare" should give doc 1 a higher score than "common" does
        assert rare_scores[1] > common_scores[1]


class TestBM25Precomputed:
    """Tests for from_precomputed/to_precomputed persistence support."""

    def test_roundtrip_preserves_scores(self) -> None:
        """Build → export → reconstruct produces identical scores."""
        docs = [
            ["python", "programming", "language"],
            ["java", "virtual", "machine"],
            ["python", "fast", "efficient"],
        ]
        original = BM25(docs)
        exported = original.to_precomputed()
        restored = BM25.from_precomputed(**exported)

        for query_text in ["python", "machine", "programming language"]:
            query = tokenize(query_text)
            assert original.score(query) == pytest.approx(restored.score(query))

    def test_to_precomputed_structure(self) -> None:
        """to_precomputed returns expected keys."""
        bm25 = BM25([["hello", "world"]])
        data = bm25.to_precomputed()
        assert set(data.keys()) == {
            "term_freqs",
            "doc_freqs",
            "doc_lens",
            "avgdl",
            "k1",
            "b",
        }
        assert data["doc_lens"] == [2]
        assert data["avgdl"] == 2.0
        assert data["k1"] == 1.5
        assert data["b"] == 0.75

    def test_from_precomputed_empty(self) -> None:
        """from_precomputed handles empty corpus."""
        bm25 = BM25.from_precomputed(term_freqs=[], doc_freqs={}, doc_lens=[], avgdl=0.0)
        assert bm25.score(["hello"]) == []

    def test_from_precomputed_doc_freqs(self) -> None:
        """from_precomputed correctly sets doc_freqs."""
        bm25 = BM25.from_precomputed(
            term_freqs=[{"a": 1, "b": 2}, {"b": 1, "c": 3}],
            doc_freqs={"a": 1, "b": 2, "c": 1},
            doc_lens=[3, 4],
            avgdl=3.5,
        )
        assert bm25.doc_freqs == {"a": 1, "b": 2, "c": 1}

    def test_custom_k1_b_preserved(self) -> None:
        """Custom k1/b values survive roundtrip."""
        original = BM25([["a", "b"]], k1=2.0, b=0.5)
        exported = original.to_precomputed()
        assert exported["k1"] == 2.0
        assert exported["b"] == 0.5
        restored = BM25.from_precomputed(**exported)
        assert original.score(["a"]) == pytest.approx(restored.score(["a"]))


class TestSearch:
    """Tests for the top-level search function."""

    def test_returns_sorted_by_score(self) -> None:
        """Results are sorted by score descending."""
        docs = [
            _make_doc("python java rust", session_name="low"),
            _make_doc("timeout timeout timeout config", session_name="high"),
            _make_doc("timeout config setting", session_name="medium"),
        ]
        results = search("timeout", docs)
        assert len(results) >= 2
        assert results[0].score >= results[1].score

    def test_respects_limit(self) -> None:
        """Results are capped at the limit."""
        docs = [_make_doc(f"keyword match document {i}", session_id=f"id-{i}") for i in range(20)]
        results = search("keyword", docs, limit=3)
        assert len(results) <= 3

    def test_empty_query(self) -> None:
        """Empty query returns empty results."""
        docs = [_make_doc("some content")]
        assert search("", docs) == []
        assert search("   ", docs) == []

    def test_empty_documents(self) -> None:
        """Empty document list returns empty results."""
        assert search("hello", []) == []

    def test_snippet_truncation(self) -> None:
        """Snippet is truncated to approximately SNIPPET_LENGTH."""
        long_content = "keyword " * 200
        docs = [_make_doc(long_content)]
        results = search("keyword", docs)
        assert len(results) == 1
        # Snippet may include "..." markers, but the core window is <= SNIPPET_LENGTH
        assert len(results[0].snippet) <= SNIPPET_LENGTH + 6  # "..." + "..."

    def test_snippet_centers_on_match(self) -> None:
        """Snippet centers on the query term, not the document start."""
        # Put filler at the start, query term deep in the document
        filler = "unrelated filler content here " * 100  # ~3000 chars
        target = "the authentication middleware was added successfully"
        content = filler + target + " " + filler
        docs = [_make_doc(content)]
        results = search("authentication", docs)
        assert len(results) == 1
        assert "authentication" in results[0].snippet
        # Should NOT just be the first 300 chars (filler)
        assert "unrelated filler content" not in results[0].snippet[:50]

    def test_snippet_adds_ellipsis(self) -> None:
        """Snippet from middle of doc has ellipsis markers."""
        filler = "padding words here " * 100
        content = filler + "target keyword here" + filler
        docs = [_make_doc(content)]
        results = search("target", docs)
        assert len(results) == 1
        assert results[0].snippet.startswith("...")
        assert results[0].snippet.endswith("...")

    def test_snippet_anchors_on_rarest_term(self) -> None:
        """Snippet centers on the rarest query term, not the first common one."""
        # "the" appears everywhere, "authentication" only in one place deep in the doc
        common_filler = "the system is running the tests for the project " * 50
        rare_section = "implement authentication middleware for JWT tokens"
        content = common_filler + rare_section + " " + common_filler
        # Two docs so "the" has high doc_freq while "authentication" has low doc_freq
        docs = [
            _make_doc(content, session_name="target", session_id="s1"),
            _make_doc(
                "the system is running the tests" * 20,
                session_name="other",
                session_id="s2",
            ),
        ]
        results = search("the authentication", docs)
        target_results = [r for r in results if r.session_name == "target"]
        assert len(target_results) == 1
        # Snippet should center on "authentication" (rare), not "the" (common)
        assert "authentication" in target_results[0].snippet

    def test_snippet_anchors_on_mixed_case_tokens(self) -> None:
        """Snippet anchoring works when content has mixed-case tokens (e.g. tool names).

        Regression: _TOKEN_RE used [a-z0-9_]+ which split uppercase letters in raw
        content ("ReadFile" -> ["ead","ile"]), so query tokens never matched and
        snippets fell back to document start.
        """
        filler = "unrelated padding content here " * 100
        # Mixed-case tool names, as produced by the extractor
        target = "Read(path=/workspace/config.yaml) Edit(path=/workspace/main.py)"
        content = filler + target + " " + filler
        docs = [_make_doc(content)]
        results = search("readfile", docs)
        # "readfile" won't match (it's "Read" and "path" as separate tokens)
        # but searching for "read" should anchor on the capitalized "Read"
        results = search("read", docs)
        assert len(results) == 1
        assert "Read(path=" in results[0].snippet

    def test_snippet_short_content_returned_whole(self) -> None:
        """Content shorter than SNIPPET_LENGTH returned as-is."""
        short = "brief keyword mention"
        docs = [_make_doc(short)]
        results = search("keyword", docs)
        assert len(results) == 1
        assert results[0].snippet == short

    def test_search_with_sample_documents(self) -> None:
        """End-to-end: create documents, search, verify ranking."""
        docs = [
            _make_doc(
                "[user] Please update the database timeout to 30 seconds",
                session_name="db-config",
                session_id="s1",
            ),
            _make_doc(
                "[user] Add authentication middleware to the API",
                session_name="auth-feature",
                session_id="s2",
            ),
            _make_doc(
                "[user] Fix the timeout bug in connection pooling",
                session_name="pool-fix",
                session_id="s3",
            ),
        ]
        results = search("timeout", docs)
        session_names = [r.session_name for r in results]
        # Both sessions mentioning "timeout" should be in results
        assert "db-config" in session_names
        assert "pool-fix" in session_names
        # Auth session should not appear (no "timeout")
        assert "auth-feature" not in session_names

    def test_result_contains_metadata(self) -> None:
        """SearchResult includes metadata from the source document."""
        docs = [_make_doc("keyword match", session_name="my-session", session_id="my-id")]
        results = search("keyword", docs)
        assert len(results) == 1
        assert results[0].session_name == "my-session"
        assert results[0].session_id == "my-id"
        assert isinstance(results[0].metadata, dict)


# ---------------------------------------------------------------------------
# Helpers for search_from_index tests
# ---------------------------------------------------------------------------


def _make_meta(
    transcript_path: str = "/tmp/test.jsonl",
    session_name: str = "session",
    session_id: str = "uuid",
) -> SearchDocumentMeta:
    return SearchDocumentMeta(
        transcript_path=transcript_path,
        session_name=session_name,
        session_id=session_id,
        extracted_at="2026-01-01T00:00:00+00:00",
        metadata={"message_count": 1},
    )


def _build_index_data(
    texts: list[str], keys: list[str] | None = None
) -> tuple[list[str], list[dict[str, int]], dict[str, int], list[int], float]:
    """Build BM25 index components from text strings."""
    if keys is None:
        keys = [f"/tmp/doc_{i}.jsonl" for i in range(len(texts))]
    all_tokens = [tokenize(t) for t in texts]
    term_freqs = []
    doc_freqs: dict[str, int] = {}
    doc_lens = []
    for tokens in all_tokens:
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        term_freqs.append(tf)
        doc_lens.append(len(tokens))
        for term in tf:
            doc_freqs[term] = doc_freqs.get(term, 0) + 1
    avgdl = sum(doc_lens) / max(len(doc_lens), 1)
    return keys, term_freqs, doc_freqs, doc_lens, avgdl


class TestSearchFromIndex:
    """Tests for search_from_index() — the persistent index search path."""

    def test_basic_search(self) -> None:
        """Basic search returns ranked results."""
        texts = [
            "python programming language",
            "java virtual machine enterprise",
            "python fast efficient scripting",
        ]
        keys, term_freqs, doc_freqs, doc_lens, avgdl = _build_index_data(texts)
        meta_map = {k: _make_meta(k, session_name=f"s{i}") for i, k in enumerate(keys)}
        content_map = dict(zip(keys, texts))

        results = search_from_index(
            "python",
            doc_keys=keys,
            term_freqs=term_freqs,
            doc_freqs=doc_freqs,
            doc_lens=doc_lens,
            avgdl=avgdl,
            content_loader=lambda ks: {k: content_map[k] for k in ks},
            doc_metadata=meta_map,
        )
        assert len(results) == 2
        assert results[0].score >= results[1].score
        session_names = {r.session_name for r in results}
        assert "s0" in session_names  # "python programming language"
        assert "s2" in session_names  # "python fast efficient scripting"

    def test_empty_query(self) -> None:
        keys, term_freqs, doc_freqs, doc_lens, avgdl = _build_index_data(["hello"])
        results = search_from_index(
            "",
            doc_keys=keys,
            term_freqs=term_freqs,
            doc_freqs=doc_freqs,
            doc_lens=doc_lens,
            avgdl=avgdl,
            content_loader=lambda ks: {},
            doc_metadata={},
        )
        assert results == []

    def test_empty_index(self) -> None:
        results = search_from_index(
            "hello",
            doc_keys=[],
            term_freqs=[],
            doc_freqs={},
            doc_lens=[],
            avgdl=0.0,
            content_loader=lambda ks: {},
            doc_metadata={},
        )
        assert results == []

    def test_content_loader_called_with_top_k_only(self) -> None:
        """content_loader receives only the top-K keys, not all documents."""
        texts = [f"unique_{i} common term" for i in range(20)]
        keys, term_freqs, doc_freqs, doc_lens, avgdl = _build_index_data(texts)
        meta_map = {k: _make_meta(k) for k in keys}
        content_map = dict(zip(keys, texts))

        loaded_keys: list[str] = []

        def tracking_loader(ks: list[str]) -> dict[str, str]:
            loaded_keys.extend(ks)
            return {k: content_map[k] for k in ks}

        results = search_from_index(
            "common",
            doc_keys=keys,
            term_freqs=term_freqs,
            doc_freqs=doc_freqs,
            doc_lens=doc_lens,
            avgdl=avgdl,
            content_loader=tracking_loader,
            doc_metadata=meta_map,
            limit=5,
        )
        assert len(loaded_keys) <= 5
        assert len(results) <= 5

    def test_missing_metadata_raises_corrupted(self) -> None:
        """Mismatched doc_keys vs metadata raises BM25IndexCorruptedError."""
        keys, term_freqs, doc_freqs, doc_lens, avgdl = _build_index_data(["hello world"])
        # Empty metadata — keys not found
        with pytest.raises(BM25IndexCorruptedError, match="missing from metadata"):
            search_from_index(
                "hello",
                doc_keys=keys,
                term_freqs=term_freqs,
                doc_freqs=doc_freqs,
                doc_lens=doc_lens,
                avgdl=avgdl,
                content_loader=lambda ks: {},
                doc_metadata={},
            )

    def test_missing_content_raises_corrupted(self) -> None:
        """Missing content for top-K result raises ContentStoreCorruptedError."""
        keys, term_freqs, doc_freqs, doc_lens, avgdl = _build_index_data(["hello world"])
        meta_map = {k: _make_meta(k) for k in keys}

        with pytest.raises(ContentStoreCorruptedError, match="missing from content"):
            search_from_index(
                "hello",
                doc_keys=keys,
                term_freqs=term_freqs,
                doc_freqs=doc_freqs,
                doc_lens=doc_lens,
                avgdl=avgdl,
                content_loader=lambda ks: {},  # returns nothing
                doc_metadata=meta_map,
            )

    def test_respects_limit(self) -> None:
        texts = [f"keyword match doc {i}" for i in range(20)]
        keys, term_freqs, doc_freqs, doc_lens, avgdl = _build_index_data(texts)
        meta_map = {k: _make_meta(k) for k in keys}
        content_map = dict(zip(keys, texts))

        results = search_from_index(
            "keyword",
            doc_keys=keys,
            term_freqs=term_freqs,
            doc_freqs=doc_freqs,
            doc_lens=doc_lens,
            avgdl=avgdl,
            content_loader=lambda ks: {k: content_map[k] for k in ks},
            doc_metadata=meta_map,
            limit=3,
        )
        assert len(results) <= 3

    def test_snippet_from_content(self) -> None:
        """Snippets are extracted from content loaded via content_loader."""
        text = "authentication middleware jwt tokens validation"
        keys, term_freqs, doc_freqs, doc_lens, avgdl = _build_index_data([text])
        meta_map = {keys[0]: _make_meta(keys[0])}

        results = search_from_index(
            "authentication",
            doc_keys=keys,
            term_freqs=term_freqs,
            doc_freqs=doc_freqs,
            doc_lens=doc_lens,
            avgdl=avgdl,
            content_loader=lambda ks: {keys[0]: text},
            doc_metadata=meta_map,
        )
        assert len(results) == 1
        assert "authentication" in results[0].snippet

    def test_scores_match_legacy_search(self) -> None:
        """search_from_index produces same scores as legacy search() for identical data."""
        texts = [
            "python programming fast",
            "java enterprise system",
            "python scripting automation",
        ]
        # Build legacy search
        docs = [
            _make_doc(
                t,
                session_name=f"s{i}",
                session_id=f"id{i}",
                transcript_path=f"/tmp/d{i}.jsonl",
            )
            for i, t in enumerate(texts)
        ]
        legacy_results = search("python", docs)

        # Build index search
        keys = [f"/tmp/d{i}.jsonl" for i in range(len(texts))]
        keys_data, term_freqs, doc_freqs, doc_lens, avgdl = _build_index_data(texts, keys)
        meta_map = {k: _make_meta(k, session_name=f"s{i}", session_id=f"id{i}") for i, k in enumerate(keys_data)}
        content_map = dict(zip(keys_data, texts))

        index_results = search_from_index(
            "python",
            doc_keys=keys_data,
            term_freqs=term_freqs,
            doc_freqs=doc_freqs,
            doc_lens=doc_lens,
            avgdl=avgdl,
            content_loader=lambda ks: {k: content_map[k] for k in ks},
            doc_metadata=meta_map,
        )

        # Same number of results with same scores
        assert len(legacy_results) == len(index_results)
        for lr, ir in zip(legacy_results, index_results):
            assert lr.score == ir.score
            assert lr.session_name == ir.session_name
