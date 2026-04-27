"""Base exceptions for Forge state operations.

Domain modules (session, proxies) define their own specific exceptions
that inherit from these bases.
"""

from __future__ import annotations


class StateError(Exception):
    """Base exception for all state operations."""


class StateNotFoundError(StateError):
    """Raised when a state file does not exist.

    Attributes:
        path: Path to the missing file.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"state file not found: '{path}'")


class StateCorruptedError(StateError):
    """Raised when a state file cannot be parsed.

    Attributes:
        path: Path to the corrupted file.
        reason: Description of what went wrong.
    """

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"state file at '{path}' is corrupted: {reason}")


class SchemaVersionError(StateCorruptedError):
    """Raised when schema version is unsupported.

    Attributes:
        path: Path to the file.
        expected: Expected version(s).
        actual: Version found in file.
    """

    def __init__(self, path: str, expected: int | set[int], actual: int) -> None:
        self.expected = expected if isinstance(expected, set) else {expected}
        self.actual = actual
        super().__init__(
            path,
            f"unsupported schema version: {actual} (expected: {sorted(self.expected)})",
        )
