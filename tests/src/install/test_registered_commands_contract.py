"""Contract tests for Forge-registered runtime command bytes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from forge.install.codex_hooks import get_builtin_codex_entries
from forge.install.preset import get_builtin_preset
from forge.install.settings_merge import merge_hooks, unmerge


def _rendered_hook_entries() -> list[tuple[str, Any, str, int | None]]:
    rows: list[tuple[str, Any, str, int | None]] = []
    for event_key, entries in get_builtin_preset()["hooks"].items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                rows.append(
                    (
                        event_key,
                        entry.get("matcher"),
                        hook["command"],
                        hook.get("timeout"),
                    )
                )
    return rows


def test_claude_hook_entries_are_pinned_by_event_matcher_command_and_timeout() -> None:
    """Pin entries, not just command strings, so matcher/timeout drift is visible."""
    assert _rendered_hook_entries() == [
        ("SessionStart", None, "forge hook session-start", None),
        ("PreToolUse", "Read", "forge hook read-hygiene", 5),
        ("PreToolUse", "ExitPlanMode", "forge hook exit-plan-mode", None),
        ("PreToolUse", "Write", "forge hook policy-check", 60),
        ("PreToolUse", "Edit", "forge hook policy-check", 60),
        ("PostToolUse", "Write", "forge hook plan-write", None),
        ("Stop", None, "forge hook stop", None),
        ("StopFailure", None, "forge hook stop-failure", None),
        ("UserPromptSubmit", None, "forge hook user-prompt-submit", None),
        ("PreCompact", None, "forge hook pre-compact", 10),
        ("PostCompact", None, "forge hook post-compact", 5),
        ("WorktreeCreate", None, "forge hook worktree-create", 30),
        ("SubagentStop", None, "forge hook subagent-stop", 10),
        ("TeammateIdle", None, "forge hook teammate-idle", 60),
        ("TaskCompleted", None, "forge hook task-completed", 60),
        ("SessionEnd", None, "forge hook session-end", 5),
    ]


def test_statusline_command_is_pinned() -> None:
    status_line = get_builtin_preset()["statusLine"]
    assert status_line == {
        "type": "command",
        "command": "forge status-line",
        "padding": 0,
    }


def test_codex_hook_commands_are_pinned() -> None:
    assert [(entry.event, entry.command, entry.timeout) for entry in get_builtin_codex_entries()] == [
        ("SessionStart", "forge hook codex-session-start", 60),
        ("PreToolUse", "forge hook codex-policy-check", 60),
    ]


def test_merge_hooks_then_unmerge_preserves_non_forge_sibling() -> None:
    custom_session_start = {"hooks": [{"type": "command", "command": "custom session-start"}]}
    settings = {"hooks": {"SessionStart": [custom_session_start]}}
    before = deepcopy(settings)

    tracking = merge_hooks(settings, "SessionStart", deepcopy(get_builtin_preset()["hooks"]["SessionStart"]))
    assert len(tracking) == 1
    assert settings["hooks"]["SessionStart"] == [
        custom_session_start,
        get_builtin_preset()["hooks"]["SessionStart"][0],
    ]

    unmerge(settings, tracking)

    assert settings == before
