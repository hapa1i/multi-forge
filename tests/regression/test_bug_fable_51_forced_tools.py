"""Regression: explicit Fable 5.1 pins must refuse forced tool choice before dispatch.

Bug: the `claude-fable-5-1` catalog entry omitted `supports_forced_tool_choice: false`, although the 5.1 migration
contract accepts only `auto` or `none`. Translated routes therefore forwarded `any`/named choices: OpenRouter returned
an upstream 400, and LiteLLM's `drop_params` quietly downgraded the forced call to `auto`.

Fix: the catalog declares the restriction, so the shared translated converter refuses it locally.

Affected: src/forge/core/data/model_catalog.yaml
"""

from __future__ import annotations

import pytest

from forge.proxy.converters import RequestConversionError, convert_anthropic_to_openai
from forge.proxy.data_models import MessagesRequest

# Successful conversion schedules async tool-event logging, so these run inside an event loop.
pytestmark = [pytest.mark.regression, pytest.mark.asyncio]

# OpenRouter and LiteLLM spell the same backend model with different version punctuation.
FABLE_51_ROUTES = ["anthropic/claude-fable-5.1", "anthropic/claude-fable-5-1"]


def _request(choice: dict) -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": "claude-fable-5-1",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Ping"}],
            "tools": [{"name": "ping", "input_schema": {"type": "object", "properties": {}}}],
            "tool_choice": choice,
        }
    )


@pytest.mark.parametrize("resolved_model", FABLE_51_ROUTES)
@pytest.mark.parametrize("choice", [{"type": "any"}, {"type": "tool", "name": "ping"}])
async def test_fable_51_forced_tool_choice_refuses_locally(resolved_model: str, choice: dict) -> None:
    with pytest.raises(RequestConversionError, match="does not support forced tool_choice"):
        convert_anthropic_to_openai(_request(choice), provider="openrouter", resolved_model=resolved_model)


@pytest.mark.parametrize("resolved_model", FABLE_51_ROUTES)
@pytest.mark.parametrize(("choice", "expected"), [({"type": "auto"}, "auto"), ({"type": "none"}, "none")])
async def test_fable_51_supported_tool_choices_still_translate(
    resolved_model: str, choice: dict, expected: str
) -> None:
    converted = convert_anthropic_to_openai(_request(choice), provider="openrouter", resolved_model=resolved_model)

    assert converted["tool_choice"] == expected
