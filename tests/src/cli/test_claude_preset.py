"""Tests for `forge claude preset` CLI commands."""

from __future__ import annotations

import json

from click.testing import CliRunner

from forge.cli.claude import claude
from forge.install.preset import ensure_preset, get_builtin_preset, get_preset_path


class TestPresetShow:
    def test_show_default(self) -> None:
        runner = CliRunner()
        result = runner.invoke(claude, ["preset", "show"])
        assert result.exit_code == 0
        assert "Claude Code Settings Preset" in result.output
        assert "forge hook session-start" in result.output

    def test_show_raw(self) -> None:
        runner = CliRunner()
        result = runner.invoke(claude, ["preset", "show", "--raw"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "hooks" in data
        assert "statusLine" in data

    def test_show_custom_content(self) -> None:
        preset_path = ensure_preset()
        custom = {"hooks": {}, "env": {"MY_VAR": "1"}}
        preset_path.write_text(json.dumps(custom, indent=2))
        runner = CliRunner()
        result = runner.invoke(claude, ["preset", "show", "--raw"])
        assert result.exit_code == 0
        assert "MY_VAR" in result.output

    def test_bare_command_shows_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(claude, ["preset"])
        assert result.exit_code == 2
        assert "Manage Claude Code settings preset" in result.output


class TestPresetReset:
    def test_reset_restores_builtin(self) -> None:
        preset_path = ensure_preset()
        preset_path.write_text('{"custom": true}')
        runner = CliRunner()
        result = runner.invoke(claude, ["preset", "reset", "--yes"])
        assert result.exit_code == 0
        assert "Reset" in result.output
        data = json.loads(preset_path.read_text())
        assert data == get_builtin_preset()

    def test_reset_creates_if_missing(self) -> None:
        preset_path = get_preset_path()
        assert not preset_path.exists()
        runner = CliRunner()
        result = runner.invoke(claude, ["preset", "reset", "--yes"])
        assert result.exit_code == 0
        assert preset_path.is_file()

    def test_reset_prompts_without_force(self) -> None:
        ensure_preset()
        runner = CliRunner()
        result = runner.invoke(claude, ["preset", "reset"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.output
