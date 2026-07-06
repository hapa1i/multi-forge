"""Tests for forge.core.paths — display_path home-directory shortening."""

from __future__ import annotations

from pathlib import Path

from forge.core.paths import display_path, find_git_root


class TestDisplayPath:
    def test_replaces_home_prefix(self):
        home = str(Path.home())
        assert display_path(f"{home}/workspace/project") == "~/workspace/project"

    def test_exact_home_returns_tilde(self):
        assert display_path(str(Path.home())) == "~"

    def test_non_home_path_unchanged(self):
        assert display_path("/tmp/something") == "/tmp/something"

    def test_relative_path_unchanged(self):
        assert display_path("relative/path") == "relative/path"

    def test_accepts_path_object(self):
        home = Path.home()
        assert display_path(home / "workspace") == "~/workspace"

    def test_partial_match_not_shortened(self):
        home = str(Path.home())
        assert display_path(f"{home}extra/path") == f"{home}extra/path"

    def test_empty_string(self):
        assert display_path("") == ""


class TestFindGitRoot:
    def test_finds_git_in_current_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        assert find_git_root(tmp_path) == tmp_path.resolve()

    def test_finds_git_in_parent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        child = tmp_path / "src" / "deep"
        child.mkdir(parents=True)
        assert find_git_root(child) == tmp_path.resolve()

    def test_returns_none_outside_git(self, tmp_path: Path) -> None:
        assert find_git_root(tmp_path) is None

    def test_finds_git_file_worktree(self, tmp_path: Path) -> None:
        (tmp_path / ".git").write_text("gitdir: /some/path")
        assert find_git_root(tmp_path) == tmp_path.resolve()

    def test_resolves_symlinked_nested_start(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        nested = repo / "src" / "pkg"
        nested.mkdir(parents=True)
        (repo / ".git").mkdir()
        linked = tmp_path / "linked-pkg"
        linked.symlink_to(nested, target_is_directory=True)

        assert find_git_root(linked) == repo.resolve()
