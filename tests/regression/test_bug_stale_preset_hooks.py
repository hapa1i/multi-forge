"""Regression: stale preset files must not suppress built-in Forge hooks.

Root cause: existing preset files preserved the stale hook set indefinitely, so
sync never picked up new hooks added to the built-in preset.

Fix: installer hooks come from the built-in preset even when the user's preset
file is stale.

Affected: src/forge/install/preset.py, src/forge/install/installer.py
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.install.installer import Installer
from forge.install.models import InstallModule, InstallProfile, InstallScope
from forge.install.preset import ensure_preset, get_preset_path
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


@pytest.fixture
def hook_env(tmp_path: Path) -> dict[str, Path]:
    """Minimal installer environment for hook settings tests."""
    forge_home = tmp_path / ".forge"
    forge_home.mkdir()

    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    # _is_repo_checkout() requires both src/forge/ AND an extension dir
    (tmp_path / "src" / "forge").mkdir(parents=True)
    (tmp_path / "src" / "skills").mkdir()

    return {
        "forge_home": forge_home,
        "claude_home": claude_home,
        "repo_root": tmp_path,
    }


def _make_installer(env: dict[str, Path]) -> Installer:
    tracking = TrackingStore(tracking_path=env["forge_home"] / "installed.json")
    return Installer(scope=InstallScope.USER, tracking_store=tracking)


def test_init_uses_builtin_hooks_when_preset_is_stale(
    hook_env: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old preset files should not suppress newly added builtin hooks."""
    monkeypatch.setenv("FORGE_HOME", str(hook_env["forge_home"]))
    monkeypatch.setenv("CLAUDE_HOME", str(hook_env["claude_home"]))

    ensure_preset()
    get_preset_path().write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Write", "Edit"]},
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "forge hook session-start",
                                }
                            ]
                        }
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "ExitPlanMode",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "forge hook exit-plan-mode",
                                }
                            ],
                        },
                        {
                            "matcher": "Write",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "forge hook policy-check",
                                    "timeout": 60,
                                }
                            ],
                        },
                        {
                            "matcher": "Edit",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "forge hook policy-check",
                                    "timeout": 60,
                                }
                            ],
                        },
                    ],
                    "PostToolUse": [
                        {
                            "matcher": "Write",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "forge hook plan-write",
                                }
                            ],
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "forge hook stop",
                                }
                            ]
                        }
                    ],
                    "StopFailure": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "forge hook stop-failure",
                                }
                            ]
                        }
                    ],
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "forge hook user-prompt-submit",
                                }
                            ]
                        }
                    ],
                    "PreCompact": [
                        {
                            "matcher": "auto",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "forge hook pre-compact",
                                    "timeout": 5,
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    installer = _make_installer(hook_env)
    with (
        patch("forge.install.installer.get_forge_source_root", return_value=hook_env["repo_root"]),
        patch("forge.install.installer.get_target_root", return_value=hook_env["claude_home"]),
    ):
        installer.init(
            profile=InstallProfile.STANDARD,
            _modules_override={InstallModule.HOOKS, InstallModule.PERMISSIONS},
        )

    settings = json.loads((hook_env["claude_home"] / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]

    pre_tool_use = hooks["PreToolUse"]
    assert any(entry.get("matcher") == "Read" for entry in pre_tool_use)
    assert "TeammateIdle" in hooks
    assert "TaskCompleted" in hooks
    assert "PostCompact" in hooks
    assert "WorktreeCreate" in hooks
    assert "SubagentStop" in hooks
