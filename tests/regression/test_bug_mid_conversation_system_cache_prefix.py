"""Regression: Claude Code's mid-conversation system messages defeated OpenRouter prompt caching.

Claude Code 2.1.294+ sends its environment block and a per-turn reminder as ``role: system``
messages inside ``messages``. Forge forwarded them as OpenAI system messages, and OpenRouter
hoists those into the provider system prompt (Gemini, Anthropic, some Kimi hosts). The prompt
start then changed every turn, so nothing after it could be reused: Gemini 4 Argon cached 11.4%
of input over 2026-10-13..15. A paid probe on 2026-10-15 showed user-role reminders restore
reuse (Argon 0% -> 78% by turn 8, Claude Haiku 64% -> 91%, Kimi K3 65% -> 91%).
"""

import pytest

from forge.proxy.converters import convert_anthropic_to_openai
from tests.fixtures.claude_code_requests import claude_code_tool_loop

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "backend",
    ["google/gemini-4-argon", "anthropic/claude-opus-5.5", "moonshotai/kimi-k3", "openai/gpt-6-astra"],
)
def test_no_system_message_after_conversation_starts(backend: str) -> None:
    request = claude_code_tool_loop("claude-opus-5-5", completed_tool_turns=3)
    result = convert_anthropic_to_openai(request, provider="openrouter", resolved_model=backend)

    roles = [m["role"] for m in result["messages"]]
    assert roles[0] == "system"
    assert "system" not in roles[1:]


def test_marker_free_backend_sees_append_only_messages() -> None:
    # Implicit prefix caches need each turn's request to extend the previous one exactly.
    turns = [
        convert_anthropic_to_openai(
            claude_code_tool_loop("claude-opus-5-5", completed_tool_turns=k),
            provider="openrouter",
            resolved_model="google/gemini-4-argon",
        )["messages"]
        for k in range(4)
    ]
    for earlier, later in zip(turns, turns[1:]):
        assert later[: len(earlier)] == earlier
