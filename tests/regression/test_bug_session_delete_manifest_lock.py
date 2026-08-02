"""Regression: terminal deletion could race a session-manifest update.

Bug: session_delete_manifest_lock.
Root cause: ``IndexStore.delete_session_txn`` serialized deletion against
creators, but ``SessionStore.delete`` did not take the manifest lock used by
``SessionStore.update``. An updater already holding that lock could finish after
deletion removed the index row and recreate the manifest as an unlisted orphan.

Fix: terminal deletion takes the manifest lock, unlinks the manifest before
directory cleanup, and removes the index row only after that callback succeeds.

Affected: src/forge/session/index.py, src/forge/session/store.py
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from forge.session import SessionManager, SessionStore
from forge.session import store as store_mod
from forge.session.index import IndexStore
from forge.session.models import SessionState

pytestmark = pytest.mark.regression


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()
    return project


class TestSessionDeleteManifestLock:
    def test_manifest_delete_failure_keeps_the_row(self, tmp_path: Path) -> None:
        """A manifest-lock failure must not turn a complete session into an orphan."""
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("victim", worktree_path=str(project), direct=True)
        boom = RuntimeError("manifest lock failed")

        def _fail() -> None:
            raise boom

        with pytest.raises(RuntimeError) as excinfo:
            index.delete_session_txn(
                "victim",
                forge_root=str(project),
                expect_manifest_absent=False,
                delete_manifest=_fail,
            )

        assert excinfo.value is boom
        assert index.live_session_exists("victim", forge_root=str(project))

    def test_delete_waits_for_an_in_flight_manifest_update(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hook update already holding the manifest lock must finish before deletion.

        Without the delete-side lock, deletion removes the row and directory while
        the updater is paused, then the updater's atomic write recreates the
        manifest with no row.
        """
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("victim", worktree_path=str(project), direct=True)
        store = SessionStore(str(project), "victim")

        update_ready = threading.Event()
        allow_update = threading.Event()
        delete_lock_attempted = threading.Event()
        update_errors: list[BaseException] = []
        delete_errors: list[BaseException] = []
        real_write = store._write_unlocked

        def _paused_write(state: SessionState) -> None:
            update_ready.set()
            if not allow_update.wait(timeout=10):
                raise RuntimeError("delete never attempted the manifest lock")
            real_write(state)

        monkeypatch.setattr(store, "_write_unlocked", _paused_write)

        def _update() -> None:
            try:
                store.update(timeout_s=5.0, mutate=lambda state: setattr(state, "last_accessed_at", "updated"))
            except BaseException as e:  # noqa: BLE001 - surfaced below
                update_errors.append(e)

        updater = threading.Thread(target=_update, name="manifest-updater")
        updater.start()
        assert update_ready.wait(timeout=10), "the updater must hold the manifest lock"

        real_manifest_lock = store_mod.file_lock_for_target

        @contextmanager
        def _observed_manifest_lock(*, target_path: Path, **kwargs: object) -> Iterator[None]:
            if threading.current_thread().name == "session-deleter":
                delete_lock_attempted.set()
            with real_manifest_lock(target_path=target_path, **kwargs):  # type: ignore[arg-type]
                yield

        monkeypatch.setattr(store_mod, "file_lock_for_target", _observed_manifest_lock)

        def _delete() -> None:
            try:
                manager.delete_session(
                    "victim",
                    forge_root=str(project),
                    delete_transcripts=False,
                    delete_worktree=False,
                )
            except BaseException as e:  # noqa: BLE001 - surfaced below
                delete_errors.append(e)

        deleter = threading.Thread(target=_delete, name="session-deleter")
        deleter.start()
        observed_lock = delete_lock_attempted.wait(timeout=2)
        allow_update.set()
        updater.join(timeout=10)
        deleter.join(timeout=10)

        assert observed_lock, "delete must acquire the manifest lock (mutation guard)"
        assert not updater.is_alive() and not deleter.is_alive()
        assert update_errors == []
        assert delete_errors == []
        assert index.read().sessions == {}
        assert not store.exists(), "the completed update must not resurrect a deleted manifest"
