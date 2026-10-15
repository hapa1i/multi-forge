"""Claude Code request shapes for translated-proxy tests.

Mirrors Claude Code 2.1.294/2.1.296 tool loops captured against a local fake upstream on
2026-10-15 (headless and interactive). The environment block and a per-turn reminder
arrive as mid-conversation ``role: system`` messages; the rolling cache marker sits on
the trailing one and drops off once that message becomes history.
"""

from __future__ import annotations

from typing import Any

from forge.proxy.data_models import MessagesRequest

MARKER: dict[str, str] = {"type": "ephemeral"}
ENVIRONMENT = "# Environment\nYou have been invoked in the following environment:\n - Primary working directory: /tmp/w"


def _reminder(turn: int) -> str:
    return f"<total_tokens>{999_000 - turn * 1234} tokens left</total_tokens>"


def claude_code_tool_loop(model: str, *, completed_tool_turns: int) -> MessagesRequest:
    """Build request k+1 of a Claude Code tool loop after ``completed_tool_turns`` tool calls."""
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "<system-reminder>\nAttribution guidance.\n</system-reminder>"},
                {"type": "text", "text": "Read the notes and summarize them."},
            ],
        }
    ]
    last = completed_tool_turns == 0
    messages.append(_system(ENVIRONMENT, marked=last))
    for turn in range(1, completed_tool_turns + 1):
        tool_id = f"toolu_{turn}"
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": tool_id, "name": "Read", "input": {"file_path": f"n{turn}.txt"}}
                ],
            }
        )
        messages.append(
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": f"note {turn}"}]}
        )
        messages.append(_system(_reminder(turn), marked=turn == completed_tool_turns))
    return MessagesRequest.model_validate(
        {
            "model": model,
            "max_tokens": 64,
            "system": [
                {"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1.296"},
                {"type": "text", "text": "You are a Claude agent.", "cache_control": MARKER},
                {"type": "text", "text": "Main system prompt.", "cache_control": MARKER},
            ],
            "messages": messages,
        }
    )


def _system(text: str, *, marked: bool) -> dict[str, Any]:
    if marked:
        return {"role": "system", "content": [{"type": "text", "text": text, "cache_control": MARKER}]}
    return {"role": "system", "content": text}


def message_markers(openai_request: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every cache_control marker in a converted OpenAI-format request, in order."""
    markers: list[dict[str, Any]] = []
    for message in openai_request["messages"]:
        content = message.get("content")
        if isinstance(content, list):
            markers.extend(
                part["cache_control"] for part in content if isinstance(part, dict) and "cache_control" in part
            )
    return markers
