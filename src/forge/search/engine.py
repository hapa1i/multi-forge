"""BM25 search engine for transcript documents.

Provides BM25Okapi ranking for keyword search over extracted transcript content.
No external dependencies — hand-rolled BM25 implementation (~30 lines of math).

Search entry point:
- search_from_index(): Persistent index path — loads precomputed BM25 data (scoring only)
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .exceptions import BM25IndexCorruptedError, ContentStoreCorruptedError
from .extractor import SearchDocumentMeta
from .tokenizer import TOKEN_RE, tokenize

# Search defaults
SNIPPET_LENGTH = 300
DEFAULT_LIMIT = 10


class BM25:
    """BM25Okapi implementation for ranking documents against a query.

    Standard BM25 with term frequency saturation and document length
    normalization. No external dependencies.

    Args:
        documents: List of tokenized documents (each is a list of terms).
        k1: Term frequency saturation parameter.
        b: Document length normalization parameter.
    """

    def __init__(
        self,
        documents: list[list[str]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self._k1 = k1
        self._b = b
        self._doc_count = len(documents)
        self._doc_lens = [len(d) for d in documents]
        self._avgdl = sum(self._doc_lens) / max(self._doc_count, 1)

        # Per-doc term frequencies
        self._term_freqs: list[dict[str, int]] = []
        # Number of docs containing each term
        self._doc_freqs: dict[str, int] = {}

        for doc in documents:
            tf: dict[str, int] = {}
            for term in doc:
                tf[term] = tf.get(term, 0) + 1
            self._term_freqs.append(tf)
            for term in tf:
                self._doc_freqs[term] = self._doc_freqs.get(term, 0) + 1

    @property
    def doc_freqs(self) -> dict[str, int]:
        """Number of documents containing each term."""
        return self._doc_freqs

    @classmethod
    def from_precomputed(
        cls,
        *,
        term_freqs: list[dict[str, int]],
        doc_freqs: dict[str, int],
        doc_lens: list[int],
        avgdl: float,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> BM25:
        """Construct BM25 from pre-computed index data (no tokenization).

        This is the fast path for persistent indices — skips the O(total_tokens)
        initialization and directly sets internal state.
        """
        instance = cls.__new__(cls)
        instance._k1 = k1
        instance._b = b
        instance._doc_count = len(doc_lens)
        instance._doc_lens = doc_lens
        instance._avgdl = avgdl
        instance._term_freqs = term_freqs
        instance._doc_freqs = doc_freqs
        return instance

    def to_precomputed(self) -> dict:
        """Export pre-computed data for persistence.

        Returns dict with keys: term_freqs, doc_freqs, doc_lens, avgdl, k1, b.
        """
        return {
            "term_freqs": self._term_freqs,
            "doc_freqs": dict(self._doc_freqs),
            "doc_lens": list(self._doc_lens),
            "avgdl": self._avgdl,
            "k1": self._k1,
            "b": self._b,
        }

    def score(self, query: list[str]) -> list[float]:
        """Score all documents against the given query terms.

        Returns list of scores in the same order as documents passed to __init__.
        """
        scores = [0.0] * self._doc_count
        for term in query:
            if term not in self._doc_freqs:
                continue
            df = self._doc_freqs[term]
            idf = math.log((self._doc_count - df + 0.5) / (df + 0.5) + 1.0)
            for i in range(self._doc_count):
                tf = self._term_freqs[i].get(term, 0)
                if tf == 0:
                    continue
                dl = self._doc_lens[i]
                tf_norm = (tf * (self._k1 + 1)) / (tf + self._k1 * (1 - self._b + self._b * dl / self._avgdl))
                scores[i] += idf * tf_norm
        return scores


def _best_snippet(
    content: str,
    query_tokens: list[str],
    length: int = SNIPPET_LENGTH,
    *,
    doc_freqs: dict[str, int] | None = None,
) -> str:
    """Extract a snippet centered on the rarest query term's first occurrence.

    Scans the content for all query token matches in a single O(n) pass,
    preferring the first occurrence of the rarest term (lowest doc_freqs
    count). This anchors snippets on the most distinctive query term rather
    than the first match of any term.

    Iterates on the original content (not lowercased) to preserve correct
    character positions for Unicode text where lowercasing can change length.

    Falls back to the first `length` characters if no query terms are found.
    """
    if len(content) <= length:
        return content

    query_set = set(query_tokens)

    # Single pass: find first occurrence of the rarest query term
    best_pos: int | None = None
    best_rarity = float("inf")

    for match in TOKEN_RE.finditer(content):
        token = match.group().lower()
        if token not in query_set:
            continue
        rarity = doc_freqs.get(token, 0) if doc_freqs else 0
        if rarity < best_rarity:
            best_pos = match.start()
            best_rarity = rarity
            if rarity <= 1:
                break  # Term appears in ≤1 doc — can't get rarer

    if best_pos is not None:
        return _extract_window(content, best_pos, length)

    # No query terms found — fall back to beginning
    return content[:length]


def _extract_window(content: str, center: int, length: int) -> str:
    """Extract a snippet window centered on a character position."""
    start = max(0, center - length // 2)
    end = start + length
    if end > len(content):
        end = len(content)
        start = max(0, end - length)
    snippet = content[start:end]
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    return prefix + snippet + suffix


@dataclass
class SearchResult:
    """A single search result."""

    session_name: str
    session_id: str
    score: float
    snippet: str
    transcript_path: str
    metadata: dict[str, Any]


def search_from_index(
    query: str,
    *,
    doc_keys: list[str],
    term_freqs: list[dict[str, int]],
    doc_freqs: dict[str, int],
    doc_lens: list[int],
    avgdl: float,
    k1: float = 1.5,
    b: float = 0.75,
    content_loader: Callable[[list[str]], dict[str, str]],
    doc_metadata: dict[str, SearchDocumentMeta],
    limit: int = DEFAULT_LIMIT,
) -> list[SearchResult]:
    """Search using a pre-computed persistent BM25 index.

    This is the fast path: loads precomputed data structures, runs scoring
    only, then lazily loads content for snippet extraction on top-K results.

    Args:
        query: Search query string.
        doc_keys: Positional document keys (transcript_paths) matching term_freqs/doc_lens.
        term_freqs: Per-document term frequency dicts (positional).
        doc_freqs: Global document frequency dict.
        doc_lens: Per-document token counts (positional).
        avgdl: Average document length across corpus.
        k1: BM25 term saturation parameter.
        b: BM25 length normalization parameter.
        content_loader: Callable that takes a list of doc keys and returns {key: content}.
        doc_metadata: Mapping of transcript_path -> SearchDocumentMeta.
        limit: Maximum number of results.

    Returns:
        List of SearchResult sorted by score descending.

    Raises:
        BM25IndexCorruptedError: If doc_keys has entries not in doc_metadata.
        ContentStoreCorruptedError: If content_loader is missing a top-K key.
    """
    if not query.strip() or not doc_keys:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    # Validate invariant: every indexed doc must have metadata
    missing_meta = [k for k in doc_keys if k not in doc_metadata]
    if missing_meta:
        raise BM25IndexCorruptedError(
            "bm25_index",
            f"{len(missing_meta)} indexed documents missing from metadata store. "
            "Run 'forge search rebuild-index' to fix.",
        )

    # Score using precomputed data (no token iteration)
    bm25 = BM25.from_precomputed(
        term_freqs=term_freqs,
        doc_freqs=doc_freqs,
        doc_lens=doc_lens,
        avgdl=avgdl,
        k1=k1,
        b=b,
    )
    scores = bm25.score(query_tokens)

    # Pair scores with doc keys, filter zero scores, sort descending
    scored = [(s, key) for s, key in zip(scores, doc_keys) if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    top_k = scored[:limit]

    if not top_k:
        return []

    # Lazy content loading: only fetch content for top-K results
    top_keys = [key for _, key in top_k]
    content_map = content_loader(top_keys)

    # Validate content availability
    missing_content = [k for k in top_keys if k not in content_map]
    if missing_content:
        raise ContentStoreCorruptedError(
            "content",
            f"{len(missing_content)} top-K documents missing from content store. "
            "Run 'forge search rebuild-index' to fix.",
        )

    results: list[SearchResult] = []
    for s, key in top_k:
        meta = doc_metadata[key]
        content = content_map[key]
        results.append(
            SearchResult(
                session_name=meta.session_name,
                session_id=meta.session_id,
                score=round(s, 4),
                snippet=_best_snippet(content, query_tokens, doc_freqs=doc_freqs),
                transcript_path=meta.transcript_path,
                metadata=meta.metadata,
            )
        )
    return results
