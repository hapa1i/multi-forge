"""Regression: session creation left a manifest with no index row when killed mid-commit.

Bug: session_create_crash_atomicity (docs/board), discharging the open debt from
native_session_adoption's closeout.
Root cause: every path that mints a session wrote the manifest and the index row
under two separate locks. A process killed between them left a manifest nothing
lists, which still owned its name and its conversation binding, and which only a
manual `session delete` from inside the owning project could clear.

Fix: `IndexStore.create_session_txn` writes the row first and the manifest second
inside one index-lock acquisition. A kill now leaves at most a bare row, which is
prunable and which the next same-name transaction reclaims.

Two failure families are covered here and neither substitutes for the other:
compensation (the callback raises, so the transaction unwinds) and crash residue
(the process dies, so nothing unwinds and a bare row is left behind).

Affected: src/forge/session/index.py, src/forge/session/manager.py,
src/forge/core/ops/session_context.py
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from forge.core.ops.session_context import collect_bound_codex_threads, collect_bound_uuids
from forge.session import SessionManager, SessionStore, create_session_state
from forge.session import index as index_mod
from forge.session.exceptions import (
    SessionExistsError,
    SessionNotFoundError,
    UuidAlreadyBoundError,
)
from forge.session.index import IndexStore
from forge.session.models import CodexConfirmed, SessionState

pytestmark = pytest.mark.regression

_UUID = "11111111-2222-3333-4444-555555555555"
_THREAD = "01912345-6789-7abc-8def-0123456789ab"


def _project(tmp_path: Path, name: str = "proj") -> Path:
    project = tmp_path / name
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()
    return project


def _state(name: str, project: Path) -> SessionState:
    state = create_session_state(name, worktree_path=str(project))
    state.forge_root = str(project)
    return state


def _seed_residue(index: IndexStore, state: SessionState, project: Path) -> None:
    """Write a row with no manifest -- the residue a killed transaction leaves.

    add_from_state, not create_session_txn: the transaction would write the
    manifest too, which is exactly the state this models the absence of.
    """
    index.add_from_state(
        state,
        str(project),
        checkout_root=str(project),
        forge_root=str(project),
        relative_path=".",
    )
    assert not SessionStore(str(project), state.name).exists()


@contextmanager
def _counting_index_lock(monkeypatch: pytest.MonkeyPatch, counter: list[Path]) -> Iterator[None]:
    """Count index-lock acquisitions made through forge.session.index."""
    real = index_mod.file_lock_for_target

    @contextmanager
    def _counted(*, target_path: Path, **kwargs: object) -> Iterator[None]:
        counter.append(target_path)
        with real(target_path=target_path, **kwargs):  # type: ignore[arg-type]
            yield

    monkeypatch.setattr(index_mod, "file_lock_for_target", _counted)
    yield


class TestCompensation:
    """The callback raises, so the transaction unwinds its own row."""

    def test_callback_failure_leaves_no_row_and_reraises_unchanged(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        boom = SessionExistsError("orphaned")

        def _fail() -> None:
            raise boom

        with pytest.raises(SessionExistsError) as excinfo:
            index.create_session_txn(
                _state("orphaned", project),
                str(project),
                forge_root=str(project),
                write_manifest=_fail,
            )

        assert excinfo.value is boom, "the callback's exception must surface unchanged"
        assert index.read().sessions == {}, "compensation must remove the row it wrote"

    def test_compensation_never_reacquires_the_index_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """file_lock_for_target is not reentrant, so compensation must stay in-lock.

        A compensation that called `remove_session` would block on the lock it
        already holds and surface FileLockTimeoutError instead of the callback's
        own error.
        """
        project = _project(tmp_path)
        index = IndexStore()
        acquisitions: list[Path] = []

        def _fail() -> None:
            raise RuntimeError("manifest write failed")

        with _counting_index_lock(monkeypatch, acquisitions):
            with pytest.raises(RuntimeError, match="manifest write failed"):
                index.create_session_txn(
                    _state("once", project),
                    str(project),
                    forge_root=str(project),
                    write_manifest=_fail,
                )

        assert len(acquisitions) == 1, f"expected one acquisition, got {len(acquisitions)}"
        assert index.read().sessions == {}

    def test_index_side_collision_raises_before_the_callback_runs(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("taken", worktree_path=str(project), direct=True)

        ran: list[int] = []
        with pytest.raises(SessionExistsError):
            index.create_session_txn(
                _state("taken", project),
                str(project),
                forge_root=str(project),
                write_manifest=lambda: ran.append(1),
            )

        assert ran == [], "the manifest callback must not run after an index-side rejection"

    def test_uuid_collision_raises_before_the_callback_runs(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("first", worktree_path=str(project), direct=True, claude_session_id=_UUID)

        second = _state("second", project)
        second.confirmed.claude_session_id = _UUID
        ran: list[int] = []

        with pytest.raises(UuidAlreadyBoundError):
            index.create_session_txn(
                second,
                str(project),
                forge_root=str(project),
                require_uuid_unbound=True,
                write_manifest=lambda: ran.append(1),
            )

        assert ran == []


class TestCrashResidue:
    """The process dies, so nothing unwinds and a bare row is left behind."""

    def test_transaction_prunes_the_residue_and_proceeds(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        state = _state("revived", project)
        _seed_residue(index, state, project)

        store = SessionStore(str(project), "revived")
        index.create_session_txn(
            state,
            str(project),
            forge_root=str(project),
            write_manifest=lambda: store.create_exclusive(state),
        )

        assert store.exists(), "the retry must publish a manifest"
        assert len(index.read().sessions) == 1, "the residue row must be replaced, not duplicated"

    def test_residue_does_not_block_rebinding_its_own_conversation(self, tmp_path: Path) -> None:
        """The stale-row prune must run before the uniqueness scan.

        Otherwise a crash mid-adopt would permanently refuse re-adopting the very
        conversation the dead session had claimed -- the scan would match the
        residue's own row.
        """
        project = _project(tmp_path)
        index = IndexStore()
        state = _state("adopted", project)
        state.confirmed.claude_session_id = _UUID
        _seed_residue(index, state, project)

        store = SessionStore(str(project), "adopted")
        index.create_session_txn(
            state,
            str(project),
            forge_root=str(project),
            require_uuid_unbound=True,
            write_manifest=lambda: store.create_exclusive(state),
        )

        assert store.exists()

    def test_list_sessions_prunes_the_residue(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        _seed_residue(index, _state("ghost", project), project)

        assert index.list_sessions() == []
        assert index.read().sessions == {}, "the prune must persist"

    def test_get_session_prunes_the_residue(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        _seed_residue(index, _state("ghost", project), project)

        with pytest.raises(SessionNotFoundError):
            index.get_session("ghost", forge_root=str(project))
        assert index.read().sessions == {}

    def test_direct_same_name_retry_succeeds_without_list_or_delete(self, tmp_path: Path) -> None:
        """The card's retry contract: no intervening `session list` or `session delete`."""
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        _seed_residue(index, _state("wanted", project), project)

        state = manager.start_session("wanted", worktree_path=str(project), direct=True)

        assert state.name == "wanted"
        assert SessionStore(str(project), "wanted").exists()
        assert index.get_session("wanted", forge_root=str(project)) is not None


