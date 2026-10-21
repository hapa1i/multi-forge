"""Cleanup preserves prompt files and plans consumed through legacy parent lookup."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.session import IndexStore, SessionStore, deletion
from forge.session.cleanup_dependencies import find_cleanup_dependencies
from forge.session.cleanup_state import cleanup_state_path
from forge.session.deletion import apply_session_deletion, plan_session_deletion
from forge.session.exceptions import ForgeSessionError
from forge.session.launch import resolve_manifest_prompt_file
from forge.session.models import SystemPromptIntent, create_session_state
from forge.session.plan_resolution import resolve_displayed_plan_path, resolve_plan_info
from tests.fixtures.session_state import publish_session, remove_index_row_only

pytestmark = pytest.mark.regression


def _publish_parent(index: IndexStore, root: Path, project: Path, relative: str = "app-a") -> Path:
    root.mkdir(parents=True)
    snapshot = root / ".forge/artifacts/subject/plans/approved.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("approved plan\n")
    state = create_session_state("subject", worktree_path=str(root.parent))
    state.forge_root = str(root)
    state.confirmed.artifacts["plans"] = [{"kind": "approved", "snapshot_path": str(snapshot.relative_to(root))}]
    publish_session(index, state, project, forge_root=root, checkout_root=root.parent, relative_path=relative)
    return snapshot


def _index_snapshot(index: IndexStore) -> tuple[bytes, int]:
    return index.index_path.read_bytes(), index.index_path.stat().st_mtime_ns


def _assert_refusal(
    index: IndexStore,
    root: Path,
    snapshot: Path,
    phase: str,
    add_borrower: Callable[[], None],
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for method in ("get_session", "list_sessions"):
        monkeypatch.setattr(
            index, method, Mock(side_effect=AssertionError("cleanup must not use self-healing lookups"))
        )
    if phase == "preview":
        add_borrower()
    before = _index_snapshot(index)
    plan = plan_session_deletion(index, "subject", forge_root=str(root), delete_worktree=False)
    assert _index_snapshot(index) == before
    retry_path = cleanup_state_path(root, "subject")
    if phase == "retry":
        with monkeypatch.context() as patch:
            patch.setattr(deletion, "apply_forge_content", Mock(side_effect=OSError("interrupted cleanup")))
            with pytest.raises(ForgeSessionError, match="interrupted cleanup"):
                apply_session_deletion(index, plan)
        assert retry_path.exists()
    if phase != "preview":
        add_borrower()
    before = _index_snapshot(index)
    if phase == "retry":
        plan = plan_session_deletion(index, "subject", forge_root=str(root), delete_worktree=False)
        assert plan.retry
        assert _index_snapshot(index) == before
    if phase != "apply":
        assert any("borrower" in refusal and reason in refusal for refusal in plan.refusals)
    manifest = SessionStore(str(root), "subject").manifest_path.read_bytes()
    with pytest.raises(ForgeSessionError, match=f"borrower.*{reason}"):
        apply_session_deletion(index, plan)
    assert _index_snapshot(index) == before
    assert snapshot.read_text() == "approved plan\n"
    assert SessionStore(str(root), "subject").manifest_path.read_bytes() == manifest
    assert retry_path.exists() == (phase == "retry")


@pytest.mark.parametrize("phase", ["preview", "apply", "retry"])
@pytest.mark.parametrize("anchor", ["absolute", "forge-root", "worktree", "recorded-launch", "caller"])
def test_system_prompt_borrower_preserves_owned_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, anchor: str
) -> None:
    index = IndexStore()
    root, borrower_root = tmp_path / "main/app-a", tmp_path / "fork/app-a"
    snapshot = _publish_parent(index, root, root.parent)
    monkeypatch.chdir(tmp_path)

    def add_borrower() -> None:
        borrower_root.mkdir(parents=True)
        launch_root = tmp_path / "historical/launch"
        launch_root.mkdir(parents=True)
        state = create_session_state("borrower", worktree_path=str(borrower_root.parent))
        state.forge_root = str(borrower_root)
        state.confirmed.claude_project_root = str(launch_root)
        prompt_root = {
            "absolute": borrower_root,
            "forge-root": borrower_root,
            "worktree": borrower_root.parent,
            "recorded-launch": launch_root,
            "caller": tmp_path,
        }[anchor]
        value = str(snapshot) if anchor == "absolute" else os.path.relpath(snapshot, prompt_root)
        state.intent.system_prompt = SystemPromptIntent(file=value)
        publish_session(index, state, borrower_root, forge_root=borrower_root)
        with monkeypatch.context() as patch:
            patch.chdir(prompt_root)
            assert resolve_manifest_prompt_file(SessionStore(str(borrower_root), "borrower").read()) == snapshot

    _assert_refusal(index, root, snapshot, phase, add_borrower, "content reference", monkeypatch)


@pytest.mark.parametrize("phase", ["preview", "apply", "retry"])
@pytest.mark.parametrize("scope", ["cross-worktree", "other-project", "relative-project", "ambiguous"])
def test_legacy_parent_plan_dependency_uses_read_only_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, scope: str
) -> None:
    index = IndexStore()
    project = tmp_path / "main"
    root, borrower_root = project / "app-a", tmp_path / "fork/app-a"
    snapshot = _publish_parent(index, root, project)
    decoy_root: Path | None = None
    if scope == "other-project":
        decoy_root = tmp_path / "other/app-a"
        _publish_parent(index, decoy_root, decoy_root.parent)
    elif scope == "relative-project":
        decoy_root = project / "app-b"
        _publish_parent(index, decoy_root, project, "app-b")
    elif scope == "ambiguous":
        decoy_root = tmp_path / "another-fork/app-a"
        _publish_parent(index, decoy_root, project)

    def add_borrower() -> None:
        borrower_root.mkdir(parents=True)
        state = create_session_state(
            "borrower", parent_session="subject", is_fork=True, worktree_path=str(borrower_root.parent)
        )
        state.forge_root = str(borrower_root)
        assert state.confirmed.derivation is None
        publish_session(
            index, state, project, forge_root=borrower_root, checkout_root=borrower_root.parent, relative_path="app-a"
        )
        info = resolve_plan_info(state, current_forge_root=str(borrower_root))
        if scope == "ambiguous":
            assert info.source is None
        else:
            assert info.source == "parent"
            resolved = resolve_displayed_plan_path(info, current_forge_root=str(borrower_root))
            assert resolved is not None and resolved.exists and resolved.path == str(snapshot)
        if decoy_root is not None:
            before = _index_snapshot(index)
            other = plan_session_deletion(index, "subject", forge_root=str(decoy_root), delete_worktree=False)
            if scope == "ambiguous":
                assert any(
                    "borrower" in refusal and "ambiguous legacy parent/lineage" in refusal for refusal in other.refusals
                )
            else:
                assert not other.refusals
            assert _index_snapshot(index) == before

    reason = "ambiguous legacy parent/lineage" if scope == "ambiguous" else "parent/lineage"
    _assert_refusal(index, root, snapshot, phase, add_borrower, reason, monkeypatch)


def test_ambiguous_legacy_parent_preserves_local_orphan_fallback(tmp_path: Path) -> None:
    index = IndexStore()
    project = tmp_path / "main"
    root = tmp_path / "fork/app-a"
    snapshot = _publish_parent(index, root, project)
    # The local parent is deliberately orphaned: legacy plan resolution still
    # reads its manifest when duplicate indexed parents cannot be resolved.
    remove_index_row_only(index, "subject", root)
    _publish_parent(index, project / "app-a", project)
    _publish_parent(index, tmp_path / "other-fork/app-a", project)
    child = create_session_state("borrower", parent_session="subject", is_fork=True, worktree_path=str(root.parent))
    child.forge_root = str(root)
    publish_session(index, child, project, forge_root=root, checkout_root=root.parent, relative_path="app-a")
    info = resolve_plan_info(child, current_forge_root=str(root))
    resolved = resolve_displayed_plan_path(info, current_forge_root=str(root))
    assert info.source == "parent" and resolved is not None
    assert resolved.path == str(snapshot) and resolved.exists
    before = _index_snapshot(index)
    orphan = SessionStore(str(root), "subject")
    manifest = orphan.manifest_path.read_bytes()

    dependencies = find_cleanup_dependencies(index, orphan.read(), forge_root=str(root))

    assert any("borrower" in reason and "ambiguous legacy parent/lineage" in reason for reason in dependencies)
    assert _index_snapshot(index) == before
    assert orphan.manifest_path.read_bytes() == manifest
    assert snapshot.read_text() == "approved plan\n"
