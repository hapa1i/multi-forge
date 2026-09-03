"""Regression: cancelling session deletion must not repair unrelated index rows."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.active import ActiveSessionStore
from forge.session.config import LAUNCH_MODE_HOST
from forge.session.exceptions import GitWorktreeError
from forge.session.worktree.cleanup import is_worktree_dirty
from tests.fixtures.session_state import publish_session, seed_row_only_session

pytestmark = pytest.mark.regression


def _seed_target_and_residue(project: Path, unrelated_root: Path) -> tuple[IndexStore, SessionManager]:
    index = IndexStore()
    worktree = project.parent / "target-worktree"
    worktree.mkdir()
    target = create_session_state("target", worktree_path=str(worktree), worktree_branch="target-branch")
    assert target.worktree is not None
    target.forge_root = str(project)
    target.worktree.is_worktree = True
    target.worktree.owns_worktree = False
    publish_session(index, target, project, forge_root=project, checkout_root=worktree)

    unrelated_root.mkdir()
    residue = create_session_state("row-only", worktree_path=str(unrelated_root))
    residue.forge_root = str(unrelated_root)
    # Deliberately model crash residue so the test can distinguish preview from
    # mutation-time self-healing.
    seed_row_only_session(index, residue, unrelated_root, forge_root=unrelated_root)
    return index, SessionManager(index)


def test_cancelled_delete_preserves_unrelated_row_only_residue(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    index, _manager = _seed_target_and_residue(project, tmp_path / "unrelated")
    monkeypatch.chdir(project)
    before = index.index_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "delete", "target"], input="n\n")

    assert result.exit_code == 0
    assert "Cancelled" in result.output
    assert index.index_path.read_bytes() == before


def test_cancelled_delete_all_preserves_unrelated_row_only_residue(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    index, _manager = _seed_target_and_residue(project, tmp_path / "unrelated")
    monkeypatch.chdir(project)
    before = index.index_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "delete", "--all"], input="n\n")

    assert result.exit_code == 0
    assert "Cancelled" in result.output
    assert index.index_path.read_bytes() == before


def test_cancelled_delete_preserves_target_row_only_residue(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".forge").mkdir()
    index = IndexStore()
    residue = create_session_state("target", worktree_path=str(project))
    residue.forge_root = str(project)
    # Deliberately model a row-first publication crash for the requested target.
    seed_row_only_session(index, residue, project, forge_root=project)
    monkeypatch.chdir(project)
    before = index.index_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "delete", "target"], input="n\n")

    assert result.exit_code == 0
    assert "About to repair stale session record" in result.output
    assert "manifest is missing" in result.output
    assert "Cancelled" in result.output
    assert index.index_path.read_bytes() == before


@pytest.mark.parametrize("confirmation", [[], ["--yes"]])
def test_confirmed_delete_repairs_target_row_only_residue_without_not_found_error(
    tmp_path: Path,
    monkeypatch,
    confirmation: list[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".forge").mkdir()
    index = IndexStore()
    residue = create_session_state("target", worktree_path=str(project))
    residue.forge_root = str(project)
    # Deliberately model a row-first publication crash; confirmation authorizes
    # pruning this derived row, while the preview above must leave it byte-exact.
    seed_row_only_session(index, residue, project, forge_root=project)
    monkeypatch.chdir(project)

    result = CliRunner().invoke(
        main,
        ["session", "delete", "target", *confirmation],
        input="" if confirmation else "y\n",
    )

    assert result.exit_code == 0, result.output
    assert "About to repair stale session record" in result.output
    assert "Deleted session" in result.output
    assert "not found" not in result.output
    assert not index.session_exists("target", forge_root=str(project))


def test_row_only_delete_refuses_replacement_published_during_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".forge").mkdir()
    index = IndexStore()
    residue = create_session_state("target", worktree_path=str(project))
    residue.forge_root = str(project)
    seed_row_only_session(index, residue, project, forge_root=project)
    monkeypatch.chdir(project)

    def _publish_replacement(*_args, **_kwargs) -> bool:
        replacement = create_session_state("target", worktree_path=str(project))
        replacement.forge_root = str(project)
        publish_session(index, replacement, project, forge_root=project, checkout_root=project)
        return True

    monkeypatch.setattr("forge.cli.session_manage.click.confirm", _publish_replacement)

    result = CliRunner().invoke(main, ["session", "delete", "target"])

    assert result.exit_code == 1, result.output
    assert "changed while deletion was being prepared" in result.output
    assert "Inspect it and retry 'forge session delete target'" in result.output
    assert "Deleted session" not in result.output
    assert SessionStore(str(project), "target").exists()
    assert index.session_exists("target", forge_root=str(project))


def test_same_name_nested_co_resident_protects_shared_worktree_in_preview_and_apply(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    checkout = repo / "worktree"
    root_project = checkout
    nested_project = checkout / "packages" / "nested"
    nested_project.mkdir(parents=True)
    index = IndexStore()

    owner = create_session_state("shared-name", worktree_path=str(checkout), worktree_branch="shared-branch")
    assert owner.worktree is not None
    owner.forge_root = str(root_project)
    owner.worktree.is_worktree = True
    owner.worktree.owns_worktree = True
    publish_session(index, owner, repo, forge_root=root_project, checkout_root=checkout)

    guest = create_session_state("shared-name", worktree_path=str(checkout), worktree_branch="shared-branch")
    assert guest.worktree is not None
    guest.forge_root = str(nested_project)
    guest.worktree.is_worktree = True
    guest.worktree.owns_worktree = False
    publish_session(index, guest, repo, forge_root=nested_project, checkout_root=checkout)
    monkeypatch.chdir(root_project)

    preview = CliRunner().invoke(main, ["session", "delete", "shared-name"], input="n\n")

    assert preview.exit_code == 0, preview.output
    assert "Worktree will be kept (used by shared-name)" in preview.output
    assert "Worktree will be removed" not in preview.output
    assert "Cancelled" in preview.output

    manager = SessionManager(index)
    with patch("forge.session.worktree.cleanup_worktree") as cleanup_worktree:
        manager.delete_session(
            "shared-name",
            forge_root=str(root_project),
            delete_transcripts=False,
            delete_worktree=True,
            force=True,
        )

    cleanup_worktree.assert_not_called()
    assert not SessionStore(str(root_project), "shared-name").exists()
    assert SessionStore(str(nested_project), "shared-name").exists()
    assert index.session_exists("shared-name", forge_root=str(nested_project))


def test_nested_legacy_manifest_preview_excludes_its_exact_index_row(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    checkout = repo / "worktree"
    nested_project = checkout / "packages" / "nested"
    nested_project.mkdir(parents=True)
    index = IndexStore()
    state = create_session_state("legacy", worktree_path=str(checkout), worktree_branch="legacy-branch")
    assert state.worktree is not None
    state.forge_root = str(nested_project)
    state.worktree.is_worktree = True
    state.worktree.owns_worktree = True
    publish_session(index, state, repo, forge_root=nested_project, checkout_root=checkout)
    SessionStore(str(nested_project), "legacy").update(
        timeout_s=5.0,
        mutate=lambda manifest: setattr(manifest, "forge_root", None),
    )
    monkeypatch.setattr("forge.session.worktree.is_worktree_dirty", lambda _path: False)
    monkeypatch.chdir(nested_project)

    preview = CliRunner().invoke(main, ["session", "delete", "legacy"], input="n\n")

    assert preview.exit_code == 0, preview.output
    assert "Worktree will be removed" in preview.output
    assert "Worktree will be kept (used by legacy)" not in preview.output
    assert "Cancelled" in preview.output
    assert SessionStore(str(nested_project), "legacy").exists()


def test_cancelled_cross_worktree_delete_preserves_row_only_residue(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".forge").mkdir()
    sibling = repo / "sibling"
    sibling.mkdir()
    worktree = repo / "target-worktree"
    worktree.mkdir()

    index = IndexStore()
    target = create_session_state("target", worktree_path=str(worktree), worktree_branch="target-branch")
    assert target.worktree is not None
    target.forge_root = str(sibling)
    target.worktree.is_worktree = True
    target.worktree.owns_worktree = False
    publish_session(index, target, repo, forge_root=sibling, checkout_root=worktree)

    residue_root = repo / "residue"
    residue_root.mkdir()
    residue = create_session_state("row-only", worktree_path=str(residue_root))
    residue.forge_root = str(residue_root)
    # Deliberately model crash residue in the same repository so Tier 2 scans it.
    seed_row_only_session(index, residue, repo, forge_root=residue_root)
    monkeypatch.chdir(repo)
    before = index.index_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "delete", "target"], input="n\n")

    assert result.exit_code == 0
    assert "Deleting session from" in result.output
    assert "Cancelled" in result.output
    assert index.index_path.read_bytes() == before


def test_cancelled_delete_preserves_stale_active_entry(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _index, _manager = _seed_target_and_residue(project, tmp_path / "unrelated")
    active = ActiveSessionStore()
    active.upsert_session(
        "target",
        worktree_path=str(project),
        launch_mode=LAUNCH_MODE_HOST,
        launcher_pid=424242,
        forge_root=str(project),
    )
    monkeypatch.setattr("forge.session.active.is_pid_alive", lambda _pid: False)
    monkeypatch.chdir(project)
    before = active.index_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "delete", "target"], input="n\n")

    assert result.exit_code == 0
    assert "Cancelled" in result.output
    assert active.index_path.read_bytes() == before


def test_clean_preview_preserves_unrelated_row_only_index_residue(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    index, _manager = _seed_target_and_residue(project, tmp_path / "unrelated")
    monkeypatch.chdir(project)
    before = index.index_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "clean", "--older-than", "1"])

    assert result.exit_code == 0, result.output
    assert index.index_path.read_bytes() == before


def test_clean_preview_preserves_stale_active_registry_entry(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _index, _manager = _seed_target_and_residue(project, tmp_path / "unrelated")
    active = ActiveSessionStore()
    active.upsert_session(
        "target",
        worktree_path=str(project),
        launch_mode=LAUNCH_MODE_HOST,
        launcher_pid=424242,
        forge_root=str(project),
    )
    monkeypatch.setattr("forge.session.active.is_pid_alive", lambda _pid: False)
    monkeypatch.chdir(project)
    before = active.index_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "clean", "--older-than", "1"])

    assert result.exit_code == 0, result.output
    assert "Actual cleanup would abort" not in result.output
    assert "No sessions older than 1 days found" in result.output
    assert active.index_path.read_bytes() == before


def test_clean_preview_preserves_malformed_active_registry_bytes(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    index, _manager = _seed_target_and_residue(project, tmp_path / "unrelated")
    index.update_session(
        "target",
        last_accessed_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
        forge_root=str(project),
    )
    active = ActiveSessionStore()
    active.index_path.parent.mkdir(parents=True, exist_ok=True)
    before = b"{malformed\n"
    active.index_path.write_bytes(before)
    monkeypatch.chdir(project)

    result = CliRunner().invoke(main, ["session", "clean", "--older-than", "1"])

    assert result.exit_code == 0, result.output
    assert "target" in result.output
    assert "will delete" in result.output
    assert "Actual cleanup would abort" not in result.output
    assert active.index_path.read_bytes() == before


def test_clean_preview_uses_fractional_age_for_threshold_classification(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    index, _manager = _seed_target_and_residue(project, tmp_path / "unrelated")
    index.update_session(
        "target",
        last_accessed_at=(datetime.now(UTC) - timedelta(hours=36)).isoformat(),
        forge_root=str(project),
    )
    monkeypatch.chdir(project)

    result = CliRunner().invoke(main, ["session", "clean", "--older-than", "1"])

    assert result.exit_code == 0, result.output
    assert "target" in result.output
    assert "will delete" in result.output
    assert "Would delete 1 session" in result.output


def test_clean_preview_and_apply_report_real_index_unparseable_timestamp_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    worktree = tmp_path / "target-worktree"
    worktree.mkdir()
    index = IndexStore()
    target = create_session_state("target", worktree_path=str(worktree), worktree_branch="target-branch")
    assert target.worktree is not None
    target.forge_root = str(project)
    target.worktree.is_worktree = True
    target.worktree.owns_worktree = False
    publish_session(index, target, project, forge_root=project, checkout_root=worktree)
    index.update_session("target", last_accessed_at="not-a-timestamp", forge_root=str(project))
    monkeypatch.chdir(project)
    before = index.index_path.read_bytes()

    preview = CliRunner().invoke(main, ["session", "clean", "--older-than", "1"])

    assert preview.exit_code == 0, preview.output
    assert "target" in preview.output
    assert "unparseable timestamp (skip)" in preview.output
    assert index.index_path.read_bytes() == before

    apply = CliRunner().invoke(main, ["session", "clean", "--older-than", "1", "--yes"])

    assert apply.exit_code == 0, apply.output
    assert "Skipped 1 session with unparseable timestamps" in apply.output
    assert SessionStore(str(project), "target").exists()
    assert index.index_path.read_bytes() == before


def test_clean_preview_matches_apply_for_owned_dirty_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    worktree = tmp_path / "owned-worktree"
    worktree.mkdir()
    index = IndexStore()
    state = create_session_state("dirty", worktree_path=str(worktree), worktree_branch="dirty-branch")
    assert state.worktree is not None
    state.forge_root = str(project)
    state.worktree.is_worktree = True
    state.worktree.owns_worktree = True
    publish_session(index, state, project, forge_root=project, checkout_root=worktree)
    index.update_session(
        "dirty",
        last_accessed_at=(datetime.now(UTC) - timedelta(hours=36)).isoformat(),
        forge_root=str(project),
    )
    monkeypatch.setattr("forge.session.worktree.is_worktree_dirty", lambda _path: True)
    monkeypatch.chdir(project)
    before = index.index_path.read_bytes()

    preview = CliRunner().invoke(
        main,
        ["session", "clean", "--older-than", "1", "--delete-worktree"],
    )

    assert preview.exit_code == 0, preview.output
    assert "dirty worktree (apply failure)" in preview.output
    assert "Would delete 0 sessions, fail 1" in preview.output
    assert index.index_path.read_bytes() == before

    apply = CliRunner().invoke(
        main,
        ["session", "clean", "--older-than", "1", "--delete-worktree", "--yes"],
    )

    assert apply.exit_code == 1, apply.output
    assert "Encountered 1 cleanup failure" in apply.output
    assert SessionStore(str(project), "dirty").exists()
    assert index.index_path.read_bytes() == before


def test_clean_preview_reports_corrupt_manifest_with_default_worktree_retention(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project-[release]"
    project.mkdir()
    worktree = tmp_path / "target-worktree"
    worktree.mkdir()
    index = IndexStore()
    state = create_session_state("corrupt", worktree_path=str(worktree), worktree_branch="corrupt-branch")
    assert state.worktree is not None
    state.forge_root = str(project)
    state.worktree.is_worktree = True
    state.worktree.owns_worktree = False
    publish_session(index, state, project, forge_root=project, checkout_root=worktree)
    index.update_session(
        "corrupt",
        last_accessed_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
        forge_root=str(project),
    )
    store = SessionStore(str(project), "corrupt")
    store.manifest_path.write_text("{malformed\n", encoding="utf-8")
    monkeypatch.chdir(project)
    before = index.index_path.read_bytes()

    preview = CliRunner().invoke(main, ["session", "clean", "--older-than", "1"])

    assert preview.exit_code == 0, preview.output
    assert "apply failure" in preview.output
    assert "Would delete 0 sessions, fail 1" in preview.output
    assert "will delete" not in preview.output
    assert index.index_path.read_bytes() == before

    apply = CliRunner().invoke(main, ["session", "clean", "--older-than", "1", "--yes"])

    assert apply.exit_code == 1, apply.output
    assert "Encountered 1 cleanup failure" in apply.output
    assert store.exists()


def test_named_delete_refuses_dirty_owned_worktree_before_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    worktree = tmp_path / "owned-worktree"
    worktree.mkdir()
    index = IndexStore()
    state = create_session_state("dirty", worktree_path=str(worktree), worktree_branch="dirty-branch")
    assert state.worktree is not None
    state.forge_root = str(project)
    state.worktree.is_worktree = True
    state.worktree.owns_worktree = True
    publish_session(index, state, project, forge_root=project, checkout_root=worktree)
    monkeypatch.setattr("forge.session.worktree.is_worktree_dirty", lambda _path: True)
    monkeypatch.chdir(project)
    before = index.index_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "delete", "dirty"])

    assert result.exit_code == 1, result.output
    assert "uncommitted changes" in result.output
    assert "Are you sure" not in result.output
    assert index.index_path.read_bytes() == before


def test_clean_preview_models_shared_worktree_deletions_in_apply_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    worktree = tmp_path / "shared-worktree"
    worktree.mkdir()
    index = IndexStore()

    guest = create_session_state("guest", worktree_path=str(worktree), worktree_branch="shared-branch")
    assert guest.worktree is not None
    guest.forge_root = str(project)
    guest.worktree.is_worktree = True
    guest.worktree.owns_worktree = False
    publish_session(index, guest, project, forge_root=project, checkout_root=worktree)

    owner = create_session_state("owner", worktree_path=str(worktree), worktree_branch="shared-branch")
    assert owner.worktree is not None
    owner.forge_root = str(project)
    owner.worktree.is_worktree = True
    owner.worktree.owns_worktree = True
    publish_session(index, owner, project, forge_root=project, checkout_root=worktree)

    index.update_session(
        "guest",
        last_accessed_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
        forge_root=str(project),
    )
    index.update_session(
        "owner",
        last_accessed_at=(datetime.now(UTC) - timedelta(days=3)).isoformat(),
        forge_root=str(project),
    )
    monkeypatch.setattr("forge.session.worktree.is_worktree_dirty", lambda _path: True)
    monkeypatch.chdir(project)

    preview = CliRunner().invoke(
        main,
        ["session", "clean", "--older-than", "1", "--delete-worktree"],
    )

    assert preview.exit_code == 0, preview.output
    assert "Would delete 1 session, fail 1" in preview.output
    assert "dirty worktree (apply failure)" in preview.output

    apply = CliRunner().invoke(
        main,
        ["session", "clean", "--older-than", "1", "--delete-worktree", "--yes"],
    )

    assert apply.exit_code == 1, apply.output
    assert "Cleaned 1 session" in apply.output
    assert "Encountered 1 cleanup failure" in apply.output
    assert not SessionStore(str(project), "guest").exists()
    assert SessionStore(str(project), "owner").exists()


def test_dirty_probe_refuses_failed_git_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("forge.session.worktree.cleanup.find_git_binary", lambda: "git")
    monkeypatch.setattr(
        "forge.session.worktree.cleanup.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 128, stdout="", stderr="fatal: broken metadata"),
    )

    with pytest.raises(GitWorktreeError, match="git worktree status failed: fatal: broken metadata"):
        is_worktree_dirty(tmp_path)


def test_confirmed_delete_retains_self_healing_for_unrelated_residue(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    unrelated_root = tmp_path / "unrelated"
    index, manager = _seed_target_and_residue(project, unrelated_root)

    manager.delete_session("target", forge_root=str(project), delete_transcripts=False)

    assert not index.session_exists("row-only", forge_root=str(unrelated_root))


def test_confirmed_delete_clears_stale_active_entry(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _index, _manager = _seed_target_and_residue(project, tmp_path / "unrelated")
    active = ActiveSessionStore()
    active.upsert_session(
        "target",
        worktree_path=str(project),
        launch_mode=LAUNCH_MODE_HOST,
        launcher_pid=424242,
        forge_root=str(project),
    )
    monkeypatch.setattr("forge.session.active.is_pid_alive", lambda _pid: False)
    monkeypatch.chdir(project)

    result = CliRunner().invoke(main, ["session", "delete", "target", "--yes"])

    assert result.exit_code == 0
    assert active.read().sessions == {}
