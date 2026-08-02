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
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from forge.core.ops.session_context import (
    collect_bound_codex_threads,
    collect_bound_uuids,
)
from forge.core.state.lock import FileLockTimeoutError
from forge.session import SessionManager, SessionStore, create_session_state
from forge.session import index as index_mod
from forge.session import store as store_mod
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


def _mark(store: SessionStore, uuid: str) -> None:
    """Tag a manifest so a replacement is distinguishable from it.

    `created_at` cannot serve: `now_iso` has second granularity, so two sessions
    minted in the same second have byte-identical manifests.
    """
    state = store.read()
    state.confirmed.claude_session_id = uuid
    store.write(state)


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

    def test_a_pre_existing_orphan_manifest_does_not_count_as_our_publication(self, tmp_path: Path) -> None:
        """Review finding: manifest presence is not proof of ownership.

        `create_exclusive` rejects the callback precisely because somebody else's
        manifest already owns the path. Probing "is a manifest there?" after the
        failure sees that orphan and reads it as ours, leaving our row indexing a
        session we did not create.
        """
        project = _project(tmp_path)
        index = IndexStore()

        orphan = _state("contested", project)
        orphan.confirmed.claude_session_id = "winner-id"
        SessionStore(str(project), "contested").create_exclusive(orphan)
        assert index.read().sessions == {}, "an orphan manifest: no row of its own"

        mine = _state("contested", project)
        store = SessionStore(str(project), "contested")

        with pytest.raises(SessionExistsError):
            index.create_session_txn(
                mine,
                str(project),
                forge_root=str(project),
                write_manifest=lambda: store.create_exclusive(mine),
            )

        assert index.read().sessions == {}, "no row may point at the orphan's manifest"
        assert store.read().confirmed.claude_session_id == "winner-id", "the orphan is untouched"

    def test_a_failed_compensation_raising_basexception_still_preserves_the_callback_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The never-raises guarantee must hold for BaseException too."""
        project = _project(tmp_path)
        index = IndexStore()
        real_write = IndexStore.write
        seen: list[int] = []

        def _flaky_write(self: IndexStore, payload: object) -> None:
            seen.append(1)
            if len(seen) == 2:
                raise KeyboardInterrupt("interrupt during compensation")
            real_write(self, payload)  # type: ignore[arg-type]

        monkeypatch.setattr(IndexStore, "write", _flaky_write)

        def _fail() -> None:
            raise SessionExistsError("doomed")

        with pytest.raises(SessionExistsError):
            index.create_session_txn(
                _state("doomed", project),
                str(project),
                forge_root=str(project),
                write_manifest=_fail,
            )

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
        """Fail the *manifest callback*, driving the real transaction.

        Replacing `create_session_txn` outright would prove only that the caller
        writes nothing on its own; routing through the real transaction exercises
        the uniqueness checks, the row write, and the compensation path that each
        creation site now depends on instead of its own rollback block.
        """
        real = index.create_session_txn

        def _boom() -> None:
            raise RuntimeError("commit failed")

        def _with_failing_manifest(state: SessionState, project_root: str, **kwargs: object) -> object:
            kwargs["write_manifest"] = _boom
            return real(state, project_root, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(index, "create_session_txn", _with_failing_manifest)

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


class TestInterruptAfterTheManifestLands:
    """A raised callback does not prove the manifest is absent.

    Review finding: `atomic_write_json` makes the manifest durable at `os.replace`
    (`core/state/io.py:146`); a signal arriving during the directory fsync or the
    manifest lock release still unwinds through the transaction's except clause.
    Compensating unconditionally there produced the exact manifest-only orphan
    this card exists to prevent.
    """

    def test_signal_after_the_manifest_is_durable_leaves_no_orphan(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        state = _state("interrupted", project)
        store = SessionStore(str(project), "interrupted")

        def _write_then_interrupt() -> None:
            store.create_exclusive(state)
            raise KeyboardInterrupt("signal after os.replace")

        with pytest.raises(KeyboardInterrupt):
            index.create_session_txn(
                state,
                str(project),
                forge_root=str(project),
                write_manifest=_write_then_interrupt,
            )

        assert store.exists(), "the manifest is durable once os.replace returned"
        assert index.read().sessions, "so its row must survive -- a bare manifest is the orphan"

    def test_failure_before_the_manifest_still_compensates(self, tmp_path: Path) -> None:
        """The companion case: no manifest landed, so the row must go."""
        project = _project(tmp_path)
        index = IndexStore()

        def _fail_first() -> None:
            raise KeyboardInterrupt("signal before the write")

        with pytest.raises(KeyboardInterrupt):
            index.create_session_txn(
                _state("interrupted", project),
                str(project),
                forge_root=str(project),
                write_manifest=_fail_first,
            )

        assert not SessionStore(str(project), "interrupted").exists()
        assert index.read().sessions == {}, "nothing landed, so nothing may be left published"


class TestCompensationFailure:
    """Compensation must not replace the error it is unwinding."""

    def test_a_failed_compensation_write_preserves_the_callback_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        real_write = IndexStore.write
        seen: list[int] = []

        def _flaky_write(self: IndexStore, payload: object) -> None:
            seen.append(1)
            if len(seen) == 2:  # the compensation write
                raise OSError("disk full during compensation")
            real_write(self, payload)  # type: ignore[arg-type]

        monkeypatch.setattr(IndexStore, "write", _flaky_write)

        def _fail() -> None:
            raise SessionExistsError("doomed")

        with pytest.raises(SessionExistsError):
            index.create_session_txn(
                _state("doomed", project),
                str(project),
                forge_root=str(project),
                write_manifest=_fail,
            )

        monkeypatch.undo()
        assert index.list_sessions() == [], "the row it could not remove is prunable"


class TestDeleteCreateCoordination:
    """Row-without-manifest is also produced by an in-flight delete, not only a crash.

    Review finding: `delete_session` removes the manifest -- or the worktree
    holding it -- before its row, and the transcript cleanup in between keeps that
    window open. A concurrent creator reclaims the name and publishes; the deleter
    must then not remove the replacement's row and manifest.
    """

    def test_delete_declines_once_a_replacement_owns_the_name(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("victim", worktree_path=str(project), direct=True, claude_session_id="o" * 8)

        entry = index.get_session("victim", forge_root=str(project))
        forge_root = entry.forge_root or entry.worktree_path
        store = SessionStore(forge_root, "victim")
        store.delete()  # what worktree cleanup does to a nested project

        replacement = manager.start_session(
            "victim", worktree_path=str(project), direct=True, claude_session_id="n" * 8
        )

        deleted: list[int] = []
        proceeded = index.delete_session_txn(
            "victim",
            forge_root=forge_root,
            expect_manifest_absent=True,
            delete_manifest=lambda: deleted.append(1),
        )

        assert proceeded is False, "the deleter must recognise it no longer owns the name"
        assert deleted == [], "and must not reach its manifest delete"
        survivor = SessionStore(forge_root, "victim")
        assert survivor.exists(), "the replacement's manifest must survive"
        assert survivor.read().confirmed.claude_session_id == replacement.confirmed.claude_session_id
        assert index.live_session_exists("victim", forge_root=forge_root), "and its row must survive"

    def test_delete_proceeds_when_nothing_reclaimed_the_name(self, tmp_path: Path) -> None:
        """Companion: the guard must not block ordinary deletion."""
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("solo", worktree_path=str(project), direct=True)

        entry = index.get_session("solo", forge_root=str(project))
        forge_root = entry.forge_root or entry.worktree_path
        store = SessionStore(forge_root, "solo")
        store.delete()

        assert (
            index.delete_session_txn(
                "solo",
                forge_root=forge_root,
                expect_manifest_absent=True,
                delete_manifest=lambda: None,
            )
            is True
        )
        assert index.read().sessions == {}

    def test_manifest_delete_runs_inside_the_index_lock(self, tmp_path: Path) -> None:
        """No creator may publish between the ownership check and the manifest delete.

        Review finding: with the delete outside the lock, a replacement landing in
        that gap kept its row and lost its manifest.
        """
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("victim", worktree_path=str(project), direct=True)
        entry = index.get_session("victim", forge_root=str(project))
        forge_root = entry.forge_root or entry.worktree_path
        SessionStore(forge_root, "victim").delete()

        blocked: list[str] = []

        def _try_to_publish_from_inside() -> None:
            # A creator needs the index lock, which this callback is running under,
            # so it cannot get in. Prove it by observing the timeout rather than a
            # successful publication.
            def _racer() -> None:
                try:
                    SessionManager().start_session("victim", worktree_path=str(project), direct=True)
                    blocked.append("published")
                except FileLockTimeoutError:
                    blocked.append("blocked")
                except BaseException as e:  # noqa: BLE001 - surfaced in the assertion
                    blocked.append(type(e).__name__)

            racer = threading.Thread(target=_racer)
            racer.start()
            racer.join(timeout=30)

        assert (
            index.delete_session_txn(
                "victim",
                forge_root=forge_root,
                expect_manifest_absent=True,
                delete_manifest=_try_to_publish_from_inside,
            )
            is True
        )
        assert blocked == ["blocked"], f"a concurrent create must not slip in, got {blocked}"

    def test_ordinary_delete_with_its_manifest_still_present_proceeds(self, tmp_path: Path) -> None:
        """Non-worktree deletion never opens the window, so the guard is inert."""
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("plain", worktree_path=str(project), direct=True)

        manager.delete_session("plain", forge_root=str(project), delete_worktree=False)

        assert index.read().sessions == {}
        assert not SessionStore(str(project), "plain").exists()

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

    def test_delete_session_spares_a_session_published_during_its_cleanup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end through `delete_session`, with the real early-removal path.

        `cleanup_worktree` is stubbed to do what it does to a nested project --
        take the manifest with the worktree -- and then a replacement is published
        while the delete is still in its transcript phase.
        """
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("victim", worktree_path=str(project), direct=True, claude_session_id="o" * 8)

        # Mark the session as owning a worktree so delete_session takes the cleanup arm.
        store = SessionStore(str(project), "victim")
        state = store.read()
        assert state.worktree is not None
        state.worktree.is_worktree = True
        store.write(state)

        published: dict[str, str] = {}

        class _Result:
            errors: list[str] = []

        def _cleanup_takes_the_manifest(**kwargs: object) -> _Result:
            SessionStore(str(project), "victim").delete()
            return _Result()

        def _publish_during_transcript_phase(*args: object, **kwargs: object) -> list[str]:
            # Stands in for the slow transcript work that keeps the window open.
            if "uuid" not in published:
                replacement = manager.start_session(
                    "victim", worktree_path=str(project), direct=True, claude_session_id="n" * 8
                )
                published["uuid"] = replacement.confirmed.claude_session_id or ""
            return []

        monkeypatch.setattr("forge.session.worktree.cleanup_worktree", _cleanup_takes_the_manifest)
        monkeypatch.setattr(SessionManager, "_find_shared_transcript_sessions", _publish_during_transcript_phase)

        manager.delete_session("victim", forge_root=str(project), force=True)

        assert published.get("uuid") == "n" * 8, "the replacement must actually have been published"
        survivor = SessionStore(str(project), "victim")
        assert survivor.exists(), "delete_session must not remove the replacement's manifest"
        assert survivor.read().confirmed.claude_session_id == "n" * 8
        assert index.live_session_exists("victim", forge_root=str(project)), "nor its row"

    def test_delete_session_spares_a_session_published_inside_worktree_cleanup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The earliest schedule: the replacement lands before any probe could run.

        Review finding: an `expect_manifest_absent` sampled by observing the
        filesystem was already looking at the replacement's manifest here, read it
        as this delete's own, and destroyed both halves of the new session. The
        flag has to be derived from what the delete does, not from what it sees.
        """
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("victim", worktree_path=str(project), direct=True, claude_session_id="o" * 8)

        store = SessionStore(str(project), "victim")
        state = store.read()
        assert state.worktree is not None
        state.worktree.is_worktree = True
        store.write(state)

        published: dict[str, str] = {}

        class _Result:
            errors: list[str] = []

        def _cleanup_then_publish(**kwargs: object) -> _Result:
            SessionStore(str(project), "victim").delete()
            replacement = manager.start_session(
                "victim", worktree_path=str(project), direct=True, claude_session_id="n" * 8
            )
            published["uuid"] = replacement.confirmed.claude_session_id or ""
            return _Result()

        monkeypatch.setattr("forge.session.worktree.cleanup_worktree", _cleanup_then_publish)

        manager.delete_session("victim", forge_root=str(project), force=True)

        assert published.get("uuid") == "n" * 8
        survivor = SessionStore(str(project), "victim")
        assert survivor.exists(), "the replacement's manifest must survive"
        assert survivor.read().confirmed.claude_session_id == "n" * 8
        assert index.live_session_exists("victim", forge_root=str(project)), "and its row"


class TestForkStaleTargetReplacement:
    """`fork --force` reaches the same delete/create window through its own path.

    Review finding: after `delete_session` frees the stale target, fork cleared
    whatever manifest was left at the name with an unconditional
    `stale_store.delete()`. A creator that claimed the freed name in between lost
    its manifest, and fork's own transaction then read the survivor's row as crash
    residue, pruned it, and published over it -- fork silently destroying a live
    session and taking its name.
    """

    def test_fork_declines_when_a_replacement_claims_the_freed_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("parent", worktree_path=str(project), direct=True)
        manager.fork_session("parent", "target")

        published: dict[str, str] = {}
        real_delete = SessionManager.delete_session

        def _publish_after_the_stale_delete(inner: SessionManager, name: str, **kwargs: Any) -> object:
            result = real_delete(inner, name, **kwargs)
            if name == "target" and "uuid" not in published:
                replacement = SessionManager(index_store=index).start_session(
                    "target", worktree_path=str(project), direct=True, claude_session_id="n" * 8
                )
                published["uuid"] = replacement.confirmed.claude_session_id or ""
            return result

        monkeypatch.setattr(SessionManager, "delete_session", _publish_after_the_stale_delete)

        with pytest.raises(SessionExistsError):
            manager.fork_session("parent", "target", force=True)

        assert published.get("uuid") == "n" * 8, "the replacement must actually have been published"
        survivor = SessionStore(str(project), "target")
        assert survivor.exists(), "fork must not destroy the replacement's manifest"
        assert survivor.read().confirmed.claude_session_id == "n" * 8
        assert index.live_session_exists("target", forge_root=str(project)), "nor prune its row"

    def test_fork_force_still_replaces_an_ordinary_stale_target(self, tmp_path: Path) -> None:
        """Companion: with nobody racing, `--force` must still swap the target."""
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("parent", worktree_path=str(project), direct=True)
        manager.fork_session("parent", "target")
        _mark(SessionStore(str(project), "target"), "s" * 8)

        manager.fork_session("parent", "target", force=True)

        replaced = SessionStore(str(project), "target")
        assert replaced.exists()
        assert replaced.read().confirmed.claude_session_id != "s" * 8, "the stale target must be gone"
        assert index.live_session_exists("target", forge_root=str(project))

    def test_fork_force_still_clears_a_pre_existing_orphan_manifest(self, tmp_path: Path) -> None:
        """A manifest with no row predates the window and stays fork's to clear."""
        project = _project(tmp_path)
        index = IndexStore()
        manager = SessionManager(index_store=index)
        manager.start_session("parent", worktree_path=str(project), direct=True)
        manager.fork_session("parent", "target")
        _mark(SessionStore(str(project), "target"), "o" * 8)
        index.remove_session("target", forge_root=str(project))

        manager.fork_session("parent", "target", force=True)

        replaced = SessionStore(str(project), "target")
        assert replaced.exists()
        assert replaced.read().confirmed.claude_session_id != "o" * 8, "the orphan must be reclaimed"
        assert index.live_session_exists("target", forge_root=str(project))


