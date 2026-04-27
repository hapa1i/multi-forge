"""Claude Code settings preset management.

The preset (~/.forge/claude.preset.json) defines what settings Forge merges
into Claude Code's settings.json on ``forge extensions enable``.

Built-in content contains only essential infrastructure:
- hooks: all 13 Forge-managed hook events wiring ``forge hook <name>`` commands
- statusLine: ``forge status-line`` command
- permissions: Write/Edit (required by handoff agent's ``claude -p`` subprocess)

Users customize additional permissions, env vars, etc. via ``forge claude preset edit``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from forge.core.paths import get_forge_home
from forge.core.state import atomic_write_text

PRESET_FILENAME = "claude.preset.json"


def get_preset_path() -> Path:
    """Return the path to ~/.forge/claude.preset.json."""
    return get_forge_home() / PRESET_FILENAME


def get_builtin_preset() -> dict[str, Any]:
    """Return the built-in preset content (factory defaults).

    Contains only essential Forge infrastructure:
    - hooks: all 13 Forge-managed hook events
    - statusLine: forge status-line command
    - permissions: Write/Edit (handoff agent needs these for claude -p)
    """
    return {
        "permissions": {
            "allow": [
                "Write",
                "Edit",
            ]
        },
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
                    "matcher": "Read",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "forge hook read-hygiene",
                            "timeout": 5,
                        }
                    ],
                },
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
                    "hooks": [
                        {
                            "type": "command",
                            "command": "forge hook pre-compact",
                            "timeout": 10,
                        }
                    ],
                }
            ],
            "PostCompact": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "forge hook post-compact",
                            "timeout": 5,
                        }
                    ],
                }
            ],
            "WorktreeCreate": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "forge hook worktree-create",
                            "timeout": 30,
                        }
                    ],
                }
            ],
            "SubagentStop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "forge hook subagent-stop",
                            "timeout": 10,
                        }
                    ],
                }
            ],
            "TeammateIdle": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "forge hook teammate-idle",
                            "timeout": 60,
                        }
                    ]
                }
            ],
            "TaskCompleted": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "forge hook task-completed",
                            "timeout": 60,
                        }
                    ]
                }
            ],
            "SessionEnd": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "forge hook session-end",
                            "timeout": 5,
                        }
                    ]
                }
            ],
        },
        "statusLine": {
            "type": "command",
            "command": "forge status-line",
            "padding": 0,
        },
    }


def get_builtin_preset_json() -> str:
    """Return the built-in preset as formatted JSON."""
    return json.dumps(get_builtin_preset(), indent=2) + "\n"


def ensure_preset() -> Path:
    """Ensure the preset file exists, creating from built-in if missing.

    Returns the path to the preset file. Idempotent — existing files
    are never overwritten.
    """
    preset_path = get_preset_path()
    if not preset_path.is_file():
        preset_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(preset_path, get_builtin_preset_json())
        os.chmod(str(preset_path), 0o600)
    return preset_path


class PresetCorruptedError(Exception):
    """Raised when the preset file contains invalid JSON or is not a dict."""


def load_preset() -> dict[str, Any]:
    """Load the preset, auto-creating from built-in if missing.

    Raises PresetCorruptedError with actionable message if the file
    contains invalid JSON or is not a JSON object.
    """
    preset_path = ensure_preset()
    try:
        with open(preset_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise PresetCorruptedError(
            f"Preset file has invalid JSON: {preset_path}\n"
            f"  Error: {e}\n"
            f"  Fix with: forge claude preset edit\n"
            f"  Or reset: forge claude preset reset"
        ) from e
    if not isinstance(data, dict):
        raise PresetCorruptedError(
            f"Preset must be a JSON object, got {type(data).__name__}: {preset_path}\n"
            f"  Fix with: forge claude preset edit\n"
            f"  Or reset: forge claude preset reset"
        )
    return data