class TestPrunerRaceGuard:
    """The under-lock re-check before every prune delete is load-bearing."""

    def test_pruner_spares_a_row_republished_before_its_re_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pruner acting on a pre-transaction snapshot must re-verify under the lock.

        list_sessions probes the filesystem unlocked, so it can flag a name as
        stale and only then re-acquire the lock to delete. If a new transaction
        published row+manifest for that name in between, the re-check must spare
        it -- otherwise row-first creation would be pruned out from under its own
        creator, which is why the earlier attempt at this ordering was reverted.
        """
        project = _project(tmp_path)
        index = IndexStore()
        state = _state("revived", project)
        _seed_residue(index, state, project)

        store = SessionStore(str(project), "revived")
        real = index_mod.file_lock_for_target
        acquisitions: list[int] = []

        @contextmanager
        def _republish_before_the_prune_lock(*, target_path: Path, **kwargs: object) -> Iterator[None]:
            acquisitions.append(1)
            # Second acquisition is list_sessions' prune re-lock. Land the manifest
            # first, as a completed transaction would have.
            if len(acquisitions) == 2 and not store.exists():
                store.create_exclusive(state)
            with real(target_path=target_path, **kwargs):  # type: ignore[arg-type]
                yield

        monkeypatch.setattr(index_mod, "file_lock_for_target", _republish_before_the_prune_lock)

        listed = [name for name, _ in index.list_sessions()]

        assert acquisitions[1:], "the prune path must have re-acquired the lock"
        assert listed == ["revived"], "the re-check must spare the republished row"
        assert index.read().sessions, "and must not have deleted it"

    def test_pruner_still_deletes_a_row_that_is_stale_at_the_re_check(self, tmp_path: Path) -> None:
        """Companion to the test above: without the republish, the row is pruned.

        Together these two show the re-check discriminates rather than always
        sparing.
        """
        project = _project(tmp_path)
        index = IndexStore()
        _seed_residue(index, _state("revived", project), project)

        assert index.list_sessions() == []
        assert index.read().sessions == {}


class TestLiveSessionExists:
    def test_ignores_a_bare_row(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        _seed_residue(index, _state("ghost", project), project)

        assert index.session_exists("ghost", forge_root=str(project)) is True, "the row is there"
        assert index.live_session_exists("ghost", forge_root=str(project)) is False, "but nothing lives at it"

    def test_reports_a_healthy_session(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("alive", worktree_path=str(project), direct=True)

        assert index.live_session_exists("alive", forge_root=str(project)) is True

    def test_auto_naming_still_treats_a_bare_row_as_taken(self, tmp_path: Path) -> None:
        """_name_is_taken keeps the conservative row-only check.

        Skipping a residue name costs an auto-name suffix, not an error, so the
        cheaper answer is the right one there.
        """
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        _seed_residue(index, _state("ghost", project), project)

        assert manager._name_is_taken("ghost", forge_root=str(project)) is True


class TestBindingScansDuringPublication:
    """A published row can be observed before its manifest by unlocked readers."""

    def test_claude_scan_reports_an_in_flight_conversation_as_bound(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        state = _state("inflight", project)
        state.confirmed.claude_session_id = _UUID
        _seed_residue(index, state, project)

        assert collect_bound_uuids(str(project)).get(_UUID) == "inflight"

    def test_codex_scan_reports_an_in_flight_thread_as_bound(self, tmp_path: Path) -> None:
        """Regression for finding F2.

        collect_bound_codex_threads read only manifests, so during the window
        between the row and its manifest an adopted thread looked free -- the one
        direction a uniqueness check must never err in.
        """
        project = _project(tmp_path)
        index = IndexStore()
        state = _state("inflight", project)
        state.confirmed.codex = CodexConfirmed(thread_id=_THREAD)
        _seed_residue(index, state, project)

        assert collect_bound_codex_threads(str(project)).get(_THREAD) == "inflight"


class TestPerPathResidue:
    """No creation path may leave an orphan manifest when its commit fails."""

    @staticmethod
    def _fail_commit(index: IndexStore, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("commit failed")

        monkeypatch.setattr(index, "create_session_txn", _boom)

    def test_start_session_leaves_no_orphan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        self._fail_commit(index, monkeypatch)

        with pytest.raises(RuntimeError, match="commit failed"):
            manager.start_session("doomed", worktree_path=str(project), direct=True)

        assert not SessionStore(str(project), "doomed").exists()
        assert index.read().sessions == {}

    def test_resume_child_leaves_no_orphan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("parent", worktree_path=str(project), direct=True)
        self._fail_commit(index, monkeypatch)

        with pytest.raises(RuntimeError, match="commit failed"):
            manager.resume_session("parent", child_name="doomed", forge_root=str(project))

        assert not SessionStore(str(project), "doomed").exists()
        assert "doomed" not in {name for name, _ in index.list_sessions()}

    def test_relaunch_leaves_no_orphan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("parent", worktree_path=str(project), direct=True)
        self._fail_commit(index, monkeypatch)

        with pytest.raises(RuntimeError, match="commit failed"):
            manager.relaunch_session("parent", child_name="doomed", forge_root=str(project))

        assert not SessionStore(str(project), "doomed").exists()
        assert "doomed" not in {name for name, _ in index.list_sessions()}

    def test_fork_leaves_no_orphan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("parent", worktree_path=str(project), direct=True)
        self._fail_commit(index, monkeypatch)

        with pytest.raises(RuntimeError, match="commit failed"):
            manager.fork_session("parent", "doomed")

        assert not SessionStore(str(project), "doomed").exists()
        assert "doomed" not in {name for name, _ in index.list_sessions()}


class TestExplicitRetryPerPath:
    """Finding F1: the pre-checks must let a residue name through to the transaction."""

    def test_resume_child_explicit_name_retry_succeeds(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("parent", worktree_path=str(project), direct=True)
        _seed_residue(index, _state("wanted", project), project)

        child, _ = manager.resume_session("parent", child_name="wanted", forge_root=str(project))

        assert child.name == "wanted"
        assert SessionStore(str(project), "wanted").exists()

    def test_relaunch_explicit_name_retry_succeeds(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("parent", worktree_path=str(project), direct=True)
        _seed_residue(index, _state("wanted", project), project)

        _, child = manager.relaunch_session("parent", child_name="wanted", forge_root=str(project))

        assert child.name == "wanted"
        assert SessionStore(str(project), "wanted").exists()
