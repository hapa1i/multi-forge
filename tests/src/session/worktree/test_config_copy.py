"""Unit tests for config copy utilities (no Docker required)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from forge.session.worktree.config_copy import (
    DEFAULT_CONFIG_ALLOWLIST,
    ConfigCopyResult,
    _copy_single,
    _is_glob_pattern,
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

        assert "docker/certs" in result.copied
        assert (target / "docker" / "certs" / "ca.pem").read_text() == "cert"


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
