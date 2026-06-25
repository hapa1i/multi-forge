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
    """Raised when a state file cannot be parsed or has an incompatible format.

    Attributes:
        path: Path to the problematic file.
        reason: Description of what went wrong.
    """

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"'{path}': {reason}")


class StateUnreadableError(StateError):
    """Raised when a state file exists but the read itself failed (not corruption).

    Distinct from ``StateCorruptedError``: the file's *contents* are not known to be
    bad -- the open/read raised ``OSError`` (the file is locked/busy, an I/O error, or a
    permissions problem). This is transient/environmental, so Forge must NOT treat it as
    corruption. Critically, ``forge clean`` must never delete a file it merely failed to
    open: only ``StateCorruptedError`` (genuine bad content) is deletable.

    Attributes:
        path: Path to the unreadable file.
        reason: Description of the read failure.
    """

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"'{path}': {reason}")


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
        self.path = path
        self.reason = f"incompatible version {actual} (expected {sorted(self.expected)})"
        Exception.__init__(
            self,
            f"'{path}' has incompatible version {actual} "
            f"(this Forge expects {sorted(self.expected)}). "
            f"Delete this file and retry.",
        )