class TestConcurrentCreate:
    """Two real creators racing one name, gated on a barrier."""

    def test_barrier_gated_double_create_has_one_winner_and_no_orphan(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        barrier = threading.Barrier(2)
        results: list[tuple[str, object]] = []
        lock = threading.Lock()

        def _create(uuid: str) -> None:
            manager = SessionManager()  # separate stores, as separate processes would have
            barrier.wait(timeout=10)
            try:
                manager.start_session("contested", worktree_path=str(project), direct=True, claude_session_id=uuid)
                outcome: tuple[str, object] = ("won", uuid)
            except SessionExistsError as e:
                outcome = ("lost", e)
            except BaseException as e:  # surface anything unexpected in the assertions
                outcome = ("error", e)
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=_create, args=("a" * 8,)), threading.Thread(target=_create, args=("b" * 8,))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        outcomes = sorted(kind for kind, _ in results)
        assert outcomes == ["lost", "won"], f"expected exactly one winner, got {results}"

        index = IndexStore()
        store = SessionStore(str(project), "contested")
        assert store.exists(), "the winner's manifest must be on disk"
        assert len(index.read().sessions) == 1, "and exactly one row must be published"
        winner_uuid = next(uuid for kind, uuid in results if kind == "won")
        assert store.read().confirmed.claude_session_id == winner_uuid, "the loser must not have clobbered it"
        assert index.live_session_exists("contested", forge_root=str(project))


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
