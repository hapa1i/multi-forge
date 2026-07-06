"""Tests for ExecutionContext and path derivation utilities."""

from __future__ import annotations

from pathlib import Path

from forge.core.ops.context import (
    ExecutionContext,
    _find_main_repo_root,
    find_forge_root,
)


class TestFindMainRepoRoot:
    """Tests for _find_main_repo_root."""

    def test_regular_repo_returns_same_path(self, tmp_path: Path) -> None:
        # Regular repo: .git is a directory
        (tmp_path / ".git").mkdir()

        result = _find_main_repo_root(tmp_path)
        assert result == tmp_path

    def test_worktree_finds_main_repo(self, tmp_path: Path) -> None:
        # Setup: main repo at tmp_path/main with worktree at tmp_path/wt
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        (main_repo / ".git").mkdir()
        (main_repo / ".git" / "worktrees").mkdir()
        (main_repo / ".git" / "worktrees" / "feature").mkdir()

        worktree = tmp_path / "wt"
        worktree.mkdir()
        gitdir = main_repo / ".git" / "worktrees" / "feature"
        (worktree / ".git").write_text(f"gitdir: {gitdir}")

        result = _find_main_repo_root(worktree)
        assert result == main_repo

    def test_worktree_relative_gitdir(self, tmp_path: Path) -> None:
        # Some git versions use relative paths in the gitdir file
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        (main_repo / ".git").mkdir()
        (main_repo / ".git" / "worktrees").mkdir()
        (main_repo / ".git" / "worktrees" / "feature").mkdir()

        worktree = tmp_path / "wt"
        worktree.mkdir()
        # Relative path from worktree to gitdir
        (worktree / ".git").write_text("gitdir: ../main/.git/worktrees/feature")

        result = _find_main_repo_root(worktree)
        assert result == main_repo

    def test_fallback_on_invalid_gitdir(self, tmp_path: Path) -> None:
        # If .git file has invalid content, fallback to worktree_root
        (tmp_path / ".git").write_text("invalid content")

        result = _find_main_repo_root(tmp_path)
        assert result == tmp_path


class TestExecutionContextFromCwd:
    """Tests for ExecutionContext.from_cwd()."""

    def test_not_in_git_repo(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)

        ctx = ExecutionContext.from_cwd()

        assert ctx.cwd == tmp_path
        assert ctx.worktree_root == tmp_path
        assert ctx.project_root == tmp_path

    def test_in_regular_git_repo(self, tmp_path: Path, monkeypatch) -> None:
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "src"
        subdir.mkdir()
        monkeypatch.chdir(subdir)

        ctx = ExecutionContext.from_cwd()

        assert ctx.cwd == subdir
        assert ctx.worktree_root == tmp_path
        assert ctx.project_root == tmp_path

    def test_explicit_cwd_parameter(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "deep" / "nested"
        subdir.mkdir(parents=True)

        ctx = ExecutionContext.from_cwd(cwd=subdir)

        assert ctx.cwd == subdir
        assert ctx.worktree_root == tmp_path
        assert ctx.project_root == tmp_path

    def test_in_git_worktree(self, tmp_path: Path, monkeypatch) -> None:
        # Setup main repo
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        (main_repo / ".git").mkdir()
        (main_repo / ".git" / "worktrees").mkdir()
        (main_repo / ".git" / "worktrees" / "feature").mkdir()

        # Setup worktree
        worktree = tmp_path / "wt"
        worktree.mkdir()
        gitdir = main_repo / ".git" / "worktrees" / "feature"
        (worktree / ".git").write_text(f"gitdir: {gitdir}")

        monkeypatch.chdir(worktree)

        ctx = ExecutionContext.from_cwd()

        assert ctx.cwd == worktree
        assert ctx.worktree_root == worktree
        assert ctx.project_root == main_repo

    def test_forge_root_found(self, tmp_path: Path, monkeypatch) -> None:
        """ExecutionContext.forge_root is set when .forge/ exists."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".forge").mkdir()
        subdir = tmp_path / "src"
        subdir.mkdir()
        monkeypatch.chdir(subdir)

        ctx = ExecutionContext.from_cwd()

        assert ctx.forge_root == tmp_path

    def test_forge_root_none_when_missing(self, tmp_path: Path, monkeypatch) -> None:
        """ExecutionContext.forge_root is None when no .forge/ exists."""
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "src"
        subdir.mkdir()
        monkeypatch.chdir(subdir)

        ctx = ExecutionContext.from_cwd()

        assert ctx.forge_root is None

    def test_forge_root_in_subfolder(self, tmp_path: Path) -> None:
        """forge_root found in a subfolder of the git repo."""
        (tmp_path / ".git").mkdir()
        poc = tmp_path / "experiments" / "poc"
        poc.mkdir(parents=True)
        (poc / ".forge").mkdir()
        deep = poc / "src" / "module"
        deep.mkdir(parents=True)

        ctx = ExecutionContext.from_cwd(cwd=deep)

        assert ctx.worktree_root == tmp_path
        assert ctx.forge_root == poc


class TestFindForgeRoot:
    """Tests for find_forge_root."""

    def test_finds_forge_directory(self, tmp_path: Path) -> None:
        (tmp_path / ".forge").mkdir()
        subdir = tmp_path / "src" / "module"
        subdir.mkdir(parents=True)

        result = find_forge_root(subdir)
        assert result == tmp_path

    def test_returns_none_when_no_forge(self, tmp_path: Path) -> None:
        subdir = tmp_path / "some" / "dir"
        subdir.mkdir(parents=True)

        result = find_forge_root(subdir)
        assert result is None

    def test_finds_forge_at_start(self, tmp_path: Path) -> None:
        (tmp_path / ".forge").mkdir()

        result = find_forge_root(tmp_path)
        assert result == tmp_path

    def test_finds_nested_forge(self, tmp_path: Path) -> None:
        """Finds .forge/ in a subfolder, not at git root."""
        poc = tmp_path / "experiments" / "poc"
        poc.mkdir(parents=True)
        (poc / ".forge").mkdir()
        deep = poc / "src"
        deep.mkdir()

        result = find_forge_root(deep)
        assert result == poc

    def test_stops_at_git_boundary(self, tmp_path: Path) -> None:
        """Does not escape into a parent repo's .forge/."""
        # Parent project has .forge/, child repo does not
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / ".forge").mkdir()

        child = parent / "child"
        child.mkdir()
        (child / ".git").mkdir()  # Git boundary
        deep = child / "src"
        deep.mkdir()

        result = find_forge_root(deep)
        assert result is None

    def test_finds_forge_at_git_root(self, tmp_path: Path) -> None:
        """Finds .forge/ when it lives alongside .git at the repo root."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".forge").mkdir()
        deep = tmp_path / "src" / "module"
        deep.mkdir(parents=True)

        result = find_forge_root(deep)
        assert result == tmp_path

    def test_finds_forge_below_git_root(self, tmp_path: Path) -> None:
        """Finds .forge/ in a subdirectory of the git repo."""
        (tmp_path / ".git").mkdir()
        app = tmp_path / "packages" / "app"
        app.mkdir(parents=True)
        (app / ".forge").mkdir()
        deep = app / "src"
        deep.mkdir()

        result = find_forge_root(deep)
        assert result == app
