"""Regression: every session delete failed when FORGE_HOME was a symlink.

Bug: session_cleanup_symlinked_forge_home.
Root cause: ``cleanup_state_path`` returned the retry inventory beneath the
unresolved FORGE_HOME spelling, while the descriptor walk that reads and
publishes that inventory refuses every symlinked path component. A relocated
Forge home (for example ``~/.forge -> /Volumes/data/forge``) therefore made
delete, purge, clean and incognito cleanup fail before removing anything.

Fix: canonicalize the operator-selected home once; components beneath it still
refuse symlinks. Worktree removal also protects the selected home spelling and
its target, so it cannot delete the symlink and redirect later index writes.

Affected: src/forge/session/cleanup_state.py, src/forge/session/deletion.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.session import SessionManager, SessionStore, deletion
from forge.session.cleanup_state import cleanup_state_path
from forge.session.deletion import apply_session_deletion, plan_session_deletion
from forge.session.exceptions import ForgeSessionError
from forge.session.index import IndexStore
from forge.session.models import create_session_state
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    real_home = tmp_path / "volume" / "forge"
    real_home.mkdir(parents=True)
    linked_home = tmp_path / "forge-home"
    linked_home.symlink_to(real_home, target_is_directory=True)
    monkeypatch.setenv("FORGE_HOME", str(linked_home))
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".forge").mkdir()
    return root


def test_delete_completes_under_symlinked_forge_home(project: Path) -> None:
    index = IndexStore()
    manager = SessionManager(index_store=index)
    manager.start_session("victim", worktree_path=str(project), direct=True)

    manager.delete_session("victim", forge_root=str(project), delete_worktree=False)

    assert index.read().sessions == {}
    assert not SessionStore(str(project), "victim").exists()


def test_interrupted_delete_retries_through_canonical_inventory(
    tmp_path: Path, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = IndexStore()
    SessionManager(index_store=index).start_session("victim", worktree_path=str(project), direct=True)
    plan = plan_session_deletion(index, "victim", forge_root=str(project), delete_worktree=False)
    with monkeypatch.context() as patch:
        patch.setattr(deletion, "apply_forge_content", Mock(side_effect=OSError("interrupted cleanup")))
        with pytest.raises(ForgeSessionError, match="interrupted cleanup"):
            apply_session_deletion(index, plan)

    retry_path = cleanup_state_path(project, "victim")
    assert retry_path.is_relative_to((tmp_path / "volume" / "forge").resolve())
    assert retry_path.is_file()

    retry = plan_session_deletion(index, "victim", forge_root=str(project), delete_worktree=False)
    assert retry.retry
    apply_session_deletion(index, retry)
    assert not retry_path.exists()
    assert not SessionStore(str(project), "victim").exists()


@pytest.fixture
def checkout(git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from forge.session import purge_native

    # This fixture owns no live runtime; exercise storage protection independently
    # of the developer machine's process census.
    monkeypatch.setattr(deletion, "check_native_inactivity", lambda runtime: ())
    monkeypatch.setattr(purge_native, "check_native_inactivity", lambda runtime: ())
    path = tmp_path / "checkout"
    subprocess.run(["git", "worktree", "add", "-b", "victim", str(path)], cwd=git_repo, check=True, capture_output=True)
    return path


def _publish_checkout(checkout: Path, git_repo: Path) -> tuple[IndexStore, SessionStore]:
    state = create_session_state("victim", worktree_path=str(checkout), worktree_branch="victim")
    state.forge_root = str(checkout)
    assert state.worktree is not None
    state.worktree.is_worktree = True
    index = IndexStore()
    publish_session(index, state, git_repo, forge_root=checkout)
    return index, SessionStore(str(checkout), "victim")


@pytest.mark.parametrize("layout", ["link-inside", "target-inside", "home-ancestor"])
@pytest.mark.parametrize("purge", [False, True])
def test_forced_worktree_removal_preserves_selected_home_and_target(
    checkout: Path, git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str, purge: bool
) -> None:
    actual_home = {
        "link-inside": tmp_path / "external-forge-home",
        "target-inside": checkout / "actual-forge-home",
        "home-ancestor": checkout.parent,
    }[layout]
    actual_home.mkdir(exist_ok=True)
    selected_home = checkout / "home-link" if layout == "link-inside" else tmp_path / "home-link"
    selected_home.symlink_to(actual_home, target_is_directory=True)
    monkeypatch.setenv("FORGE_HOME", str(selected_home))
    retained = actual_home / "retained-config.json"
    retained.write_bytes(b'{"fixture": "original Forge home"}\n')
    index, store = _publish_checkout(checkout, git_repo)
    original_index = actual_home / "sessions/index.json"
    before = {path: path.read_bytes() for path in (retained, original_index, store.manifest_path)}

    plan = plan_session_deletion(index, "victim", forge_root=str(checkout), force=True, purge=purge)
    assert any("Forge home" in reason and "--keep-worktree" in reason for reason in plan.refusals)
    with pytest.raises(ForgeSessionError, match="Forge home"):
        apply_session_deletion(index, plan)

    assert checkout.is_dir()
    assert selected_home.is_symlink() and selected_home.resolve() == actual_home
    assert all(path.read_bytes() == data for path, data in before.items())
    assert not cleanup_state_path(checkout, "victim").exists()

    retained_plan = plan_session_deletion(
        index, "victim", forge_root=str(checkout), force=True, purge=purge, delete_worktree=False
    )
    assert not retained_plan.refusals
    apply_session_deletion(index, retained_plan)
    assert checkout.is_dir()
    assert selected_home.is_symlink() and selected_home.resolve() == actual_home
    assert retained.read_bytes() == before[retained]
    assert not store.exists()


@pytest.mark.parametrize("retry", [False, True])
def test_selected_home_changed_after_preview_refuses_without_removal(
    checkout: Path, git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retry: bool
) -> None:
    actual_home = tmp_path / "external-forge-home"
    actual_home.mkdir()
    selected_home = checkout / "home-link"
    selected_home.symlink_to(actual_home, target_is_directory=True)
    monkeypatch.setenv("FORGE_HOME", str(actual_home))
    index, store = _publish_checkout(checkout, git_repo)
    plan = plan_session_deletion(index, "victim", forge_root=str(checkout), force=True)
    assert not plan.refusals
    if retry:
        with monkeypatch.context() as patch:
            patch.setattr(deletion, "apply_forge_content", Mock(side_effect=OSError("interrupted cleanup")))
            with pytest.raises(ForgeSessionError, match="interrupted cleanup"):
                apply_session_deletion(index, plan)
        plan = plan_session_deletion(index, "victim", forge_root=str(checkout), force=True)
        assert plan.retry and not plan.refusals
    inventory = cleanup_state_path(checkout, "victim")
    paths = [store.manifest_path, index.index_path, *([inventory] if retry else [])]
    before = {path: path.read_bytes() for path in paths}

    monkeypatch.setenv("FORGE_HOME", str(selected_home))
    with pytest.raises(ForgeSessionError, match="Forge home"):
        apply_session_deletion(index, plan)
    assert checkout.is_dir()
    assert selected_home.is_symlink() and selected_home.resolve() == actual_home
    assert all(path.read_bytes() == data for path, data in before.items())
    assert inventory.exists() == retry

    # A new preview, including an interrupted cleanup, exposes the same refusal.
    preview = plan_session_deletion(index, "victim", forge_root=str(checkout), force=True)
    assert preview.retry == retry
    recovery = "restore the original FORGE_HOME path" if retry else "--keep-worktree"
    assert any("Forge home" in reason and recovery in reason for reason in preview.refusals)

    # Restoring the original home spelling keeps the saved retry options valid.
    monkeypatch.setenv("FORGE_HOME", str(actual_home))
    restored = plan_session_deletion(index, "victim", forge_root=str(checkout), force=True)
    assert restored.retry == retry and not restored.refusals
