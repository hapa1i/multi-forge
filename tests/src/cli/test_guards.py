"""Tests for CWD validation guards."""

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.cli.guards import (
    enforce_target_project_compatibility,
    require_main_repo_root,
    require_repo_root,
)


def test_target_project_compatibility_guard_uses_shared_recovery(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "project.toml").write_text(
        'schema_version = 1\nrequired_forge = ">=9999"\n',
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        enforce_target_project_compatibility(tmp_path)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "requires Forge >=9999" in captured.err
    assert "satisfying required_forge" in captured.err
    assert "global Forge" not in captured.err


class TestRequireRepoRoot:
    """Tests for require_repo_root()."""

    def test_at_repo_root_returns_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        with patch("forge.session.claude.paths.find_project_root", return_value=tmp_path):
            result = require_repo_root()
        assert result == tmp_path.resolve()

    def test_in_subfolder_exits(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        subfolder = tmp_path / "src"
        subfolder.mkdir()
        monkeypatch.chdir(subfolder)
        with patch("forge.session.claude.paths.find_project_root", return_value=tmp_path):
            with pytest.raises(SystemExit) as exc_info:
                require_repo_root()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "repository root" in captured.err
        assert "subdirectory" in captured.err

    def test_in_subfolder_shows_tip(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        subfolder = tmp_path / "src"
        subfolder.mkdir()
        monkeypatch.chdir(subfolder)
        with patch("forge.session.claude.paths.find_project_root", return_value=tmp_path):
            with pytest.raises(SystemExit):
                require_repo_root()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Tip:" in captured.err
        assert "cd " in captured.err

    def test_not_in_repo_exits(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with patch(
            "forge.session.claude.paths.find_project_root",
            side_effect=FileNotFoundError("No git repository found"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                require_repo_root()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Not in a git repository" in captured.err

    def test_not_in_repo_no_tip(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with patch(
            "forge.session.claude.paths.find_project_root",
            side_effect=FileNotFoundError("No git repository found"),
        ):
            with pytest.raises(SystemExit):
                require_repo_root()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Tip:" not in captured.err

    def test_at_forge_root_in_subfolder_returns_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """CWD at a nested Forge project root (.forge/ present) should be accepted."""
        nested = tmp_path / "packages" / "app"
        nested.mkdir(parents=True)
        (nested / ".forge").mkdir()
        monkeypatch.chdir(nested)
        with patch("forge.session.claude.paths.find_project_root", return_value=tmp_path):
            result = require_repo_root()
        assert result == nested.resolve()


class TestRequireMainRepoRoot:
    """Tests for require_main_repo_root()."""

    def test_at_main_repo_root_returns_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        with (
            patch("forge.session.claude.paths.find_project_root", return_value=tmp_path),
            patch("forge.session.worktree.get_main_repo_root", return_value=tmp_path),
        ):
            result = require_main_repo_root()
        assert result == tmp_path.resolve()

    def test_in_child_worktree_exits(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        worktree_root = tmp_path / "project-feature"
        worktree_root.mkdir()
        main_root = tmp_path / "project"
        main_root.mkdir()
        monkeypatch.chdir(worktree_root)
        with (
            patch(
                "forge.session.claude.paths.find_project_root",
                return_value=worktree_root,
            ),
            patch("forge.session.worktree.get_main_repo_root", return_value=main_root),
        ):
            with pytest.raises(SystemExit) as exc_info:
                require_main_repo_root()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "child worktree" in captured.err

    def test_in_child_worktree_shows_tip_to_main_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        worktree_root = tmp_path / "project-feature"
        worktree_root.mkdir()
        main_root = tmp_path / "project"
        main_root.mkdir()
        monkeypatch.chdir(worktree_root)
        with (
            patch(
                "forge.session.claude.paths.find_project_root",
                return_value=worktree_root,
            ),
            patch("forge.session.worktree.get_main_repo_root", return_value=main_root),
        ):
            with pytest.raises(SystemExit):
                require_main_repo_root()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Tip:" in captured.err
        assert "cd " in captured.err

    def test_subfolder_of_child_worktree_points_to_main_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """From <child-worktree>/src, error should point to main repo, not child root."""
        worktree_root = tmp_path / "project-feature"
        subfolder = worktree_root / "src"
        subfolder.mkdir(parents=True)
        main_root = tmp_path / "project"
        main_root.mkdir()
        monkeypatch.chdir(subfolder)
        with (
            patch(
                "forge.session.claude.paths.find_project_root",
                return_value=worktree_root,
            ),
            patch("forge.session.worktree.get_main_repo_root", return_value=main_root),
        ):
            with pytest.raises(SystemExit) as exc_info:
                require_main_repo_root()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "child worktree" in captured.err
        assert "subdirectory" not in captured.err

    def test_not_in_repo_exits(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with patch(
            "forge.session.claude.paths.find_project_root",
            side_effect=FileNotFoundError("No git repository found"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                require_main_repo_root()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Not in a git repository" in captured.err

    def test_git_not_found_allows(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """If git binary is missing, allow through (find_project_root passed)."""
        from forge.session.exceptions import GitNotFoundError

        monkeypatch.chdir(tmp_path)
        with (
            patch("forge.session.claude.paths.find_project_root", return_value=tmp_path),
            patch(
                "forge.session.worktree.get_main_repo_root",
                side_effect=GitNotFoundError(),
            ),
        ):
            result = require_main_repo_root()
        assert result == tmp_path.resolve()

    def test_git_worktree_error_allows(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """If git rev-parse fails, allow through (find_project_root passed)."""
        from forge.session.exceptions import GitWorktreeError

        monkeypatch.chdir(tmp_path)
        with (
            patch("forge.session.claude.paths.find_project_root", return_value=tmp_path),
            patch(
                "forge.session.worktree.get_main_repo_root",
                side_effect=GitWorktreeError("rev-parse", "failed", 1),
            ),
        ):
            result = require_main_repo_root()
        assert result == tmp_path.resolve()

    def test_subfolder_of_main_repo_exits(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Subfolder of main repo shows subdirectory error."""
        subfolder = tmp_path / "src"
        subfolder.mkdir()
        monkeypatch.chdir(subfolder)
        with (
            patch("forge.session.claude.paths.find_project_root", return_value=tmp_path),
            patch("forge.session.worktree.get_main_repo_root", return_value=tmp_path),
        ):
            with pytest.raises(SystemExit) as exc_info:
                require_main_repo_root()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "subdirectory" in captured.err

    def test_at_forge_root_in_subfolder_of_main_repo_returns_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Nested Forge project root should be accepted for --worktree commands."""
        nested = tmp_path / "packages" / "app"
        nested.mkdir(parents=True)
        (nested / ".forge").mkdir()
        monkeypatch.chdir(nested)
        with (
            patch("forge.session.claude.paths.find_project_root", return_value=tmp_path),
            patch("forge.session.worktree.get_main_repo_root", return_value=tmp_path),
        ):
            result = require_main_repo_root()
        assert result == nested.resolve()
