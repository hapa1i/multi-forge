"""Regression: cache markers followed the client's model name instead of the backend.

``_model_supports_cache_control(request.model)`` saw Claude Code's ``claude-opus-5-5`` on every
plain ``--proxy`` launch, so markers reached Gemini and every other backend, while ``--model``
launches sent the backend's own name and stripped them. On OpenRouter's Gemini route the
forwarded markers never wrote a cache (Argon) or doubled reported prompt tokens (Flash). The
resolved backend's catalog mechanism now decides.
"""

import pytest

from forge.proxy.converters import convert_anthropic_to_openai
from tests.fixtures.claude_code_requests import claude_code_tool_loop, message_markers

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    ("client_model", "backend", "forwarded"),
    [
        ("claude-opus-5-5", "google/gemini-4-argon", False),  # plain --proxy launch on openrouter-gemini
        ("claude-opus-5-5", "moonshotai/kimi-k3", False),
        ("claude-opus-5-5", "openai/gpt-6-astra", False),
        ("anthropic/claude-opus-5.5", "anthropic/claude-opus-5.5", True),  # model-first Claude launch
        ("claude-opus-5-5", "anthropic/claude-unlisted-test", True),  # unknown Claude: name fallback
        ("claude-opus-5-5", "acme/unlisted-test", False),
    ],
)
def test_markers_follow_resolved_backend(client_model: str, backend: str, forwarded: bool) -> None:
    request = claude_code_tool_loop(client_model, completed_tool_turns=1)
    result = convert_anthropic_to_openai(request, provider="openrouter", resolved_model=backend)

    assert bool(message_markers(result)) is forwarded
