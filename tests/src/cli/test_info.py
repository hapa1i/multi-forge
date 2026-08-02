"""Tests for `forge info` (global dashboard, homed in cli/)."""

from __future__ import annotations

import json

from click.testing import CliRunner
from pytest import MonkeyPatch, fixture

from forge.cli.main import main


@fixture
def runner():
    return CliRunner()


class TestInfoCommand:
    def test_human_output_shows_sections(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info"])

        assert result.exit_code == 0
        assert "Forge Info" in result.stdout
        assert "System" in result.stdout
        assert "Installations" in result.stdout
        assert "Proxies" in result.stdout
        assert "Recent Sessions" in result.stdout

    def test_json_output_shape(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        for key in ("forge_version", "forge_home", "claude_code", "installations", "proxies", "sessions"):
            assert key in data
        assert set(data["claude_code"]) == {"path", "version"}


class TestClaudeVersionDedup:
    """The claude version must come from install/version.py, not a local parse.

    The old inline copy in install/cli.py had drifted from _run_claude_version
    (whole stripped string vs first token); the shared helper is now the only
    parse in src/.
    """

    def test_version_comes_from_shared_helper(self, runner: CliRunner, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/claude" if cmd == "claude" else None)
        monkeypatch.setattr("forge.install.version.get_claude_runtime_version", lambda: "9.9.9")

        result = runner.invoke(main, ["info", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["claude_code"] == {"path": "/usr/local/bin/claude", "version": "9.9.9"}

    def test_no_claude_binary_reports_null_without_calling_helper(
        self, runner: CliRunner, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda cmd: None)

        def _fail() -> str:
            raise AssertionError("helper must not run when claude is absent")

        monkeypatch.setattr("forge.install.version.get_claude_runtime_version", _fail)

        result = runner.invoke(main, ["info", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["claude_code"] == {"path": None, "version": None}
