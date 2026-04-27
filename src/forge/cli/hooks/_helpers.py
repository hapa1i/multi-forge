"""Shared I/O helpers used across hook command modules."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from forge.session.hooks import HookResult
from forge.session.models import SessionState


def _find_latest_plan_from_transcript(transcript_path: str, cwd: Path) -> Path | None:
    """Streaming scan for last plan file write.

    This is a fallback only; it avoids loading the entire transcript into memory.
    """

    path = Path(transcript_path)
    if not path.is_file():
        return None

    latest: Path | None = None
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") != "assistant":
                    continue

                message = entry.get("message")
                if not isinstance(message, dict):
                    continue

                content = message.get("content")
                if not isinstance(content, list):
                    continue

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    if block.get("name") != "Write":
                        continue

                    tool_input = block.get("input")
                    if not isinstance(tool_input, dict):
                        continue

                    fp = tool_input.get("file_path")
                    if not isinstance(fp, str) or not fp:
                        continue

                    if "/.claude/plans/" not in fp and not fp.startswith(".claude/plans/"):
                        continue

                    candidate = Path(fp)
                    if candidate.is_absolute():
                        try:
                            candidate = candidate.resolve().relative_to(cwd)
                        except Exception:
                            pass

                    latest = cwd / candidate
    except Exception:
        return latest

    return latest


def _output_json(data: dict[str, Any]) -> None:
    """Output hook result as JSON to stdout.

    For non-SessionStart hooks, we return a small JSON payload for debugging,
    but avoid any UI-facing `systemMessage`.
    """
    click.echo(json.dumps(data, indent=2))


def _output_result(result: HookResult) -> None:
    """Output SessionStart hook result as JSON to stdout."""
    _output_json(result.to_dict())


def _read_stdin_json() -> tuple[dict[str, Any] | None, str | None]:
    """Read hook JSON payload from stdin.

    Returns:
        (parsed_dict, error)

        - If input is empty/whitespace: (None, "empty")
        - If JSON is invalid or not an object: (None, "invalid_json")
        - If valid: (dict, None)
    """

    stdin_data = sys.stdin.read()
    if not stdin_data.strip():
        return None, "empty"

    try:
        parsed = json.loads(stdin_data)
    except Exception:
        return None, "invalid_json"

    if not isinstance(parsed, dict):
        return None, "invalid_json"

    return parsed, None


def _print_session_tip(manifest: SessionState) -> None:
    """No-op: SessionEnd hook output is suppressed by Claude Code.

    See anthropics/claude-code#9090. The reconnect tip is printed from
    the parent launcher process instead (_print_post_exit_tip in session.py).
    Kept as a stub so the session-end hook doesn't break if called.
    """


def _append_artifact_entry(
    confirmed_artifacts: dict[str, Any],
    *,
    kind: str,
    entry: dict[str, Any],
) -> None:
    """Append an artifact record under confirmed.artifacts in a stable shape."""

    items = confirmed_artifacts.get(kind)
    if items is None:
        confirmed_artifacts[kind] = [entry]
        return

    if not isinstance(items, list):
        # If the field was corrupted or mis-typed, clobber to a list.
        confirmed_artifacts[kind] = [entry]
        return

    items.append(entry)
