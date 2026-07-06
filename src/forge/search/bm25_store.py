"""Persistent BM25 index store.

Persists precomputed BM25 data structures (term frequencies, document
frequencies, corpus stats) so queries only run scoring, not index
construction.

Store location: <project_root>/.forge/search-index/bm25_index.json

Follows the same patterns as SearchDocumentStore/IndexStateStore:
atomic writes, file locking, schema versioning, self-healing on missing file.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from forge.core.state import (
    SchemaVersionError,
    atomic_write_json,
    file_lock_for_target,
    now_iso,
    read_versioned_json_object,
)

from .exceptions import BM25IndexCorruptedError, BM25IndexUnreadableError
from .index_state import SEARCH_INDEX_DIR

logger = logging.getLogger(__name__)

BM25_INDEX_FILENAME = "bm25_index.json"
BM25_INDEX_VERSION = 1

# Bump when TOKEN_RE or tokenize() logic changes — mismatch forces rebuild
# to prevent silently wrong scores.
TOKENIZER_ID = "v1"

STORE_LOCK_TIMEOUT_S = 5.0
HANDLER_LOCK_TIMEOUT_S = 1.0


@dataclass
class BM25IndexData:
    """Serializable BM25 index state.

    Positional alignment: doc_keys[i], doc_lens[i], term_freqs[i] all
    refer to the same document.
    """

    doc_keys: list[str] = field(default_factory=list)
    doc_lens: list[int] = field(default_factory=list)
    term_freqs: list[dict[str, int]] = field(default_factory=list)
    doc_freqs: dict[str, int] = field(default_factory=dict)
    avgdl: float = 0.0
    k1: float = 1.5
    b: float = 0.75
    tokenizer_id: str = TOKENIZER_ID

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return asdict(self)


def _get_bm25_index_path(forge_root: Path) -> Path:
    return forge_root / ".forge" / SEARCH_INDEX_DIR / BM25_INDEX_FILENAME


def _handle_bm25_version_mismatch(path: Path, _data: dict[str, Any], version: Any) -> NoReturn:
    raise SchemaVersionError(str(path), BM25_INDEX_VERSION, version)


class BM25IndexStore:
    """Manage per-project persistent BM25 index.

    Store location: <forge_root>/.forge/search-index/bm25_index.json

    Error handling:
    - Missing file: returns None (no index built yet)
    - Corrupted file: raises BM25IndexCorruptedError
    - Wrong schema version: raises SchemaVersionError
    - Tokenizer ID mismatch: raises SchemaVersionError (forces rebuild)
    """

    def __init__(
        self,
        forge_root: Path | None = None,
        *,
        store_path: Path | None = None,
    ) -> None:
        if store_path:
            self._store_path = store_path
        elif forge_root:
            self._store_path = _get_bm25_index_path(forge_root)
        else:
            raise ValueError("Either forge_root or store_path required")

    @property
    def store_path(self) -> Path:
        return self._store_path

    def exists(self) -> bool:
        return self._store_path.is_file()

    def read(self) -> BM25IndexData | None:
        """Read BM25 index from disk.

        Returns None if the file does not exist (no index built yet).

        Raises:
            BM25IndexCorruptedError: If the file contains invalid JSON,
                tokenizer ID mismatch, or positional arrays are misaligned.
            SchemaVersionError: If schema version doesn't match.
        """
        if not self.exists():
            return None

        path_str = str(self._store_path)

        data = read_versioned_json_object(
            self._store_path,
            version_key="schema_version",
            expected_version=BM25_INDEX_VERSION,
            corrupted_error=BM25IndexCorruptedError,
            unreadable_error=BM25IndexUnreadableError,
            missing_version_reason="missing schema_version",
            on_version_mismatch=_handle_bm25_version_mismatch,
        )

        stored_tokenizer = data.get("tokenizer_id", "")
        if stored_tokenizer != TOKENIZER_ID:
            raise BM25IndexCorruptedError(
                path_str,
                f"tokenizer mismatch: index has '{stored_tokenizer}', "
                f"current is '{TOKENIZER_ID}'. Run 'forge search rebuild-index' to fix.",
            )

        try:
            index_data = BM25IndexData(
                doc_keys=data.get("doc_keys", []),
                doc_lens=data.get("doc_lens", []),
                term_freqs=data.get("term_freqs", []),
                doc_freqs=data.get("doc_freqs", {}),
                avgdl=float(data.get("avgdl", 0.0)),
                k1=float(data.get("k1", 1.5)),
                b=float(data.get("b", 0.75)),
                tokenizer_id=stored_tokenizer,
            )
        except (TypeError, ValueError) as e:
            raise BM25IndexCorruptedError(path_str, f"invalid data: {e}") from e

        n_keys = len(index_data.doc_keys)
        n_lens = len(index_data.doc_lens)
        n_freqs = len(index_data.term_freqs)
        if n_keys != n_lens or n_keys != n_freqs:
            raise BM25IndexCorruptedError(
                path_str,
                f"positional array length mismatch: doc_keys={n_keys}, "
                f"doc_lens={n_lens}, term_freqs={n_freqs}. "
                "Run 'forge search rebuild-index' to fix.",
            )

        return index_data

    def write(self, data: BM25IndexData) -> None:
        """Write BM25 index atomically. Creates parent directories if needed."""
        payload: dict[str, Any] = {
            "schema_version": BM25_INDEX_VERSION,
            "updated_at": now_iso(),
            "tokenizer_id": data.tokenizer_id,
            **data.to_dict(),
        }
        atomic_write_json(self._store_path, payload)

    def replace_all(
        self,
        data: BM25IndexData,
        *,
        timeout_s: float = STORE_LOCK_TIMEOUT_S,
    ) -> None:
        """Replace entire index under lock (for rebuild-index)."""
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            self.write(data)

    def upsert_document(
        self,
        doc_key: str,
        term_freq: dict[str, int],
        doc_len: int,
        *,
        timeout_s: float = HANDLER_LOCK_TIMEOUT_S,
    ) -> None:
        """Add or replace a document in the index (locked, idempotent).

        If doc_key already exists, its old contribution is removed first
        (doc_freqs decremented) before adding the new entry. This ensures
        work queue retries don't create duplicates or double-increment.
        """
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            data = self.read()
            if data is None:
                data = BM25IndexData()

            _remove_doc_from_data(data, doc_key)

            data.doc_keys.append(doc_key)
            data.doc_lens.append(doc_len)
            data.term_freqs.append(term_freq)
            for term, count in term_freq.items():
                if count > 0:
                    data.doc_freqs[term] = data.doc_freqs.get(term, 0) + 1

            data.avgdl = sum(data.doc_lens) / max(len(data.doc_lens), 1)

            self.write(data)

    def remove_document(
        self,
        doc_key: str,
        *,
        timeout_s: float = HANDLER_LOCK_TIMEOUT_S,
    ) -> bool:
        """Remove a document from the index (locked). Returns True if found."""
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            data = self.read()
            if data is None:
                return False

            removed = _remove_doc_from_data(data, doc_key)
            if not removed:
                return False

            data.avgdl = sum(data.doc_lens) / max(len(data.doc_lens), 1)

            self.write(data)
            return True


def _remove_doc_from_data(data: BM25IndexData, doc_key: str) -> bool:
    """Remove a document from BM25IndexData in-place. Returns True if found."""
    try:
        idx = data.doc_keys.index(doc_key)
    except ValueError:
        return False

    old_tf = data.term_freqs[idx]
    for term in old_tf:
        if term in data.doc_freqs:
            data.doc_freqs[term] -= 1
            if data.doc_freqs[term] <= 0:
                del data.doc_freqs[term]

    data.doc_keys.pop(idx)
    data.doc_lens.pop(idx)
    data.term_freqs.pop(idx)

    return True
