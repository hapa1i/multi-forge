"""Regression: Claude Code mid-conversation system messages must not 422.

Claude Code 2.1.161 can send ``{"role": "system"}`` entries inside
``messages``. The translated proxy route binds ``MessagesRequest`` before
conversion, so rejecting that role produces a local 422 before OpenRouter or
LiteLLM sees the request.
"""

from typing import Any

import pytest

from forge.proxy.converters import convert_anthropic_to_openai
from forge.proxy.data_models import MessagesRequest

pytestmark = pytest.mark.regression


RAW_BODY: dict[str, Any] = {
    "model": "claude-opus-4-8-20260601",
    "max_tokens": 1024,
    "messages": [
        {"role": "user", "content": "hello we are going to test forking"},
        {"role": "system", "content": "Continue with the QA runtime context."},
        {"role": "user", "content": "please continue"},
    ],
}


def test_system_role_message_validates() -> None:
    req = MessagesRequest(**RAW_BODY)

    assert req.messages[1].role == "system"
    assert req.messages[1].content == "Continue with the QA runtime context."


def test_system_role_message_preserved_for_openrouter() -> None:
    req = MessagesRequest(**RAW_BODY)
    result = convert_anthropic_to_openai(req, provider="openrouter")

    assert result["messages"][1] == {
        "role": "system",
        "content": "Continue with the QA runtime context.",
    }
