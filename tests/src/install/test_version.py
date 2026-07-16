"""Tests for forge.install.version — Claude Code minimum version enforcement."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.install.version import (
    _VERSION_CACHE_TTL_S,
    MIN_CLAUDE_CODE_VERSION,
    check_minimum_version,
    get_claude_runtime_version,
    reset_version_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Reset version cache before each test."""
    reset_version_cache()


class TestGetClaudeRuntimeVersion:
    def test_returns_version_string(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="2.1.78 (Claude Code)\n", stderr="")
        with patch("forge.install.version.subprocess.run", return_value=mock_result):
            assert get_claude_runtime_version() == "2.1.78"

    def test_strips_claude_code_suffix(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="2.1.80 (Claude Code)", stderr="")
        with patch("forge.install.version.subprocess.run", return_value=mock_result):
            assert get_claude_runtime_version() == "2.1.80"

    def test_handles_version_without_suffix(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="2.1.78\n", stderr="")
        with patch("forge.install.version.subprocess.run", return_value=mock_result):
            assert get_claude_runtime_version() == "2.1.78"

    def test_returns_none_on_not_found(self) -> None:
        with patch("forge.install.version.subprocess.run", side_effect=FileNotFoundError):
            assert get_claude_runtime_version() is None

    def test_returns_none_on_timeout(self) -> None:
        with patch(
            "forge.install.version.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5),
        ):
            assert get_claude_runtime_version() is None

    def test_returns_none_on_nonzero_exit(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
        with patch("forge.install.version.subprocess.run", return_value=mock_result):
            assert get_claude_runtime_version() is None

    def test_returns_none_on_empty_output(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("forge.install.version.subprocess.run", return_value=mock_result):
            assert get_claude_runtime_version() is None

    def test_caches_result(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="2.1.78 (Claude Code)\n", stderr="")
        with patch("forge.install.version.subprocess.run", return_value=mock_result) as mock_run:
            assert get_claude_runtime_version() == "2.1.78"
            assert get_claude_runtime_version() == "2.1.78"
            assert mock_run.call_count == 1

    def test_cache_expires(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="2.1.78 (Claude Code)\n", stderr="")
        with (
            patch("forge.install.version.subprocess.run", return_value=mock_result) as mock_run,
            patch("forge.install.version.time.monotonic") as mock_time,
        ):
            mock_time.return_value = 1000.0
            get_claude_runtime_version()
            assert mock_run.call_count == 1

            # Within TTL — cached
            mock_time.return_value = 1000.0 + _VERSION_CACHE_TTL_S - 1
            get_claude_runtime_version()
            assert mock_run.call_count == 1

            # Past TTL — re-fetched
            mock_time.return_value = 1000.0 + _VERSION_CACHE_TTL_S + 1
            get_claude_runtime_version()
            assert mock_run.call_count == 2


class TestCheckMinimumVersion:
    def test_ok_when_meets_minimum(self) -> None:
        result = check_minimum_version("2.1.78")
        assert result.ok is True
        assert result.version == "2.1.78"
        assert result.minimum == MIN_CLAUDE_CODE_VERSION

    def test_ok_when_exceeds_minimum(self) -> None:
        result = check_minimum_version("2.1.80")
        assert result.ok is True

    def test_ok_with_major_version_bump(self) -> None:
        result = check_minimum_version("3.0.0")
        assert result.ok is True

    def test_fails_when_below_minimum(self) -> None:
        result = check_minimum_version("2.1.70")
        assert result.ok is False
        assert "below" in result.reason
        assert "2.1.70" in result.reason
        assert MIN_CLAUDE_CODE_VERSION in result.reason

    def test_fails_when_version_none(self) -> None:
        with patch("forge.install.version.get_claude_runtime_version", return_value=None):
            result = check_minimum_version()
            assert result.ok is False
            assert result.version is None
            assert "not found" in result.reason.lower()

    def test_fails_when_unparseable(self) -> None:
        result = check_minimum_version("garbage")
        assert result.ok is False
        assert result.version == "garbage"
        assert "parse" in result.reason.lower()

    def test_uses_runtime_detection_when_no_arg(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="2.1.79 (Claude Code)\n", stderr="")
        with patch("forge.install.version.subprocess.run", return_value=mock_result):
            result = check_minimum_version()
            assert result.ok is True
            assert result.version == "2.1.79"

    def test_result_has_correct_minimum(self) -> None:
        result = check_minimum_version("2.1.78")
        assert result.minimum == "2.1.78"


class TestVersionGateOnExtensionsEnable:
    """Verify that ``forge extension enable`` blocks on old Claude Code."""

    def test_enable_blocks_on_old_version(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import extensions

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".claude").mkdir()

        with patch("forge.install.version.get_claude_runtime_version", return_value="2.1.70"):
            runner = CliRunner()
            result = runner.invoke(extensions, ["enable"])
            assert result.exit_code != 0
            assert "below" in result.output or "2.1.70" in result.output

    def test_enable_proceeds_on_good_version(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import extensions

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".claude").mkdir()

        with patch("forge.install.version.get_claude_runtime_version", return_value="2.1.80"):
            runner = CliRunner()
            result = runner.invoke(extensions, ["enable"])
            # Should not fail on version check (may fail on other things like missing files)
            assert "below" not in (result.output or "")
            assert "2.1.80" not in (result.output or "")


class TestVersionGateOnExtensionsSync:
    """Verify that ``forge extension sync`` blocks on old Claude Code."""

    def test_sync_blocks_on_old_version(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import extensions
        from forge.install.models import InstallPlan, InstallScope

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".claude").mkdir()

        preview = InstallPlan(scope="local", mode="copy", profile="minimal", requires_claude_version=True)
        with (
            patch(
                "forge.install.version.get_claude_runtime_version",
                return_value="2.1.70",
            ),
            patch(
                "forge.cli.extensions.find_forge_installation",
                return_value=(InstallScope.LOCAL, tmp_path),
            ),
            patch("forge.cli.extensions.Installer") as installer_class,
        ):
            installer_class.return_value.plan_update.return_value = preview
            runner = CliRunner()
            result = runner.invoke(extensions, ["sync"])
            assert result.exit_code != 0
            assert "below" in result.output or "2.1.70" in result.output
            installer_class.return_value.update.assert_not_called()
