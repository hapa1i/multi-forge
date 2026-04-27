"""Regression: session list shows sessions that show/delete can't interact with.

Bug: `forge session list` is repo-scoped and shows sessions from all
forge_roots in the same git repo, but `show` and `delete` were project-scoped
(current forge_root only). Users could see sessions in `list` they couldn't
touch -- "session not found in current project" with a hint to cd elsewhere.

Root cause: CLI commands passed `_cwd_forge_root()` to manager lookups,
restricting resolution to the current project. The manager and index layers
already supported cross-project lookups; the restriction was purely in the
CLI layer.

Fix: Shared two-tier resolver (`resolve_session_repo_wide`) in
`src/forge/core/ops/resolution.py`. Commands `show`, `delete`, `set`, `reset`
now resolve repo-wide with current-project preference.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state

pytestmark = pytest.mark.regression


def _setup_repo_with_two_forge_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Create a repo with two forge_roots, session in the second."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("COLUMNS", "500")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    # forge_root_a: where the user is
    fr_a = repo
    (fr_a / ".forge").mkdir()

    # forge_root_b: where the session lives
    fr_b = repo / "subproject"
    fr_b.mkdir()
    (fr_b / ".forge").mkdir()

    # Seed a session in fr_b
    name = "remote-sess"
    manifest = create_session_state(
        name,
        proxy_template="direct",
        proxy_base_url="",
        worktree_path=str(fr_b),
    )
    manifest.forge_root = str(fr_b)
    SessionStore(str(fr_b), name).write(manifest)
    IndexStore().add_session(
        name=name,
        worktree_path=str(fr_b),
        project_root=str(repo),
        forge_root=str(fr_b),
    )

    monkeypatch.chdir(repo)
    return fr_a, fr_b


def test_list_shows_session_and_show_can_reach_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If `list` shows a session, `show` should be able to display it."""
    fr_a, fr_b = _setup_repo_with_two_forge_roots(tmp_path, monkeypatch)
    runner = CliRunner()

    list_result = runner.invoke(main, ["session", "list"])
    assert list_result.exit_code == 0
    assert "remote-sess" in list_result.output

    show_result = runner.invoke(main, ["session", "show", "remote-sess"])
    assert show_result.exit_code == 0
    assert "remote-sess" in show_result.output
    assert "subproject" in show_result.output  # cross-project note


def test_list_shows_session_and_delete_can_remove_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If `list` shows a session, `delete` should be able to remove it."""
    fr_a, fr_b = _setup_repo_with_two_forge_roots(tmp_path, monkeypatch)
    runner = CliRunner()

    list_result = runner.invoke(main, ["session", "list"])
    assert "remote-sess" in list_result.output

    delete_result = runner.invoke(main, ["session", "delete", "remote-sess", "--yes"])
    assert delete_result.exit_code == 0
    assert "Deleted" in delete_result.output

    # Verify it's gone
    list_after = runner.invoke(main, ["session", "list"])
    assert "remote-sess" not in list_after.output
