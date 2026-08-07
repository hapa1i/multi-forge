"""Regression D010: incognito worktree creation must require the main checkout.

Root cause: the incognito shortcut called ``require_repo_root`` unconditionally,
so ``--worktree`` was the only worktree-creating session command that accepted a
linked worktree as its launch root.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.regression


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], capture_output=True, check=True)
    for key, value in (("user.email", "test@test.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], cwd=path, capture_output=True, check=True)
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True)


def test_incognito_worktree_rejects_linked_worktree_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_repo = tmp_path / "main"
    linked_worktree = tmp_path / "linked"
    _init_git_repo(main_repo)
    subprocess.run(
        ["git", "worktree", "add", "-b", "linked", str(linked_worktree)],
        cwd=main_repo,
        capture_output=True,
        check=True,
    )
    monkeypatch.chdir(linked_worktree)
    monkeypatch.setenv("COLUMNS", "500")

    with patch("forge.cli.session_lifecycle.launch_new_session", return_value=0) as launch:
        result = CliRunner().invoke(
            main,
            ["session", "incognito", "guard-drift", "--worktree", "--no-proxy"],
        )

    assert result.exit_code == 1
    assert "Cannot create worktrees from inside a child worktree" in result.output
    assert str(main_repo.resolve()) in result.output
    launch.assert_not_called()
