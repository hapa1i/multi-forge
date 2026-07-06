"""Unit tests for hook installation detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.install.hooks import (
    entry_is_forge_hook,
    has_forge_hook,
    has_forge_hooks,
    is_forge_hook_command,
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """Project directory with .claude/ structure."""
    (tmp_path / ".claude").mkdir()
    return tmp_path


def _write_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


FORGE_SESSION_START = {
    "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "forge hook session-start"}]}]}
}

FORGE_PRE_TOOL_USE = {
    "hooks": {
        "PreToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "forge hook policy-check"}]}]
    }
}

FORGE_STOP = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "forge hook stop"}]}]}}


class TestForgeHookPredicate:
    @pytest.mark.parametrize(
        "command",
        [
            "forge hook stop",
            "/opt/multi-forge/bin/forge hook stop",
            '"/opt/my tools/forge" hook stop',
        ],
    )
    def test_matches_forge_hook_invocation(self, command: str) -> None:
        assert is_forge_hook_command(command) is True

    def test_matches_specific_handler(self) -> None:
        assert is_forge_hook_command("forge hook policy-check", "policy-check") is True
        assert is_forge_hook_command("/opt/bin/forge hook policy-check --json", "policy-check") is True
        assert is_forge_hook_command("forge hook exit-plan-mode", "policy-check") is False
        assert is_forge_hook_command("forge hook", "policy-check") is False

    @pytest.mark.parametrize(
        "command",
        [
            "echo forge hook stop",
            "myforge hook stop",
            "forge-hook stop",
            "forge",
            "",
            '"unterminated',
        ],
    )
    def test_rejects_non_invocations(self, command: str) -> None:
        assert is_forge_hook_command(command) is False

    @pytest.mark.parametrize(
        "entry",
        [
            {"type": "command", "command": "forge hook session-start"},
            {"hooks": [{"type": "command", "command": "forge hook session-start"}]},
        ],
    )
    def test_entry_helper_matches_supported_settings_shapes(self, entry: dict) -> None:
        assert entry_is_forge_hook(entry, "session-start") is True

    def test_entry_helper_can_require_command_type(self) -> None:
        entry = {"command": "forge hook session-start"}

        assert entry_is_forge_hook(entry) is True
        assert entry_is_forge_hook(entry, require_command_type=True) is False

    @pytest.mark.parametrize("hooks_value", [None, 5, True])
    def test_entry_helper_ignores_malformed_nested_hooks_value(self, hooks_value: object) -> None:
        assert entry_is_forge_hook({"hooks": hooks_value}, require_command_type=True) is False


class TestHasForgeHook:
    def test_found_in_local_settings(self, project: Path) -> None:
        _write_settings(project / ".claude" / "settings.local.json", FORGE_SESSION_START)
        assert has_forge_hook(project, "SessionStart") is True

    def test_found_in_project_settings(self, project: Path) -> None:
        _write_settings(project / ".claude" / "settings.json", FORGE_SESSION_START)
        assert has_forge_hook(project, "SessionStart") is True

    def test_found_in_user_settings(self, project: Path) -> None:
        # CLAUDE_HOME is set by the isolate_claude_home autouse fixture
        import os

        claude_home = Path(os.environ["CLAUDE_HOME"])
        _write_settings(claude_home / "settings.json", FORGE_SESSION_START)
        assert has_forge_hook(project, "SessionStart") is True

    def test_found_in_user_settings_local(self, project: Path) -> None:
        """forge hook enable --user writes to ~/.claude/settings.local.json."""
        import os

        claude_home = Path(os.environ["CLAUDE_HOME"])
        _write_settings(claude_home / "settings.local.json", FORGE_SESSION_START)
        assert has_forge_hook(project, "SessionStart") is True

    def test_returns_false_when_no_settings(self, project: Path) -> None:
        assert has_forge_hook(project, "SessionStart") is False

    def test_returns_false_when_no_hooks_key(self, project: Path) -> None:
        _write_settings(project / ".claude" / "settings.local.json", {"env": {}})
        assert has_forge_hook(project, "SessionStart") is False

    def test_returns_false_for_non_forge_hook(self, project: Path) -> None:
        """A custom hook that isn't forge should not satisfy the check."""
        data = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "my-custom-hook start"}]}]}}
        _write_settings(project / ".claude" / "settings.local.json", data)
        assert has_forge_hook(project, "SessionStart") is False

    def test_handles_corrupt_json(self, project: Path) -> None:
        (project / ".claude" / "settings.local.json").write_text("{bad json")
        assert has_forge_hook(project, "SessionStart") is False

    def test_handles_empty_hooks_list(self, project: Path) -> None:
        data: dict = {"hooks": {"SessionStart": []}}
        _write_settings(project / ".claude" / "settings.local.json", data)
        assert has_forge_hook(project, "SessionStart") is False

    def test_handles_non_dict_entries_in_hooks_list(self, project: Path) -> None:
        """Malformed hook entries (strings, nulls) should not crash detection."""
        data = {"hooks": {"SessionStart": ["not-a-dict", None, 42]}}
        _write_settings(project / ".claude" / "settings.local.json", data)
        assert has_forge_hook(project, "SessionStart") is False

    def test_handles_non_dict_root(self, project: Path) -> None:
        """Settings file containing a JSON array instead of object."""
        (project / ".claude" / "settings.local.json").write_text("[1, 2, 3]")
        assert has_forge_hook(project, "SessionStart") is False

    @pytest.mark.parametrize(
        "hook_type,settings",
        [
            ("SessionStart", FORGE_SESSION_START),
            ("PreToolUse", FORGE_PRE_TOOL_USE),
            ("Stop", FORGE_STOP),
        ],
    )
    def test_detects_each_hook_type(self, project: Path, hook_type: str, settings: dict) -> None:
        _write_settings(project / ".claude" / "settings.local.json", settings)
        assert has_forge_hook(project, hook_type) is True

    def test_wrong_hook_type_returns_false(self, project: Path) -> None:
        _write_settings(project / ".claude" / "settings.local.json", FORGE_SESSION_START)
        assert has_forge_hook(project, "Stop") is False

    def test_hooks_value_is_list_not_dict(self, project: Path) -> None:
        """{"hooks": []} should not crash — hooks must be a dict."""
        data: dict = {"hooks": []}
        _write_settings(project / ".claude" / "settings.local.json", data)
        assert has_forge_hook(project, "SessionStart") is False

    def test_pre_sync_top_level_command_format(self, project: Path) -> None:
        """Pre-sync format with command at entry level (no nested hooks array)."""
        data = {"hooks": {"SessionStart": [{"type": "command", "command": "forge hook session-start"}]}}
        _write_settings(project / ".claude" / "settings.local.json", data)
        assert has_forge_hook(project, "SessionStart") is True

    def test_absolute_path_forge_command_matches(self, project: Path) -> None:
        data = {
            "hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command": "/opt/bin/forge hook session-start"}]}]
            }
        }
        _write_settings(project / ".claude" / "settings.local.json", data)
        assert has_forge_hook(project, "SessionStart") is True

    def test_contains_only_command_is_not_a_forge_hook(self, project: Path) -> None:
        data = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo forge hook stop"}]}]}}
        _write_settings(project / ".claude" / "settings.local.json", data)
        assert has_forge_hook(project, "Stop") is False

    def test_handler_filters_specific_handler(self, project: Path) -> None:
        """Specific handler should not match a different forge hook handler."""
        data = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "ExitPlanMode", "hooks": [{"type": "command", "command": "forge hook exit-plan-mode"}]}
                ]
            }
        }
        _write_settings(project / ".claude" / "settings.local.json", data)
        # Generic check matches
        assert has_forge_hook(project, "PreToolUse") is True
        # Specific handler does NOT match exit-plan-mode
        assert has_forge_hook(project, "PreToolUse", handler="policy-check") is False

    def test_handler_matches_specific_handler(self, project: Path) -> None:
        _write_settings(project / ".claude" / "settings.local.json", FORGE_PRE_TOOL_USE)
        assert has_forge_hook(project, "PreToolUse", handler="policy-check") is True


class TestHasForgeHooks:
    def test_delegates_to_session_start(self, project: Path) -> None:
        _write_settings(project / ".claude" / "settings.local.json", FORGE_SESSION_START)
        assert has_forge_hooks(project) is True

    def test_returns_false_when_no_hooks(self, project: Path) -> None:
        assert has_forge_hooks(project) is False
