"""Forge search infrastructure for transcript indexing and search.

Provides:
- search_from_index(): BM25 search using persistent precomputed index
- extract_document() / decompose_document(): Content extraction and decomposition
- BM25IndexStore / ContentStore / SearchDocumentStore: Per-project persistence
- tokenize(): Shared tokenizer for BM25 indexing and querying
"""

from .bm25_store import BM25IndexData, BM25IndexStore
from .content_store import ContentStore
from .engine import SearchResult, search_from_index
from .exceptions import (
    BM25IndexCorruptedError,
    BM25IndexUnreadableError,
    ContentStoreCorruptedError,
    ContentStoreUnreadableError,
    IndexStateCorruptedError,
    IndexStateUnreadableError,
    SearchDocumentStoreCorruptedError,
    SearchDocumentStoreUnreadableError,
    SearchError,
)
from .extractor import (
    SearchDocument,
    SearchDocumentMeta,
    decompose_document,
    extract_document,
)
from .index_state import IndexState, IndexStateStore
from .store import SearchDocumentStore
from .tokenizer import tokenize

__all__ = [
    # Core API
    "search_from_index",
    "extract_document",
    "decompose_document",
    "tokenize",
    # Types
    "SearchResult",
    "SearchDocument",
    "SearchDocumentMeta",
    "BM25IndexData",
    # Stores
    "SearchDocumentStore",
    "BM25IndexStore",
    "ContentStore",
    "IndexStateStore",
    "IndexState",
    # Exceptions
    "SearchError",
    "IndexStateCorruptedError",
    "IndexStateUnreadableError",
    "SearchDocumentStoreCorruptedError",
    "SearchDocumentStoreUnreadableError",
    "BM25IndexCorruptedError",
    "BM25IndexUnreadableError",
    "ContentStoreCorruptedError",
    "ContentStoreUnreadableError",
]
