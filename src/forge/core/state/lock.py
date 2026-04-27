"""Cross-process file locking for Forge state.

Forge state files are written atomically via write-temp + os.replace.
That prevents torn reads, but it does NOT prevent concurrent *read-modify-write*
flows from overwriting each other.

This module provides a small, advisory lock primitive to serialize those RMW
operations across processes.

Design notes:
- Locks are implemented using `fcntl.flock` (macOS/Linux).
- We always lock a **separate lock file** (e.g., "index.json.lock"), not the
  target file itself, because the target file inode changes on atomic replace.
- This is intended to be best-effort. Callers should choose appropriate
  timeouts (hooks: short/fail-open; CLI: longer).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .exceptions import StateError


class FileLockTimeoutError(StateError):
    """Raised when a lock cannot be acquired within the timeout."""

    def __init__(self, lock_path: Path, timeout_s: float) -> None:
        self.lock_path = lock_path
        self.timeout_s = timeout_s
        super().__init__(f"timed out acquiring lock '{lock_path}' after {timeout_s:.3f}s")


def get_lock_path_for_target(target_path: Path) -> Path:
    """Return the lock file path for a target state file.

    Example:
        target: /home/user/.forge/sessions/index.json
        lock:   /home/user/.forge/sessions/index.json.lock
    """

    return target_path.parent / f"{target_path.name}.lock"


@contextmanager
def file_lock(*, lock_path: Path, timeout_s: float, poll_s: float = 0.05) -> Iterator[None]:
    """Acquire an exclusive advisory lock for the duration of the context.

    Args:
        lock_path: Path to the lock file.
        timeout_s: Maximum time to wait for acquisition.
        poll_s: Sleep interval between non-blocking retries.

    Raises:
        FileLockTimeoutError: If the lock cannot be acquired in time.
        OSError: If the lock file cannot be created/opened.
    """

    # Local import: avoids importing fcntl on platforms where it may not exist.
    import fcntl

    lock_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + timeout_s

    # Keep the fd open for the duration of the lock.
    with lock_path.open("a+", encoding="utf-8") as f:
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise FileLockTimeoutError(lock_path=lock_path, timeout_s=timeout_s)
                time.sleep(poll_s)

        try:
            yield
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                # Best-effort cleanup; fd close will also release.
                pass


@contextmanager
def file_lock_for_target(*, target_path: Path, timeout_s: float, poll_s: float = 0.05) -> Iterator[None]:
    """Convenience wrapper to lock a target file by deriving its lock path."""

    with file_lock(
        lock_path=get_lock_path_for_target(target_path),
        timeout_s=timeout_s,
        poll_s=poll_s,
    ):
        yield
