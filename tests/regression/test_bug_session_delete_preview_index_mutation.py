"""Deletion previews preserve index bytes, even when admission must refuse."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.active import ActiveSessionStore
from forge.session.config import LAUNCH_MODE_HOST
from forge.session.exceptions import GitWorktreeError
from forge.session.worktree.cleanup import is_worktree_dirty
from tests.fixtures.session_state import (
    delete_published_session,
    publish_session,
    seed_row_only_session,
)

pytestmark = pytest.mark.regression


def _publish(
    root: Path,
    name: str = "target",
    *,
    checkout: Path | None = None,
    owns: bool = False,
) -> IndexStore:
    root.mkdir(parents=True, exist_ok=True)
    state = create_session_state(name, worktree_path=str(checkout or root), worktree_branch="target-branch")
    state.forge_root = str(root)
    assert state.worktree is not None
    state.worktree.is_worktree = checkout is not None
    state.worktree.owns_worktree = owns
    index = IndexStore()
    publish_session(index, state, root, forge_root=root, checkout_root=checkout or root)
    return index


def _residue(index: IndexStore, root: Path, name: str = "row-only") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".forge").mkdir(exist_ok=True)
    state = create_session_state(name, worktree_path=str(root))
    state.forge_root = str(root)
    # Deliberately violate publication coherence: a crash left unknown ancestry.
    seed_row_only_session(index, state, root, forge_root=root)


def _snapshot(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


@pytest.mark.parametrize("selection", [["target"], ["--all"]])
@pytest.mark.parametrize("unknown", [False, True])
def test_delete_cancel_or_refusal_preserves_unrelated_index_state(
    tmp_path: Path, monkeypatch, selection, unknown
) -> None:
    project = tmp_path / "project"
    index = _publish(project)
    if unknown:
        _residue(index, tmp_path / "unrelated")
    else:
        _publish(tmp_path / "unrelated", "other")
    monkeypatch.chdir(project)
    before = _snapshot(index.index_path)
    result = CliRunner().invoke(main, ["session", "delete", *selection], input="n\n")
    assert result.exit_code == (1 if unknown else 0), result.output
    assert ("missing manifest" if unknown else "Cancelled") in result.output
    assert _snapshot(index.index_path) == before
    assert SessionStore(str(project), "target").exists()


@pytest.mark.parametrize("options", [[], ["--yes"], ["--yes", "--force"]])
def test_unknown_target_is_refused_without_repairing_row(tmp_path: Path, monkeypatch, options) -> None:
    project = tmp_path / "project"
    index = IndexStore()
    _residue(index, project, "target")
    monkeypatch.chdir(project)
    before = _snapshot(index.index_path)
    result = CliRunner().invoke(main, ["session", "delete", "target", *options], input="y\n")
    assert result.exit_code == 1, result.output
    assert "no manifest" in result.output
    assert "forge session list --scope all" in " ".join(result.output.split())
    assert _snapshot(index.index_path) == before


def test_replacement_during_confirmation_is_preserved(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    index = _publish(project)
    monkeypatch.chdir(project)

    def replace_target(*args, **kwargs):
        assert delete_published_session(index, "target", project)
        _publish(project)
        return True

    monkeypatch.setattr("forge.cli.session_delete.click.confirm", replace_target)
    result = CliRunner().invoke(main, ["session", "delete", "target"])
    assert result.exit_code == 1, result.output
    assert "instance changed" in result.output
    assert SessionStore(str(project), "target").exists()


def test_same_name_nested_co_resident_keeps_shared_worktree(tmp_path: Path, monkeypatch) -> None:
    checkout = tmp_path / "worktree"
    nested = checkout / "packages/app"
    index = _publish(checkout, "shared", checkout=checkout, owns=True)
    _publish(nested, "shared", checkout=checkout)
    monkeypatch.chdir(checkout)
    before = _snapshot(index.index_path)
    preview = CliRunner().invoke(main, ["session", "delete", "shared"], input="n\n")
    assert preview.exit_code == 0, preview.output
    assert "Keep worktree (shared)" in preview.output
    assert _snapshot(index.index_path) == before
    apply = CliRunner().invoke(main, ["session", "delete", "shared", "--yes"])
    assert apply.exit_code == 0, apply.output
    assert checkout.exists()
    assert not SessionStore(str(checkout), "shared").exists()
    assert SessionStore(str(nested), "shared").exists()


def _worktree(repo: Path, path: Path) -> None:
    subprocess.run(
        ["git", "worktree", "add", "-b", "target-branch", str(path)],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def test_nested_legacy_preview_excludes_its_exact_index_row(git_repo: Path, tmp_path: Path, monkeypatch) -> None:
    checkout = tmp_path / "worktree"
    _worktree(git_repo, checkout)
    nested = checkout / "packages/app"
    index = _publish(nested, checkout=checkout, owns=True)
    store = SessionStore(str(nested), "target")
    store.update(timeout_s=5.0, mutate=lambda state: setattr(state, "forge_root", None))
    monkeypatch.chdir(nested)
    before = _snapshot(index.index_path)
    preview = CliRunner().invoke(main, ["session", "delete", "target", "--force"], input="n\n")
    assert preview.exit_code == 0, preview.output
    assert "Remove worktree:" in preview.output
    assert "Cancelled" in preview.output
    assert _snapshot(index.index_path) == before
    assert store.exists()


@pytest.mark.parametrize("apply", [False, True])
def test_stale_active_entry_is_read_only_until_confirmed(tmp_path: Path, monkeypatch, apply) -> None:
    project = tmp_path / "project"
    _publish(project)
    active = ActiveSessionStore()
    active.upsert_session(
        "target",
        forge_root=str(project),
        worktree_path=str(project),
        launch_mode=LAUNCH_MODE_HOST,
        launcher_pid=424242,
    )
    monkeypatch.setattr("forge.session.active.is_pid_alive", lambda pid: False)
    monkeypatch.chdir(project)
    before = _snapshot(active.index_path)
    result = CliRunner().invoke(
        main,
        ["session", "delete", "target", *(["--yes"] if apply else [])],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    if apply:
        assert active.read().sessions == {}
    else:
        assert _snapshot(active.index_path) == before


def test_clean_preview_preserves_unrelated_row_and_active_residue(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    index = _publish(project)
    _residue(index, tmp_path / "unrelated")
    active = ActiveSessionStore()
    active.upsert_session(
        "target",
        forge_root=str(project),
        worktree_path=str(project),
        launch_mode=LAUNCH_MODE_HOST,
        launcher_pid=424242,
    )
    monkeypatch.setattr("forge.session.active.is_pid_alive", lambda pid: False)
    monkeypatch.chdir(project)
    before = [_snapshot(path) for path in (index.index_path, active.index_path)]
    result = CliRunner().invoke(main, ["session", "clean", "--older-than", "1"])
    assert result.exit_code == 0, result.output
    assert [_snapshot(path) for path in (index.index_path, active.index_path)] == before


def test_clean_preview_refuses_malformed_active_registry_without_repair(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    index = _publish(project)
    index.update_session("target", forge_root=str(project), last_accessed_at="2000-01-01T00:00:00Z")
    active = ActiveSessionStore()
    active.index_path.parent.mkdir(parents=True, exist_ok=True)
    active.index_path.write_bytes(b"{malformed\n")
    before = _snapshot(active.index_path)
    monkeypatch.chdir(project)
    result = CliRunner().invoke(main, ["session", "clean", "--older-than", "1"])
    assert result.exit_code == 1, result.output
    assert "active session registry" in result.output
    assert _snapshot(active.index_path) == before
    assert SessionStore(str(project), "target").exists()


def test_clean_preview_uses_fractional_age_and_does_not_mutate(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    index = _publish(project)
    index.update_session(
        "target",
        forge_root=str(project),
        last_accessed_at=(datetime.now(UTC) - timedelta(hours=36)).isoformat(),
    )
    before = _snapshot(index.index_path)
    monkeypatch.chdir(project)
    result = CliRunner().invoke(main, ["session", "clean", "--older-than", "1"])
    assert result.exit_code == 0, result.output
    assert "Would delete 1 session" in result.output
    assert _snapshot(index.index_path) == before


@pytest.mark.parametrize("apply", [False, True])
def test_unparseable_age_is_reported_without_mutation(tmp_path: Path, monkeypatch, apply) -> None:
    project = tmp_path / "project"
    index = _publish(project)
    index.update_session("target", forge_root=str(project), last_accessed_at="not-a-timestamp")
    before = _snapshot(index.index_path)
    monkeypatch.chdir(project)
    result = CliRunner().invoke(main, ["session", "clean", "--older-than", "1", *(["--yes"] if apply else [])])
    assert result.exit_code == 0, result.output
    assert "unparseable timestamp" in result.output
    assert _snapshot(index.index_path) == before


@pytest.mark.parametrize(
    "command",
    [["delete", "target"], ["clean", "--older-than", "1", "--delete-worktree"]],
)
def test_dirty_worktree_refuses_before_confirmation_or_apply(
    git_repo: Path, tmp_path: Path, monkeypatch, command
) -> None:
    checkout = tmp_path / "worktree"
    _worktree(git_repo, checkout)
    index = _publish(git_repo, checkout=checkout, owns=True)
    (checkout / "untracked.txt").write_text("user work")
    index.update_session("target", forge_root=str(git_repo), last_accessed_at="2000-01-01T00:00:00Z")
    monkeypatch.chdir(git_repo)
    before = _snapshot(index.index_path)
    confirm = Mock(side_effect=AssertionError("refused targets must never prompt"))
    monkeypatch.setattr("forge.cli.session_delete.click.confirm", confirm)
    for options in ([], ["--yes"]):
        result = CliRunner().invoke(main, ["session", *command, *options])
        assert result.exit_code == 1, result.output
        assert "uncommitted changes" in result.output
        assert _snapshot(index.index_path) == before
    confirm.assert_not_called()
    assert checkout.exists()


def test_clean_corrupt_manifest_preview_and_apply_agree(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project-[release]"
    index = _publish(project)
    index.update_session("target", forge_root=str(project), last_accessed_at="2000-01-01T00:00:00Z")
    store = SessionStore(str(project), "target")
    store.manifest_path.write_text("{malformed\n")
    before = _snapshot(index.index_path)
    monkeypatch.chdir(project)
    for options in ([], ["--yes"]):
        result = CliRunner().invoke(main, ["session", "clean", "--older-than", "1", *options])
        assert result.exit_code == 1, result.output
        assert "invalid JSON" in result.output
        assert _snapshot(index.index_path) == before
        assert store.exists()


def test_clean_freezes_shared_worktree_retention_for_whole_batch(tmp_path: Path, monkeypatch) -> None:
    root, checkout = tmp_path / "project", tmp_path / "shared-worktree"
    checkout.mkdir()
    index = _publish(root, "owner", checkout=checkout, owns=True)
    _publish(root, "guest", checkout=checkout)
    for name in ("owner", "guest"):
        index.update_session(name, forge_root=str(root), last_accessed_at="2000-01-01T00:00:00Z")
    monkeypatch.chdir(root)
    before = _snapshot(index.index_path)
    preview = CliRunner().invoke(main, ["session", "clean", "--older-than", "1", "--delete-worktree"])
    assert preview.exit_code == 0, preview.output
    assert "Would delete 2 session(s)" in preview.output
    assert _snapshot(index.index_path) == before
    apply = CliRunner().invoke(main, ["session", "clean", "--older-than", "1", "--delete-worktree", "--yes"])
    assert apply.exit_code == 0, apply.output
    assert checkout.exists()
    assert not SessionStore(str(root), "owner").exists()
    assert not SessionStore(str(root), "guest").exists()


def test_dirty_probe_refuses_failed_git_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("forge.session.worktree.cleanup.find_git_binary", lambda: "git")
    monkeypatch.setattr(
        "forge.session.worktree.cleanup.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 128, stdout="", stderr="fatal: broken metadata"),
    )
    with pytest.raises(GitWorktreeError, match="git worktree status failed: fatal: broken metadata"):
        is_worktree_dirty(tmp_path)
