"""Cleanup admission, exact inventories and interrupted deletion recovery."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import dacite
import pytest

from forge.session import IndexStore, SessionStore
from forge.session.cleanup_state import cleanup_state_path
from forge.session.deletion import (
    SessionDeletionPlan,
    apply_session_deletion,
    plan_session_deletion,
)
from forge.session.exceptions import ForgeSessionError
from forge.session.models import Derivation, create_session_state
from tests.fixtures.session_state import delete_published_session, publish_session


def _publish(root: Path, name: str = "subject", *, parent: Path | None = None):
    root.mkdir(parents=True, exist_ok=True)
    state = create_session_state(name, worktree_path=str(root))
    state.forge_root = str(root)
    if parent is not None:
        state.parent_session = "subject"
        state.confirmed.derivation = Derivation(parent_session="subject", parent_forge_root=str(parent))
    publish_session(IndexStore(), state, root, forge_root=root)
    return state


def _write(path: Path, text: str = "private content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_delete_removes_owned_content_and_preserves_native_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    _publish(root)
    owned = _write(root / ".forge/artifacts/subject/authority/events.jsonl")
    transfer = _write(root / ".forge/prev_sessions/subject/children/old.notes.md", "my notes")
    native = _write(tmp_path / "native/original.jsonl")
    other = _write(root / ".forge/artifacts/another/events.jsonl")
    index = IndexStore()
    before = index.index_path.read_bytes()
    plan = plan_session_deletion(index, "subject", forge_root=str(root), delete_worktree=False)
    assert not plan.refusals
    assert index.index_path.read_bytes() == before
    assert owned.exists() and transfer.exists()
    apply_session_deletion(index, plan)
    assert not owned.exists() and not transfer.exists()
    assert not SessionStore(str(root), "subject").exists()
    assert native.read_text() == other.read_text() == "private content"
    assert not cleanup_state_path(root, "subject").exists()
    _publish(root)
    assert not owned.exists()


def test_inactive_cross_root_child_refuses_before_any_mutation(tmp_path: Path) -> None:
    root, child = tmp_path / "parent", tmp_path / "child"
    _publish(root)
    _publish(child, "child", parent=root)
    owned = _write(root / ".forge/artifacts/subject/report.md")
    index = IndexStore()
    before = index.index_path.read_bytes()
    plan = plan_session_deletion(index, "subject", forge_root=str(root))
    assert any("child" in reason and "parent/lineage" in reason for reason in plan.refusals)
    with pytest.raises(ForgeSessionError, match="depend"):
        apply_session_deletion(index, plan)
    assert owned.read_text() == "private content"
    assert index.index_path.read_bytes() == before


def test_dependency_created_after_preview_refuses(tmp_path: Path) -> None:
    root = tmp_path / "parent"
    _publish(root)
    owned = _write(root / ".forge/artifacts/subject/report.md")
    plan = plan_session_deletion(IndexStore(), "subject", forge_root=str(root))
    _publish(tmp_path / "child", "child", parent=root)
    with pytest.raises(ForgeSessionError, match="depend"):
        apply_session_deletion(IndexStore(), plan)
    assert owned.exists()
    assert not cleanup_state_path(root, "subject").exists()


def test_stale_preview_cannot_delete_replacement_instance(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _publish(root)
    index = IndexStore()
    stale = plan_session_deletion(index, "subject", forge_root=str(root))
    assert delete_published_session(index, "subject", root)
    _publish(root)
    replacement = _write(root / ".forge/artifacts/subject/new.md")
    store = SessionStore(str(root), "subject")
    before = {path: path.read_bytes() for path in (replacement, store.manifest_path, index.index_path)}
    owner = store.review_identity()
    assert owner != stale.instance_id
    # Distinct creation timestamps can trigger the manifest guard before the
    # instance guard. Both refusals must leave the replacement byte-identical.
    with pytest.raises(ForgeSessionError, match="instance changed|manifest changed"):
        apply_session_deletion(index, stale)
    assert all(path.read_bytes() == data for path, data in before.items())
    assert store.review_identity() == owner
    assert not cleanup_state_path(root, "subject").exists()


def test_failure_keeps_inventory_and_retry_reuses_original_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import forge.session.deletion as deletion

    root = tmp_path / "project"
    _publish(root)
    owned = _write(root / ".forge/artifacts/subject/report.md")
    index = IndexStore()
    plan = plan_session_deletion(index, "subject", forge_root=str(root), delete_worktree=False)
    original = deletion.apply_forge_content
    monkeypatch.setattr(deletion, "apply_forge_content", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(ForgeSessionError, match="disk failure"):
        apply_session_deletion(index, plan)
    retry_file = cleanup_state_path(root, "subject")
    assert retry_file.exists() and owned.exists()
    saved = json.loads(retry_file.read_text())
    assert saved["instance_id"] == plan.instance_id
    monkeypatch.setattr(deletion, "apply_forge_content", original)
    retry = plan_session_deletion(index, "subject", forge_root=str(root), delete_worktree=False)
    assert retry.retry and retry.content == plan.content
    apply_session_deletion(index, retry)
    assert not owned.exists() and not retry_file.exists()


def test_retry_refuses_new_unapproved_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.session.deletion as deletion

    root = tmp_path / "project"
    _publish(root)
    first = _write(root / ".forge/artifacts/subject/first.md")
    plan = plan_session_deletion(IndexStore(), "subject", forge_root=str(root))
    original = deletion.apply_forge_content
    monkeypatch.setattr(deletion, "apply_forge_content", Mock(side_effect=OSError("injected")))
    with pytest.raises(ForgeSessionError):
        apply_session_deletion(IndexStore(), plan)
    extra = _write(first.with_name("new.md"), "unapproved")
    monkeypatch.setattr(deletion, "apply_forge_content", original)
    retry = plan_session_deletion(IndexStore(), "subject", forge_root=str(root))
    with pytest.raises(ForgeSessionError, match="New content"):
        apply_session_deletion(IndexStore(), retry)
    assert first.exists() and extra.exists()


def test_live_worker_refuses_cleanup_without_holding_index_lock(tmp_path: Path) -> None:
    from forge.session.workers import session_worker_lease

    root = tmp_path / "project"
    _publish(root)
    index = IndexStore()
    token = index.migrate_session_identity("subject", str(root))
    with session_worker_lease(root, "subject", expected_instance_id=token, label="memory writer"):
        plan = plan_session_deletion(index, "subject", forge_root=str(root), force=True)
        assert any("memory writer" in reason for reason in plan.refusals)
        with pytest.raises(ForgeSessionError, match="workers"):
            apply_session_deletion(index, plan)
    assert not plan_session_deletion(index, "subject", forge_root=str(root)).refusals


def test_completed_retry_does_not_recreate_removed_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.session.deletion as deletion

    root = tmp_path / "project"
    _publish(root)
    index = IndexStore()
    plan = plan_session_deletion(index, "subject", forge_root=str(root), delete_worktree=False)
    # Simulate a crash after terminal index removal but before deleting the retry inventory.
    deletion._save_retry(cleanup_state_path(root, "subject"), plan)
    assert delete_published_session(index, "subject", root)
    shutil.rmtree(root)
    retry = replace(plan, retry=True)
    apply_session_deletion(index, retry)
    assert not root.exists()
    assert not cleanup_state_path(root, "subject").exists()


def test_corrupt_dependency_manifest_refuses_preview(tmp_path: Path) -> None:
    root, other = tmp_path / "project", tmp_path / "other"
    _publish(root)
    _publish(other, "other")
    SessionStore(str(other), "other").manifest_path.write_text("{")
    with pytest.raises(ForgeSessionError):
        plan_session_deletion(IndexStore(), "subject", forge_root=str(root))


def test_missing_dependency_manifest_refuses_without_pruning(tmp_path: Path) -> None:
    root, other = tmp_path / "project", tmp_path / "other"
    _publish(root)
    _publish(other, "other")
    # Deliberately violate publication coherence: unknown ancestry must remain blocking.
    SessionStore(str(other), "other").manifest_path.unlink()
    index = IndexStore()
    before = index.index_path.read_bytes()
    with pytest.raises(ForgeSessionError, match="missing manifest"):
        plan_session_deletion(index, "subject", forge_root=str(root))
    assert index.index_path.read_bytes() == before


@pytest.mark.parametrize("link", ["hardlink", "ancestor-symlink"])
def test_unsafe_manifest_location_refuses(tmp_path: Path, link: str) -> None:
    root = tmp_path / "project"
    _publish(root)
    store = SessionStore(str(root), "subject")
    if link == "hardlink":
        os.link(store.manifest_path, tmp_path / "other-copy")
    else:
        (root / ".forge").rename(root / "elsewhere")
        (root / ".forge").symlink_to(root / "elsewhere", target_is_directory=True)
    with pytest.raises((OSError, ValueError, ForgeSessionError)):
        plan_session_deletion(IndexStore(), "subject", forge_root=str(root))
    assert store.manifest_path.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("instance_id", "invalid"),
        ("manifest_sha256", "invalid"),
        ("unknown", True),
    ],
)
def test_malformed_retry_inventory_refuses(tmp_path: Path, field: str, value: object) -> None:
    root = tmp_path / "project"
    _publish(root)
    plan = plan_session_deletion(IndexStore(), "subject", forge_root=str(root))
    data = plan.to_dict()
    data[field] = value
    with pytest.raises((ValueError, dacite.DaciteError)):
        SessionDeletionPlan.from_dict(data)


def _git(path: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout


def _publish_worktree(git_repo: Path, tmp_path: Path) -> Path:
    checkout = tmp_path / "worktree"
    _git(git_repo, "worktree", "add", "-b", "subject", str(checkout))
    state = create_session_state("subject", worktree_path=str(checkout), worktree_branch="subject")
    state.forge_root = str(checkout)
    assert state.worktree is not None
    state.worktree.is_worktree = True
    publish_session(IndexStore(), state, git_repo, forge_root=checkout)
    return checkout


def test_changed_worktree_branch_refuses_before_owned_content_removal(git_repo: Path, tmp_path: Path) -> None:
    checkout = _publish_worktree(git_repo, tmp_path)
    owned = _write(checkout / ".forge/artifacts/subject/report.md")
    plan = plan_session_deletion(
        IndexStore(),
        "subject",
        forge_root=str(checkout),
        force=True,
        delete_branch=True,
    )
    _git(checkout, "switch", "-c", "replacement")
    with pytest.raises(ForgeSessionError, match="branch"):
        apply_session_deletion(IndexStore(), plan)
    assert owned.exists()
    assert not cleanup_state_path(checkout, "subject").exists()


@pytest.mark.parametrize("branch_changed", [False, True])
def test_retry_after_worktree_removal_does_not_recreate_root(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    branch_changed: bool,
) -> None:
    from forge.session import worktree

    checkout = _publish_worktree(git_repo, tmp_path)
    plan = plan_session_deletion(
        IndexStore(),
        "subject",
        forge_root=str(checkout),
        force=True,
        delete_branch=True,
    )
    original = worktree.cleanup_worktree

    def fail_after_removal(path: Path, **kwargs):
        worktree.remove_worktree(path, force=True, repo_root=git_repo)
        return worktree.CleanupResult(worktree_removed=True, errors=["injected branch failure"])

    monkeypatch.setattr(worktree, "cleanup_worktree", fail_after_removal)
    with pytest.raises(ForgeSessionError, match="injected branch failure"):
        apply_session_deletion(IndexStore(), plan)
    assert not checkout.exists()
    inventory = cleanup_state_path(checkout, "subject")
    assert inventory.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(worktree, "cleanup_worktree", original)
    if branch_changed:
        _git(git_repo, "commit", "--allow-empty", "-m", "new branch ownership")
        _git(
            git_repo,
            "update-ref",
            "refs/heads/subject",
            _git(git_repo, "rev-parse", "HEAD").strip(),
        )
    retry = plan_session_deletion(
        IndexStore(),
        "subject",
        forge_root=str(checkout),
        force=True,
        delete_branch=True,
    )
    if branch_changed:
        assert any("Selected branch changed" in refusal for refusal in retry.refusals)
        with pytest.raises(ForgeSessionError, match="Selected branch changed"):
            apply_session_deletion(IndexStore(), retry)
        assert not checkout.exists()
        assert inventory.exists()
        assert "refs/heads/subject" in _git(git_repo, "show-ref")
        return
    apply_session_deletion(IndexStore(), retry)
    assert not checkout.exists()
    assert not inventory.exists()
    assert "refs/heads/subject" not in _git(git_repo, "show-ref")


def test_completed_retry_refuses_content_created_after_index_removal(
    tmp_path: Path,
) -> None:
    import forge.session.deletion as deletion

    root = tmp_path / "project"
    _publish(root)
    index = IndexStore()
    plan = plan_session_deletion(index, "subject", forge_root=str(root), delete_worktree=False)
    deletion._save_retry(cleanup_state_path(root, "subject"), plan)
    assert delete_published_session(index, "subject", root)
    added = _write(root / ".forge/artifacts/subject/new.md")
    with pytest.raises(ForgeSessionError, match="New content"):
        apply_session_deletion(index, replace(plan, retry=True))
    assert added.exists()
    assert cleanup_state_path(root, "subject").exists()


def test_relocated_child_does_not_make_source_parent_a_dependent(
    tmp_path: Path,
) -> None:
    root, child_root = tmp_path / "parent", tmp_path / "child"
    parent = _publish(root)
    parent.confirmed.claude_session_id = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    SessionStore(str(root), "subject").write(parent)
    child = _publish(child_root, "child", parent=root)
    child.confirmed.artifacts["relocated_parent_session_id"] = parent.confirmed.claude_session_id
    SessionStore(str(child_root), "child").write(child)
    assert not plan_session_deletion(IndexStore(), "child", forge_root=str(child_root)).refusals
    assert plan_session_deletion(IndexStore(), "subject", forge_root=str(root)).refusals


def test_case_variant_shared_native_alias_blocks_purge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge.session import purge_native

    monkeypatch.setattr(purge_native, "check_native_inactivity", lambda runtime: ())
    monkeypatch.setattr("forge.session.deletion.check_native_inactivity", lambda runtime: ())
    root = tmp_path / "project"
    subject = _publish(root)
    subject.confirmed.claude_session_id = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    SessionStore(str(root), "subject").write(subject)
    alias = _publish(root, "alias")
    alias.confirmed.claude_session_id = subject.confirmed.claude_session_id.upper()
    SessionStore(str(root), "alias").write(alias)
    plan = plan_session_deletion(IndexStore(), "subject", forge_root=str(root), purge=True)
    assert any("alias" in reason and "native conversation" in reason for reason in plan.refusals)


def test_retry_after_manifest_unlink_can_finish_metadata_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    _publish(root)
    store = SessionStore(str(root), "subject")
    extra = _write(store.session_dir / "runtime-state.json")
    plan = plan_session_deletion(IndexStore(), "subject", forge_root=str(root), delete_worktree=False)
    original = SessionStore.delete_locked

    def fail_after_manifest_unlink(self):
        self.manifest_path.unlink()
        raise OSError("injected metadata directory failure")

    monkeypatch.setattr(SessionStore, "delete_locked", fail_after_manifest_unlink)
    with pytest.raises(ForgeSessionError, match="injected metadata"):
        apply_session_deletion(IndexStore(), plan)
    assert extra.exists()
    monkeypatch.setattr(SessionStore, "delete_locked", original)
    retry = plan_session_deletion(IndexStore(), "subject", forge_root=str(root), delete_worktree=False)
    apply_session_deletion(IndexStore(), retry)
    assert not store.session_dir.exists()


def test_retry_inventory_cannot_be_inside_removed_worktree(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = _publish_worktree(git_repo, tmp_path)
    index = IndexStore()
    monkeypatch.setenv("FORGE_HOME", str(checkout / "forge-home"))
    plan = plan_session_deletion(index, "subject", forge_root=str(checkout), force=True)
    assert any("Forge home" in refusal and "--keep-worktree" in refusal for refusal in plan.refusals)
    with pytest.raises(ForgeSessionError, match="Forge home"):
        apply_session_deletion(index, plan)
    assert checkout.exists()


def _reviewer_purge_fixture(tmp_path, monkeypatch):
    from forge.core.paths import get_forge_home
    from forge.core.reactive.codex_reviewer_home import INPUT_MARKER, MARKER
    from forge.session import purge_native
    from forge.session.claude.paths import encode_project_path

    root = tmp_path / "project"
    state = _publish(root)
    native_id = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    state.confirmed.claude_session_id = native_id
    state.confirmed.claude_project_root = str(root)
    SessionStore(str(root), state.name).write(state)
    native_home = tmp_path / "native"
    monkeypatch.setenv("CLAUDE_HOME", str(native_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(native_home))
    monkeypatch.setattr(purge_native, "check_native_inactivity", lambda runtime: ())
    monkeypatch.setattr("forge.session.deletion.check_native_inactivity", lambda runtime: ())
    transcript = _write(
        native_home / "projects" / encode_project_path(str(root)) / f"{native_id}.jsonl",
        json.dumps({"type": "user", "sessionId": native_id, "cwd": str(root), "version": "2.1.245"}) + "\n",
    )
    reviewer = get_forge_home() / "reviewers/codex"
    reviewer.mkdir(parents=True, mode=0o700)
    _write(reviewer / MARKER, json.dumps({"version": 1, "extra_usage_off_asserted": True}))
    _write(reviewer / "review.lock", "")
    _write(reviewer / "sessions" / INPUT_MARKER, "1\n")
    copy = _write(
        reviewer / "sessions/2026/10/20/rollout.jsonl",
        json.dumps({"type": "session_meta", "payload": {"id": native_id}}),
    )
    return root, reviewer, transcript, copy


@pytest.mark.parametrize("busy_at_preview", [False, True])
def test_busy_reviewer_refuses_before_native_removal_or_retry_save(tmp_path, monkeypatch, busy_at_preview):
    from forge.core.reactive.codex_reviewer_home import reviewer_lease

    root, reviewer, transcript, copy = _reviewer_purge_fixture(tmp_path, monkeypatch)
    index = IndexStore()
    before = {path: path.read_bytes() for path in (transcript, copy, index.index_path)}
    if not busy_at_preview:
        plan = plan_session_deletion(index, "subject", forge_root=str(root), purge=True, delete_worktree=False)
        assert not plan.refusals
    with reviewer_lease(reviewer):
        if busy_at_preview:
            plan = plan_session_deletion(index, "subject", forge_root=str(root), purge=True, delete_worktree=False)
            assert any("reviewer lease" in reason for reason in plan.refusals)
        with pytest.raises(ForgeSessionError, match="reviewer lease"):
            apply_session_deletion(index, plan)
    assert all(path.read_bytes() == data for path, data in before.items())
    assert not cleanup_state_path(root, "subject").exists()


def test_reviewer_lease_is_held_before_native_unlink(tmp_path, monkeypatch):
    from forge.core.reactive.codex_reviewer_home import (
        ReviewerBusyError,
        reviewer_lease,
    )
    from forge.session import deletion

    root, reviewer, transcript, copy = _reviewer_purge_fixture(tmp_path, monkeypatch)
    index = IndexStore()
    plan = plan_session_deletion(index, "subject", forge_root=str(root), purge=True, delete_worktree=False)
    original = deletion.unlink_native_file
    observed = []

    def unlink_while_leased(file):
        with pytest.raises(ReviewerBusyError), reviewer_lease(reviewer):
            pass
        observed.append(file.path)
        return original(file)

    monkeypatch.setattr(deletion, "unlink_native_file", unlink_while_leased)
    apply_session_deletion(index, plan)
    assert observed == [str(transcript)]
    assert not transcript.exists() and not copy.exists()
