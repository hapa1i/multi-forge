"""Responses must enforce catalog sampling capabilities before provider dispatch."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.core.llm.clients.litellm import LiteLLMClient
from forge.core.llm.types import CompletionResponse, Message, ModelHyperparameters

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


@pytest.mark.parametrize("temperature", [0.7, 1.0])
@pytest.mark.parametrize("stream", [False, True])
async def test_astra_omits_client_sampling_parameters(temperature: float, stream: bool) -> None:
    client = LiteLLMClient(model="openai/gpt-6-astra", provider="litellm_remote")
    sdk_client = MagicMock()
    create = AsyncMock(return_value=MagicMock())
    sdk_client.responses.with_raw_response.create = create
    messages = [Message(role="user", content="Say hello")]
    params = ModelHyperparameters(temperature=temperature, top_p=0.8, reasoning_effort="medium")

    with (
        patch.object(client, "_get_client", new=AsyncMock(return_value=sdk_client)),
        patch.object(client, "_parse_responses_output", return_value=CompletionResponse(text="hello")),
        patch.object(client, "_merge_response_metadata", side_effect=lambda completion, _headers: completion),
    ):
        if stream:
            events = [event async for event in client.stream(messages, hyperparams=params)]
            assert events[0].text == "hello"
        else:
            response = await client.complete(messages, hyperparams=params)
            assert response.text == "hello"

    create.assert_awaited_once()
    assert create.await_args is not None
    request = create.await_args.kwargs
    assert request["model"] == "openai/gpt-6-astra"
    assert request["reasoning"] == {"effort": "medium"}
    assert "temperature" not in request
    assert "top_p" not in request
