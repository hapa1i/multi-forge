"""Content store for lazy snippet loading.

Stores document content strings keyed by transcript_path. Content is loaded
at query time only for top-K results (snippet extraction), not for scoring.

Store location: <project_root>/.forge/search-index/content.json

Follows the same patterns as other search stores: atomic writes, file
locking, schema versioning, self-healing on missing file.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from forge.core.state import (
    SchemaVersionError,
    atomic_write_json,
    file_lock_for_target,
    now_iso,
)

from .exceptions import ContentStoreCorruptedError
from .index_state import SEARCH_INDEX_DIR

logger = logging.getLogger(__name__)

# File and schema constants
CONTENT_FILENAME = "content.json"
CONTENT_STORE_VERSION = 1

# Lock timeouts
STORE_LOCK_TIMEOUT_S = 5.0
HANDLER_LOCK_TIMEOUT_S = 1.0


def _get_content_store_path(forge_root: Path) -> Path:
    return forge_root / ".forge" / SEARCH_INDEX_DIR / CONTENT_FILENAME


class ContentStore:
    """Manage per-project content store for lazy snippet loading.

    Store location: <forge_root>/.forge/search-index/content.json
    Maps transcript_path -> extracted content string.

    Error handling:
    - Missing file: returns empty dict (self-healing)
    - Corrupted file: raises ContentStoreCorruptedError
    - Wrong schema version: raises SchemaVersionError
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
            self._store_path = _get_content_store_path(forge_root)
        else:
            raise ValueError("Either forge_root or store_path required")

    @property
    def store_path(self) -> Path:
        return self._store_path

    def exists(self) -> bool:
        return self._store_path.is_file()

    def read_all(self) -> dict[str, str]:
        """Read all content from disk.

        Returns empty dict if the file does not exist (self-healing).

        Raises:
            ContentStoreCorruptedError: If the file contains invalid JSON.
            SchemaVersionError: If the schema version doesn't match.
        """
        if not self.exists():
            return {}

        path_str = str(self._store_path)

        try:
            with open(self._store_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ContentStoreCorruptedError(path_str, f"invalid JSON: {e}") from e
        except OSError as e:
            raise ContentStoreCorruptedError(path_str, f"read error: {e}") from e

        if not isinstance(data, dict):
            raise ContentStoreCorruptedError(
                path_str,
                f"expected JSON object, got {type(data).__name__}",
            )

        version = data.get("schema_version")
        if version is None:
            raise ContentStoreCorruptedError(path_str, "missing schema_version")
        if version != CONTENT_STORE_VERSION:
            raise SchemaVersionError(path_str, CONTENT_STORE_VERSION, version)

        content = data.get("content", {})
        if not isinstance(content, dict):
            logger.warning(
                "Content store %s has non-dict 'content' field (got %s), treating as empty",
                path_str,
                type(content).__name__,
            )
            return {}

        return content

    def read_keys(self, keys: list[str]) -> dict[str, str]:
        """Read content for specific document keys only.

        Loads the full JSON file (unavoidable with JSON format) but returns
        only the requested keys. This is the method used at query time for
        snippet extraction of top-K results.

        Returns:
            Dict mapping requested keys to their content strings.
            Keys not found in the store are omitted from the result.
        """
        all_content = self.read_all()
        return {k: all_content[k] for k in keys if k in all_content}

    def write(self, content_map: dict[str, str]) -> None:
        """Write content store atomically. Creates parent directories if needed."""
        payload: dict[str, Any] = {
            "schema_version": CONTENT_STORE_VERSION,
            "updated_at": now_iso(),
            "content": content_map,
        }
        atomic_write_json(self._store_path, payload)

    def replace_all(
        self,
        content_map: dict[str, str],
        *,
        timeout_s: float = STORE_LOCK_TIMEOUT_S,
    ) -> None:
        """Replace all content under lock (for rebuild-index)."""
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            self.write(content_map)

    def add(
        self,
        doc_key: str,
        content: str,
        *,
        timeout_s: float = HANDLER_LOCK_TIMEOUT_S,
    ) -> None:
        """Add or replace content for a document (locked, idempotent)."""
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            content_map = self.read_all()
            content_map[doc_key] = content
            self.write(content_map)

    def remove(
        self,
        doc_key: str,
        *,
        timeout_s: float = HANDLER_LOCK_TIMEOUT_S,
    ) -> bool:
        """Remove content for a document (locked). Returns True if found."""
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            content_map = self.read_all()
            if doc_key not in content_map:
                return False
            del content_map[doc_key]
            self.write(content_map)
            return True

    def prune_keys(
        self,
        valid_keys: set[str],
        *,
        timeout_s: float = STORE_LOCK_TIMEOUT_S,
    ) -> list[str]:
        """Remove entries not in valid_keys (locked). Returns removed keys."""
        with file_lock_for_target(target_path=self._store_path, timeout_s=timeout_s):
            content_map = self.read_all()
            removed = [k for k in content_map if k not in valid_keys]
            if not removed:
                return []
            for k in removed:
                del content_map[k]
            self.write(content_map)
            return removed
