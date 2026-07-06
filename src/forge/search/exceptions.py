"""Exceptions for the Forge search module.

Follows the forge.core.state exception hierarchy:
- SearchError is the module-level base
- IndexStateCorruptedError inherits StateCorruptedError for consistency
  with BackendRegistryCorruptedError and other state corruption errors
"""

from __future__ import annotations

from forge.core.state import StateCorruptedError, StateUnreadableError


class SearchError(Exception):
    """Base exception for search module operations."""


class IndexStateCorruptedError(StateCorruptedError):
    """Raised when the index state file cannot be parsed.

    Inherits (path, reason) signature from StateCorruptedError.
    """

    pass


class IndexStateUnreadableError(StateUnreadableError):
    """Raised when the index state file exists but cannot be read."""

    pass


class SearchDocumentStoreCorruptedError(StateCorruptedError):
    """Raised when the document store file cannot be parsed.

    Inherits (path, reason) signature from StateCorruptedError.
    """

    pass


class SearchDocumentStoreUnreadableError(StateUnreadableError):
    """Raised when the document store file exists but cannot be read."""

    pass


class BM25IndexCorruptedError(StateCorruptedError):
    """Raised when the BM25 index file cannot be parsed or is inconsistent.

    Inherits (path, reason) signature from StateCorruptedError.
    """

    pass


class BM25IndexUnreadableError(StateUnreadableError):
    """Raised when the BM25 index file exists but cannot be read."""

    pass


class ContentStoreCorruptedError(StateCorruptedError):
    """Raised when the content store file cannot be parsed or is inconsistent.

    Inherits (path, reason) signature from StateCorruptedError.
    """

    pass


class ContentStoreUnreadableError(StateUnreadableError):
    """Raised when the content store file exists but cannot be read."""

    pass
