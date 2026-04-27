from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest

from forge.core.state.lock import FileLockTimeoutError, file_lock


def _hold_lock(lock_path: str, hold_s: float) -> None:
    path = Path(lock_path)
    with file_lock(lock_path=path, timeout_s=1.0, poll_s=0.01):
        # Signal to parent that lock is held.
        Path(f"{lock_path}.ready").write_text("1")
        time.sleep(hold_s)


def test_file_lock_times_out_under_contention(tmp_path: Path) -> None:
    lock_path = tmp_path / "state.lock"

    proc = multiprocessing.Process(target=_hold_lock, args=(str(lock_path), 0.4))
    proc.start()

    ready_path = Path(f"{lock_path}.ready")

    try:
        deadline = time.monotonic() + 2.0
        while not ready_path.exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("child process did not acquire lock in time")
            time.sleep(0.01)

        with pytest.raises(FileLockTimeoutError):
            with file_lock(lock_path=lock_path, timeout_s=0.05, poll_s=0.01):
                pass
    finally:
        proc.join(timeout=2.0)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2.0)


def test_file_lock_releases_after_process_exit(tmp_path: Path) -> None:
    lock_path = tmp_path / "state.lock"

    proc = multiprocessing.Process(target=_hold_lock, args=(str(lock_path), 0.2))
    proc.start()
    proc.join(timeout=2.0)
    assert not proc.is_alive()

    # Should be acquirable now.
    with file_lock(lock_path=lock_path, timeout_s=1.0, poll_s=0.01):
        pass
