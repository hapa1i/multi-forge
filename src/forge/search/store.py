"""Document metadata store for search-indexed transcripts (v2).

Persists SearchDocumentMeta objects (metadata only — no content, no tokens)
at <project_root>/.forge/search-index/documents.json. Content and BM25 index
data are stored in separate files (content.json, bm25_index.json).

Each project has its own store — no cross-project mixing in a single file.

Follows the IndexStateStore pattern: versioned JSON, atomic writes, file locking,
self-healing on missing file.

Uses dacite for deserialization (consistent with BackendRegistryStore).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import dacite

from forge.core.state import (
    SchemaVersionError,
    atomic_write_json,
    file_lock_for_target,
    now_iso,
)

from .exceptions import SearchDocumentStoreCorruptedError
from .extractor import SearchDocumentMeta
from .index_state import SEARCH_INDEX_DIR

logger = logging.getLogger(__name__)

# File and schema constants
DOCUMENTS_FILENAME = "documents.json"
DOCUMENT_STORE_VERSION = 1

# Lock timeouts
STORE_LOCK_TIMEOUT_S = 5.0
HANDLER_STORE_LOCK_TIMEOUT_S = 1.0


def get_project_documents_store_path(forge_root: Path) -> Path:
    """Return the document store path for a Forge project.

    Path: <forge_root>/.forge/search-index/documents.json
    """
    return forge_root / ".forge" / SEARCH_INDEX_DIR / DOCUMENTS_FILENAME


class SearchDocumentStore:
    """Manage per-project search document metadata store.

    Store location: <forge_root>/.forge/search-index/documents.json
    Documents are keyed by transcript_path (absolute path string).

    V2 schema: metadata only (no content, no tokens). Content and BM25
    index data are stored in separate files.

    Error handling:
    - Missing file: returns empty list (self-healing)
    - Corrupted file: raises SearchDocumentStoreCorruptedError
    - Wrong schema version: raises SchemaVersionError (v1 triggers rebuild)
    """

    def __init__(
        self,
        forge_root: Path | None = None,
        *,
        store_path: Path | None = None,
    ) -> None:
        if store_path:
            self._store_path = store_path  # Explicit override (tests)
        elif forge_root:
            self._store_path = get_project_documents_store_path(forge_root)
        else:
            raise ValueError("Either forge_root or store_path required")

    @property
    def store_path(self) -> Path:
        return self._store_path

    def exists(self) -> bool:
        return self._store_path.is_file()

    def read(self) -> list[SearchDocumentMeta]:
        """Read all document metadata from disk.

        Returns empty list if the file does not exist (self-healing).

        Raises:
            SearchDocumentStoreCorruptedError: If the file contains invalid JSON.
            SchemaVersionError: If the schema version doesn't match (v1 → rebuild).
        """
        if not self.exists():
            return []

        path_str = str(self._store_path)

        try:
            with open(self._store_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise SearchDocumentStoreCorruptedError(path_str, f"invalid JSON: {e}") from e
        except OSError as e:
            raise SearchDocumentStoreCorruptedError(path_str, f"read error: {e}") from e

        if not isinstance(data, dict):
            raise SearchDocumentStoreCorruptedError(path_str, f"expected JSON object, got {type(data).__name__}")

        version = data.get("schema_version")
        if version is None:
            raise SearchDocumentStoreCorruptedError(path_str, "missing schema_version")
        if version != DOCUMENT_STORE_VERSION:
            raise SchemaVersionError(path_str, DOCUMENT_STORE_VERSION, version)

        raw_docs = data.get("documents", [])
        if not isinstance(raw_docs, list):
            logger.warning(
                "Document store %s has non-list 'documents' field (got %s), treating as empty",
                path_str,
                type(raw_docs).__name__,
            )
            return []

        documents: list[SearchDocumentMeta] = []
        path_str = str(self._store_path)
        for i, raw in enumerate(raw_docs):
            if not isinstance(raw, dict):
                raise SearchDocumentStoreCorruptedError(path_str, f"entry {i} is {type(raw).__name__}, expected dict")
            try:
                doc = dacite.from_dict(
                    data_class=SearchDocumentMeta,
                    data=raw,
                    config=dacite.Config(strict=True),
                )
                documents.append(doc)
            except (dacite.DaciteError, KeyError, TypeError) as e:
                raise SearchDocumentStoreCorruptedError(path_str, f"entry {i} deserialization error: {e}") from e

        return documents

    def write(self, documents: list[SearchDocumentMeta]) -> None:
        """Write documents atomically.

        Creates parent directories if needed.
        """
        data: dict[str, Any] = {
            "schema_version": DOCUMENT_STORE_VERSION,
            "updated_at": now_iso(),
            "documents": [doc.to_dict() for doc in documents],
        }
        atomic_write_json(self._store_path, data)

    def replace_all(
        self,
        documents: list[SearchDocumentMeta],
        *,
        timeout_s: float = STORE_LOCK_TIMEOUT_S,
    ) -> None:
        """Replace all documents under lock (for rebuild-index)."""
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            self.write(documents)

    def add(
        self,
        doc: SearchDocumentMeta,
        *,
        timeout_s: float = HANDLER_STORE_LOCK_TIMEOUT_S,
    ) -> None:
        """Add or replace a document (locked read-modify-write).

        Documents are keyed by transcript_path. Idempotent: if a document
        with the same transcript_path already exists, it is replaced.
        """
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            docs = self.read()
            docs = [d for d in docs if d.transcript_path != doc.transcript_path]
            docs.append(doc)
            self.write(docs)

    def find_missing(self) -> list[str]:
        """Return transcript_paths whose files no longer exist on disk.

        Read-only counterpart to prune_missing (no lock, no write): the preview
        for `forge search clean`. Same predicate as prune_missing, so the count
        a preview reports matches what --yes would remove.
        """
        return [d.transcript_path for d in self.read() if not Path(d.transcript_path).is_file()]

    def prune_missing(self, *, timeout_s: float = STORE_LOCK_TIMEOUT_S) -> list[str]:
        """Remove documents whose transcript_path no longer exists on disk.

        Locked read-modify-write. Returns list of removed transcript_path strings.
        Skips write if nothing was pruned.
        """
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            docs = self.read()
            kept: list[SearchDocumentMeta] = []
            removed: list[str] = []
            for d in docs:
                if Path(d.transcript_path).is_file():
                    kept.append(d)
                else:
                    removed.append(d.transcript_path)
            if removed:
                self.write(kept)
            return removed

    def remove(self, transcript_path: str, *, timeout_s: float = STORE_LOCK_TIMEOUT_S) -> bool:
        """Remove a document by transcript_path (locked read-modify-write).

        Returns True if a document was found and removed, False otherwise.
        """
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            docs = self.read()
            filtered = [d for d in docs if d.transcript_path != transcript_path]
            if len(filtered) == len(docs):
                return False
            self.write(filtered)
            return True
