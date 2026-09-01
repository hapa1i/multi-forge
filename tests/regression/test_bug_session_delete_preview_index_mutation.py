"""Regression: cancelling session deletion must not repair unrelated index rows."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionManager, create_session_state
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


def test_confirmed_delete_retains_self_healing_for_unrelated_residue(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    unrelated_root = tmp_path / "unrelated"
    index, manager = _seed_target_and_residue(project, unrelated_root)

    manager.delete_session("target", forge_root=str(project), delete_transcripts=False)

    assert not index.session_exists("row-only", forge_root=str(unrelated_root))
