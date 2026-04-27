"""Read hygiene hook: strip extra params from skill instruction file reads.

Skill instruction files (code.md, docs.md, code-openai.md, docs-gemini.md, etc.)
have a strict "file_path only" Read contract defined in SKILL.md. Models often
add offset/limit/pages anyway. This hook silently fixes the call via updatedInput
rather than blocking it — zero token cost, deterministic correction.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SKILL_RESOURCE_RE = re.compile(r"/skills/[^/]+/resources/")
_INSTRUCTION_BASENAME_RE = re.compile(r"^(code|docs)(-[a-z0-9_-]+)?\.md$")
_EXTRA_READ_PARAMS = {"offset", "limit", "pages"}


def _is_skill_instruction_file(file_path: str) -> bool:
    """Check if a path is a skill instruction file with a strict Read contract.

    Three checks, all must pass:
    1. Path contains /skills/<name>/resources/
    2. File is an immediate child of resources/ (parent dir is "resources")
    3. Basename matches {mode}.md or {mode}-{family}.md
    """
    if not _SKILL_RESOURCE_RE.search(file_path):
        return False
    p = Path(file_path)
    if p.parent.name != "resources":
        return False
    return bool(_INSTRUCTION_BASENAME_RE.fullmatch(p.name))


def handle_read_hygiene(data: dict[str, Any]) -> dict[str, Any] | None:
    """Process a PreToolUse:Read event and strip extra params if needed.

    Returns the hookSpecificOutput dict to print, or None if no fix needed.
    """
    if data.get("hook_event_name") != "PreToolUse":
        return None
    if data.get("tool_name") != "Read":
        return None

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return None

    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str):
        return None

    if not _is_skill_instruction_file(file_path):
        return None

    extra_keys = set(tool_input.keys()) & _EXTRA_READ_PARAMS
    if not extra_keys:
        return None

    logger.debug("read-hygiene: stripped %s from %s", sorted(extra_keys), Path(file_path).name)

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {
                "file_path": file_path,
            },
        }
    }
