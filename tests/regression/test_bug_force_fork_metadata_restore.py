"""Failed force replacement cannot resurrect metadata for already removed content."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from forge.session import IndexStore, SessionManager, SessionStore
from forge.session.exceptions import ForgeSessionError
from forge.session.models import SessionState
from forge.session.prev_sessions import child_path

pytestmark = pytest.mark.regression


@dataclass
class StaleFork:
    manager: SessionManager
    root: Path
    options: dict[str, Any]
    artifact: Path
    transfer: Path
    native: Path
    manifest: bytes
    index: bytes


@pytest.fixture(params=["same-directory", "into", "owned-worktree"])
def stale_fork(
    request: pytest.FixtureRequest, git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> StaleFork:
    (git_repo / ".forge").mkdir()
    monkeypatch.chdir(git_repo)
    manager = SessionManager(index_store=IndexStore())
    manager.start_session("parent", worktree_path=str(git_repo), direct=True)
    options: dict[str, Any] = {"resume_mode": "transfer"}
    if request.param == "into":
        target = tmp_path / "existing-worktree"
        subprocess.run(
            ["git", "worktree", "add", "-b", "existing", str(target)], cwd=git_repo, check=True, capture_output=True
        )
        (target / ".forge").mkdir()
        options.update(into_path=str(target), branch="existing")
    elif request.param == "owned-worktree":
        options["create_worktree"] = True
    _, child = manager.fork_session("parent", "child", **options)
    assert child.forge_root is not None
    root = Path(child.forge_root)
    native = tmp_path / "original-native.jsonl"
    native.write_bytes(b"retained original native conversation\n")
    artifact = root / ".forge/artifacts/child/transcripts/old.jsonl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"previous captured conversation\n")
    store = SessionStore(str(root), "child")
    state = store.read()
    state.confirmed.artifacts["transcripts"] = [
        {
            "session_id": "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
            "source_path": str(native),
            "copied_path": str(artifact.relative_to(root)),
            "copied": True,
        }
    ]
    store.write(state)
    transfer = child_path(root, "parent", "child")
    transfer.parent.mkdir(parents=True, exist_ok=True)
    transfer.write_bytes(b"previous editable transfer snapshot\n")
    return StaleFork(
        manager,
        root,
        options,
        artifact,
        transfer,
        native,
        store.manifest_path.read_bytes(),
        manager.index_store.index_path.read_bytes(),
    )


def test_failed_force_publication_does_not_restore_contentless_metadata(
    stale_fork: StaleFork, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = stale_fork
    original = case.manager.index_store.create_session_txn
    failed = False

    def fail_once(state: SessionState, *args: Any, **kwargs: Any) -> Any:
        nonlocal failed
        if state.name == "child" and not failed:
            failed = True
            raise RuntimeError("injected publication failure")
        return original(state, *args, **kwargs)

    monkeypatch.setattr(case.manager.index_store, "create_session_txn", fail_once)
    with pytest.raises(Exception, match="injected publication failure") as failure:
        case.manager.fork_session("parent", "child", force=True, **case.options)

    assert failed
    assert not SessionStore(str(case.root), "child").exists()
    assert not case.manager.index_store.peek_session("child", forge_root=str(case.root))
    assert not case.artifact.exists() and not case.transfer.exists()
    assert case.native.read_bytes() == b"retained original native conversation\n"
    assert isinstance(failure.value, ForgeSessionError)
    assert "already removed" in str(failure.value)
    assert "forge session list --scope all" in str(failure.value)
    if case.options.get("create_worktree"):
        assert not case.root.exists()
    else:
        assert case.root.is_dir()


def test_failure_before_force_cleanup_preserves_old_content(
    stale_fork: StaleFork, monkeypatch: pytest.MonkeyPatch
) -> None:
    from forge.session import deletion

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise ForgeSessionError("injected cleanup refusal")

    monkeypatch.setattr(deletion, "apply_session_deletion", refuse)
    with pytest.raises(ForgeSessionError, match="injected cleanup refusal") as failure:
        stale_fork.manager.fork_session("parent", "child", force=True, **stale_fork.options)
    assert "already removed" not in str(failure.value)
    assert SessionStore(str(stale_fork.root), "child").manifest_path.read_bytes() == stale_fork.manifest
    assert stale_fork.manager.index_store.index_path.read_bytes() == stale_fork.index
    assert stale_fork.artifact.read_bytes() == b"previous captured conversation\n"
    assert stale_fork.transfer.read_bytes() == b"previous editable transfer snapshot\n"
    assert stale_fork.native.read_bytes() == b"retained original native conversation\n"


@pytest.mark.parametrize("stale_fork", ["owned-worktree"], indirect=True)
@pytest.mark.parametrize("failure_point", ["recreate", "config-copy", "preparation"])
def test_owned_replacement_preparation_failure_reports_completed_cleanup(
    stale_fork: StaleFork, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    from forge.session import memory_inheritance, worktree

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"injected {failure_point} failure")

    if failure_point == "recreate":
        monkeypatch.setattr(worktree, "create_worktree", fail)
    elif failure_point == "config-copy":
        monkeypatch.setattr(worktree, "copy_runtime_config", fail)
    else:
        monkeypatch.setattr(memory_inheritance, "apply_memory_inheritance", fail)
    with pytest.raises(ForgeSessionError, match="already removed") as failure:
        stale_fork.manager.fork_session("parent", "child", force=True, **stale_fork.options)
    assert f"injected {failure_point} failure" in str(failure.value)
    assert "forge session list --scope all" in str(failure.value)
    assert "backup" in str(failure.value)
    assert not SessionStore(str(stale_fork.root), "child").exists()
    assert not stale_fork.manager.index_store.peek_session("child", forge_root=str(stale_fork.root))
    assert not stale_fork.root.exists()
    assert not stale_fork.artifact.exists() and not stale_fork.transfer.exists()
    assert stale_fork.native.read_bytes() == b"retained original native conversation\n"


@pytest.mark.parametrize("ownership", ["modern", "legacy-owner", "ownerless"])
@pytest.mark.parametrize("identical_state", [False, True])
@pytest.mark.parametrize("race_phase", ["planning", "apply"])
def test_force_replacement_preserves_owner_that_arrives_before_cleanup(
    stale_fork: StaleFork, monkeypatch: pytest.MonkeyPatch, ownership: str, identical_state: bool, race_phase: str
) -> None:
    from forge.session import deletion
    from forge.session.models import create_session_state
    from tests.fixtures.session_state import delete_published_session, publish_session

    case = stale_fork
    index = case.manager.index_store
    target_store = SessionStore(str(case.root), "child")
    if ownership != "modern":
        # Deliberately model a pre-instance row, with or without a historical review owner.
        raw = index.read()
        for entry in raw.sessions.values():
            if entry.root == str(case.root) and entry.is_fork:
                entry.instance_id = None
        index.write(raw)
        if ownership == "ownerless":
            (target_store.session_dir / "review-identity").unlink()
    previous_state = target_store.read()
    previous_manifest = target_store.manifest_path.read_bytes()
    previous_owner = target_store.review_identity()
    replacement_bytes: dict[Path, bytes] = {}

    def replace_owner(store: IndexStore, name: str) -> None:
        if name == "child" and not replacement_bytes:
            assert delete_published_session(store, name, case.root)
            if identical_state:
                winner = previous_state
            else:
                winner = create_session_state(name, worktree_path=str(case.root))
                winner.forge_root = str(case.root)
                winner.confirmed.claude_session_id = "bbbbbbbb-bbbb-4bbb-abbb-bbbbbbbbbbbb"
            publish_session(store, winner, case.root, forge_root=case.root)
            assert target_store.review_identity() != previous_owner
            if identical_state:
                assert target_store.manifest_path.read_bytes() == previous_manifest
            for path in (
                SessionStore(str(case.root), name).manifest_path,
                store.index_path,
                case.artifact,
                case.transfer,
            ):
                replacement_bytes[path] = path.read_bytes()

    if race_phase == "planning":
        original_plan = deletion.plan_session_deletion

        def replace_before_plan(store: IndexStore, name: str, **kwargs: Any) -> deletion.SessionDeletionPlan:
            replace_owner(store, name)
            return original_plan(store, name, **kwargs)

        monkeypatch.setattr(deletion, "plan_session_deletion", replace_before_plan)
    else:
        original_apply = deletion.apply_session_deletion

        def replace_before_apply(store: IndexStore, plan: deletion.SessionDeletionPlan) -> tuple[str, ...]:
            replace_owner(store, plan.name)
            return original_apply(store, plan)

        monkeypatch.setattr(deletion, "apply_session_deletion", replace_before_apply)
    message = "changed before" if race_phase == "planning" else "changed"
    with pytest.raises(ForgeSessionError, match=message) as failure:
        case.manager.fork_session("parent", "child", force=True, **case.options)
    assert "already removed" not in str(failure.value)
    assert replacement_bytes
    assert all(path.read_bytes() == content for path, content in replacement_bytes.items())
    assert case.native.read_bytes() == b"retained original native conversation\n"
