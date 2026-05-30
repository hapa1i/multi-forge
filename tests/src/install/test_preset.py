"""Tests for forge.install.preset — Claude Code settings preset management."""

from __future__ import annotations

import json

import pytest

from forge.core.paths import get_forge_home
from forge.install.preset import (
    PRESET_FILENAME,
    PresetCorruptedError,
    ensure_preset,
    get_builtin_preset,
    get_builtin_preset_json,
    get_preset_path,
    load_preset,
)


class TestPresetPath:
    def test_returns_path_under_forge_home(self) -> None:
        assert get_preset_path() == get_forge_home() / PRESET_FILENAME

    def test_filename_is_claude_preset_json(self) -> None:
        assert get_preset_path().name == "claude.preset.json"


class TestBuiltinPreset:
    def test_has_all_hook_types(self) -> None:
        preset = get_builtin_preset()
        hooks = preset["hooks"]
        expected = {
            "SessionStart",
            "SessionEnd",
            "PreToolUse",
            "PostToolUse",
            "Stop",
            "StopFailure",
            "UserPromptSubmit",
            "PreCompact",
            "PostCompact",
            "WorktreeCreate",
            "SubagentStop",
            "TeammateIdle",
            "TaskCompleted",
        }
        assert set(hooks.keys()) == expected

    def test_has_statusline(self) -> None:
        preset = get_builtin_preset()
        assert preset["statusLine"]["command"] == "forge status-line"
        assert preset["statusLine"]["padding"] == 0

    def test_no_env_section(self) -> None:
        preset = get_builtin_preset()
        assert "env" not in preset

    def test_has_write_edit_permissions(self) -> None:
        """The memory writer's claude -p subprocess needs Write/Edit to modify files."""
        preset = get_builtin_preset()
        allow = preset["permissions"]["allow"]
        assert "Write" in allow
        assert "Edit" in allow

    def test_no_opinionated_permissions(self) -> None:
        """Only infrastructure permissions (Write/Edit); no Bash or other tool grants."""
        preset = get_builtin_preset()
        allow = preset["permissions"]["allow"]
        assert set(allow) == {"Write", "Edit"}

    def test_no_opinionated_env_vars(self) -> None:
        preset = get_builtin_preset()
        env = preset.get("env", {})
        assert "CLAUDE_CODE_EFFORT_LEVEL" not in env
        assert "CLAUDE_CODE_DISABLE_AUTO_MEMORY" not in env
        assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" not in env
        assert "CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS" not in env
        assert "DISABLE_AUTOUPDATER" not in env

    def test_json_is_valid(self) -> None:
        content = get_builtin_preset_json()
        data = json.loads(content)
        assert isinstance(data, dict)
        assert data == get_builtin_preset()


class TestEnsurePreset:
    def test_creates_file_when_missing(self) -> None:
        preset_path = get_preset_path()
        assert not preset_path.exists()
        result = ensure_preset()
        assert result == preset_path
        assert preset_path.is_file()

    def test_content_matches_builtin(self) -> None:
        ensure_preset()
        content = get_preset_path().read_text(encoding="utf-8")
        assert json.loads(content) == get_builtin_preset()

    def test_idempotent(self) -> None:
        ensure_preset()
        # Write custom content
        preset_path = get_preset_path()
        custom = {"env": {"MY_VAR": "1"}}
        preset_path.write_text(json.dumps(custom))
        # ensure_preset should NOT overwrite
        ensure_preset()
        assert json.loads(preset_path.read_text()) == custom

    def test_file_permissions(self) -> None:
        path = ensure_preset()
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600


class TestLoadPreset:
    def test_returns_builtin_on_first_call(self) -> None:
        data = load_preset()
        assert data == get_builtin_preset()

    def test_auto_creates_file(self) -> None:
        preset_path = get_preset_path()
        assert not preset_path.exists()
        load_preset()
        assert preset_path.is_file()

    def test_returns_custom_content(self) -> None:
        preset_path = ensure_preset()
        custom = {"hooks": {}, "env": {"CUSTOM": "yes"}}
        preset_path.write_text(json.dumps(custom))
        assert load_preset() == custom

    def test_raises_on_invalid_json(self) -> None:
        preset_path = ensure_preset()
        preset_path.write_text("not valid json {{{")
        with pytest.raises(PresetCorruptedError, match="invalid JSON"):
            load_preset()

    def test_raises_on_non_dict_json(self) -> None:
        preset_path = ensure_preset()
        preset_path.write_text('["an", "array"]')
        with pytest.raises(PresetCorruptedError, match="must be a JSON object"):
            load_preset()

    def test_error_message_includes_recovery_hints(self) -> None:
        preset_path = ensure_preset()
        preset_path.write_text("broken")
        with pytest.raises(PresetCorruptedError, match="forge claude preset edit"):
            load_preset()
