"""Unit tests for config copy utilities (no Docker required)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.session.worktree.config_copy import (
    DEFAULT_CONFIG_ALLOWLIST,
    ConfigCopyResult,
    _copy_single,
    _is_glob_pattern,
    _resolve_glob,
    copy_runtime_config,
    get_copied_config_files,
)


class TestIsGlobPattern:
    def test_double_star(self) -> None:
        assert _is_glob_pattern("**/.claude/settings.json") is True

    def test_single_star(self) -> None:
        assert _is_glob_pattern("*.json") is True

    def test_question_mark(self) -> None:
        assert _is_glob_pattern("file?.txt") is True

    def test_bracket(self) -> None:
        assert _is_glob_pattern("file[0-9].txt") is True

    def test_exact_path(self) -> None:
        assert _is_glob_pattern(".env") is False

    def test_nested_exact_path(self) -> None:
        assert _is_glob_pattern("docker/certs") is False


class TestCopySingle:
    def test_copies_file(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        (source / ".env").write_text("SECRET=val")

        result = ConfigCopyResult()
        with patch("forge.session.worktree.config_copy.is_file_tracked", return_value=False):
            _copy_single(source, target, ".env", result)

        assert ".env" in result.copied
        assert (target / ".env").read_text() == "SECRET=val"

    def test_skips_existing(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        (source / ".env").write_text("SOURCE")
        (target / ".env").write_text("TARGET")

        result = ConfigCopyResult()
        _copy_single(source, target, ".env", result)

        assert ".env" in result.skipped_exists
        assert (target / ".env").read_text() == "TARGET"

    def test_skips_not_found(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        result = ConfigCopyResult()
        _copy_single(source, target, ".env", result)

        assert ".env" in result.skipped_not_found

    def test_skips_tracked(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        (source / ".envrc").write_text("content")

        result = ConfigCopyResult()
        with patch("forge.session.worktree.config_copy.is_file_tracked", return_value=True):
            _copy_single(source, target, ".envrc", result)

        assert ".envrc" in result.skipped_tracked

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        (source / ".claude").mkdir()
        (source / ".claude" / "settings.local.json").write_text("{}")

        result = ConfigCopyResult()
        with patch("forge.session.worktree.config_copy.is_file_tracked", return_value=False):
            _copy_single(source, target, ".claude/settings.local.json", result)

        assert ".claude/settings.local.json" in result.copied
        assert (target / ".claude" / "settings.local.json").read_text() == "{}"

    def test_copies_directory(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        (source / "docker" / "certs").mkdir(parents=True)
        (source / "docker" / "certs" / "ca.pem").write_text("cert")

        result = ConfigCopyResult()
        _copy_single(source, target, "docker/certs", result)

        assert result.copied == ["docker/certs/ca.pem"]
        assert (target / "docker" / "certs" / "ca.pem").read_text() == "cert"

    def test_copies_directory_per_file_with_safety_checks(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source_certs = source / "docker" / "certs"
        target_certs = target / "docker" / "certs"
        source_certs.mkdir(parents=True)
        target_certs.mkdir(parents=True)
        for name in ("existing.pem", "tracked.pem", "local.pem"):
            (source_certs / name).write_text(f"source-{name}")
        (target_certs / "existing.pem").write_text("target-existing")
        excluded = source_certs / "node_modules" / "vendor.pem"
        excluded.parent.mkdir()
        excluded.write_text("vendor")

        result = ConfigCopyResult()
        with patch(
            "forge.session.worktree.config_copy.is_file_tracked",
            side_effect=lambda path, _cwd: path.name == "tracked.pem",
        ):
            _copy_single(source, target, "docker/certs", result)

        assert result.copied == ["docker/certs/local.pem"]
        assert result.skipped_exists == ["docker/certs/existing.pem"]
        assert result.skipped_tracked == ["docker/certs/tracked.pem"]
        assert (target_certs / "existing.pem").read_text() == "target-existing"
        assert not (target_certs / "tracked.pem").exists()
        assert not (target_certs / "node_modules").exists()

    def test_directory_does_not_merge_through_destination_symlink(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        outside = tmp_path / "outside"
        (source / "docker" / "certs").mkdir(parents=True)
        (source / "docker" / "certs" / "ca.pem").write_text("cert")
        (target / "docker").mkdir(parents=True)
        outside.mkdir()
        (target / "docker" / "certs").symlink_to(outside, target_is_directory=True)

        result = ConfigCopyResult()
        _copy_single(source, target, "docker/certs", result)

        assert result.skipped_exists == ["docker/certs"]
        assert not (outside / "ca.pem").exists()

    def test_copy_failure_is_reported_per_directory_file(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        (source / "docker" / "certs").mkdir(parents=True)
        (source / "docker" / "certs" / "ca.pem").write_text("cert")
        target.mkdir()

        result = ConfigCopyResult()
        with (
            patch("forge.session.worktree.config_copy.is_file_tracked", return_value=False),
            patch("forge.session.worktree.config_copy.shutil.copy2", side_effect=OSError("disk full")),
        ):
            _copy_single(source, target, "docker/certs", result)

        assert result.failed == [("docker/certs/ca.pem", "disk full")]


class TestResolveGlob:
    def test_excludes_git_and_node_modules_components(self, tmp_path: Path) -> None:
        included = tmp_path / "app" / ".mcp.json"
        included.parent.mkdir()
        included.write_text("included")
        for relative in (
            Path("node_modules/pkg/.mcp.json"),
            Path("nested/node_modules/pkg/.mcp.json"),
            Path(".git/cache/.mcp.json"),
            Path("nested/.git/cache/.mcp.json"),
        ):
            path = tmp_path / relative
            path.parent.mkdir(parents=True)
            path.write_text("excluded")

        assert _resolve_glob(tmp_path, "**/.mcp.json") == [Path("app/.mcp.json")]


class TestCopyRuntimeConfigGlob:
    """Test glob pattern handling in copy_runtime_config."""

    def test_copies_claude_settings_local(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        (source / ".claude").mkdir()
        (source / ".claude" / "settings.local.json").write_text('{"user": true}')

        with patch("forge.session.worktree.config_copy.is_file_tracked", return_value=False):
            result = copy_runtime_config(source, target)

        assert ".claude/settings.local.json" in result.copied
        assert json.loads((target / ".claude" / "settings.local.json").read_text()) == {"user": True}

    def test_copies_nested_claude_settings(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        (source / "sub" / ".claude").mkdir(parents=True)
        (source / "sub" / ".claude" / "settings.local.json").write_text('{"nested": true}')

        with patch("forge.session.worktree.config_copy.is_file_tracked", return_value=False):
            result = copy_runtime_config(source, target)

        assert "sub/.claude/settings.local.json" in result.copied

    def test_glob_no_matches_goes_to_skipped(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        result = copy_runtime_config(source, target)

        for entry in DEFAULT_CONFIG_ALLOWLIST:
            assert entry in result.skipped_not_found

    def test_custom_glob_allowlist(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()
        (source / "sub").mkdir()
        (source / "sub" / "custom.conf").write_text("val")

        with patch("forge.session.worktree.config_copy.is_file_tracked", return_value=False):
            result = copy_runtime_config(source, target, allowlist=("**/custom.conf",))

        assert "sub/custom.conf" in result.copied


class TestGetCopiedConfigFilesGlob:
    """Test glob handling in get_copied_config_files."""

    def test_finds_claude_settings_local(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.local.json").write_text("{}")

        with patch("forge.session.worktree.config_copy.is_file_tracked", return_value=False):
            result = get_copied_config_files(tmp_path)

        names = [p.name for p in result]
        assert "settings.local.json" in names

    def test_finds_nested_settings(self, tmp_path: Path) -> None:
        (tmp_path / "sub" / ".claude").mkdir(parents=True)
        (tmp_path / "sub" / ".claude" / "settings.local.json").write_text("{}")

        with patch("forge.session.worktree.config_copy.is_file_tracked", return_value=False):
            result = get_copied_config_files(tmp_path)

        paths = [str(p.relative_to(tmp_path)) for p in result]
        assert "sub/.claude/settings.local.json" in paths

    def test_directory_entry_returns_only_untracked_non_excluded_files(self, tmp_path: Path) -> None:
        certs = tmp_path / "docker" / "certs"
        certs.mkdir(parents=True)
        for name in ("tracked.pem", "local.pem"):
            (certs / name).write_text(name)
        excluded = certs / "node_modules" / "vendor.pem"
        excluded.parent.mkdir()
        excluded.write_text("vendor")

        with patch(
            "forge.session.worktree.config_copy.is_file_tracked",
            side_effect=lambda path, _cwd: path.name == "tracked.pem",
        ):
            result = get_copied_config_files(tmp_path)

        assert [path.relative_to(tmp_path) for path in result] == [Path("docker/certs/local.pem")]

    def test_directory_walk_failure_is_logged_and_skipped(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        (tmp_path / "docker" / "certs").mkdir(parents=True)

        with (
            patch("forge.session.worktree.config_copy._directory_files", side_effect=OSError("permission denied")),
            caplog.at_level(logging.DEBUG, logger="forge.session.worktree.config_copy"),
        ):
            result = get_copied_config_files(tmp_path)

        assert result == []
        assert "Skipping unreadable config directory during cleanup discovery" in caplog.text


class TestDefaultAllowlist:
    def test_contains_claude_settings(self) -> None:
        assert "**/.claude/settings.json" in DEFAULT_CONFIG_ALLOWLIST
        assert "**/.claude/settings.local.json" in DEFAULT_CONFIG_ALLOWLIST

    def test_contains_mcp_glob(self) -> None:
        assert "**/.mcp.json" in DEFAULT_CONFIG_ALLOWLIST
        assert "**/.mcp.local.json" in DEFAULT_CONFIG_ALLOWLIST

    def test_contains_root_only_entries(self) -> None:
        assert ".env" in DEFAULT_CONFIG_ALLOWLIST
        assert ".env.local" in DEFAULT_CONFIG_ALLOWLIST
        assert ".envrc" in DEFAULT_CONFIG_ALLOWLIST
        assert "docker/certs" in DEFAULT_CONFIG_ALLOWLIST

    def test_no_root_only_mcp(self) -> None:
        """Root-only .mcp.json replaced by glob version."""
        exact_entries = [e for e in DEFAULT_CONFIG_ALLOWLIST if not _is_glob_pattern(e)]
        assert ".mcp.json" not in exact_entries
        assert ".mcp.local.json" not in exact_entries
