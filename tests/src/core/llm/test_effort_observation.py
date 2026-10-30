"""Effort callbacks describe the serialized provider request before dispatch."""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI
from tenacity import wait_none

from forge.core.effort_observation import AppliedEffort
from forge.core.llm.clients.litellm import LiteLLMClient
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import Message, ModelHyperparameters

TOOLS = [
    {
        "type": "function",
        "function": {"name": "report", "parameters": {"type": "object"}},
    }
]
MESSAGES = [Message(role="user", content="Describe effort")]
DROP = AppliedEffort(
    applied=None,
    wire="dropped",
    note="GPT-5 Chat Completions drops reasoning_effort when function tools are present.",
)


@dataclass(frozen=True)
class EffortCase:
    model: str = "provider/chat-fixture"
    openrouter: bool = False
    defaults: ModelHyperparameters | None = None
    params: ModelHyperparameters | None = None
    tools: bool = False
    observation: AppliedEffort = AppliedEffort(None, None)
    body: dict[str, Any] = field(default_factory=dict)


def _response(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
    if request.url.path.endswith("/responses"):
        return httpx.Response(
            200,
            json={
                "id": "resp-fixture",
                "object": "response",
                "status": "completed",
                "model": body["model"],
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok", "annotations": []}],
                    }
                ],
            },
        )
    common = {"id": "chat-fixture", "model": body["model"], "created": 0}
    if body.get("stream"):
        chunk = {
            **common,
            "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}],
        }
        return httpx.Response(
            200,
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )
    return httpx.Response(
        200,
        json={
            **common,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["complete", "stream"])
@pytest.mark.parametrize(
    "case",
    [
        pytest.param(EffortCase(), id="chat-absent"),
        pytest.param(
            EffortCase(
                defaults=ModelHyperparameters(reasoning_effort="high"),
                params=ModelHyperparameters(max_tokens=64),
                observation=AppliedEffort("high", "reasoning_effort"),
                body={"reasoning_effort": "high"},
            ),
            id="chat-configured-default",
        ),
        pytest.param(
            EffortCase(
                params=ModelHyperparameters(
                    reasoning_effort="high",
                    extra={"openai": {"extra_body": {"reasoning_effort": "low"}}},
                ),
                observation=AppliedEffort("low", "reasoning_effort"),
                body={"reasoning_effort": "low"},
            ),
            id="chat-extra-body-wins",
        ),
        pytest.param(
            EffortCase(model="openai/gpt-5-fixture", tools=True),
            id="gpt-tools-no-effort",
        ),
        pytest.param(
            EffortCase(
                model="openai/gpt-5-fixture",
                params=ModelHyperparameters(
                    reasoning_effort="high",
                    extra={"openai": {"reasoning_effort": "low"}},
                ),
                tools=True,
                observation=DROP,
            ),
            id="gpt-tools-drop",
        ),
        pytest.param(
            EffortCase(
                model="openai/gpt-5-fixture",
                params=ModelHyperparameters(
                    reasoning_effort="high",
                    extra={"openai": {"extra_body": {"reasoning_effort": "low"}}},
                ),
                tools=True,
                observation=AppliedEffort("low", "reasoning_effort"),
                body={"reasoning_effort": "low"},
            ),
            id="gpt-tools-existing-extra-body-behavior",
        ),
        pytest.param(
            EffortCase(
                model="gemini/gemini-4-argon",
                observation=AppliedEffort("medium", "thinkingConfig.thinkingLevel"),
                body={
                    "thinkingConfig": {
                        "thinkingLevel": "medium",
                        "includeThoughts": True,
                    }
                },
            ),
            id="argon-catalog-default",
        ),
        pytest.param(
            EffortCase(
                model="vertex_ai/gemini-4-argon",
                params=ModelHyperparameters(
                    reasoning_effort="high",
                    extra={"openai": {"extra_body": {"reasoning_effort": "low"}}},
                ),
                observation=AppliedEffort("low", "thinkingConfig.thinkingLevel"),
                body={"thinkingConfig": {"thinkingLevel": "low", "includeThoughts": True}},
            ),
            id="argon-translated-override",
        ),
        pytest.param(EffortCase(openrouter=True), id="openrouter-absent"),
        pytest.param(
            EffortCase(
                openrouter=True,
                defaults=ModelHyperparameters(reasoning_effort="high"),
                params=ModelHyperparameters(extra={"openai": {"extra_body": {"reasoning": {"effort": "low"}}}}),
                observation=AppliedEffort("high", "reasoning.effort"),
                body={"reasoning": {"effort": "high"}},
            ),
            id="openrouter-existing-translation-precedence",
        ),
        pytest.param(
            EffortCase(
                openrouter=True,
                params=ModelHyperparameters(extra={"openai": {"extra_body": {"reasoning": {"effort": "low"}}}}),
                observation=AppliedEffort("low", "reasoning.effort"),
                body={"reasoning": {"effort": "low"}},
            ),
            id="openrouter-extra-body-effort",
        ),
        pytest.param(EffortCase(model="openai/gpt-6-astra"), id="responses-absent"),
        pytest.param(
            EffortCase(
                model="openai/gpt-6-astra",
                defaults=ModelHyperparameters(reasoning_effort="high"),
                params=ModelHyperparameters(extra={"openai": {"extra_body": {"reasoning": {"effort": "low"}}}}),
                tools=True,
                observation=AppliedEffort("high", "reasoning.effort"),
                body={"reasoning": {"effort": "high"}},
            ),
            id="responses-configured-default-preserves-ignored-extras",
        ),
    ],
)
async def test_effort_matches_final_sdk_body(case: EffortCase, stream: bool) -> None:
    observations: list[AppliedEffort] = []
    order: list[str] = []
    bodies: list[dict[str, Any]] = []
    before = case.params.model_dump() if case.params is not None else None

    def observe(value: AppliedEffort) -> None:
        order.append("effort")
        observations.append(value)

    def serve(request: httpx.Request) -> httpx.Response:
        order.append("io")
        assert observations == [case.observation]
        body = json.loads(request.content)
        bodies.append(body)
        return _response(request, body)

    async with AsyncOpenAI(
        api_key="fixture-key",
        base_url="http://effort.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(serve)),
    ) as sdk:
        client = (
            OpenRouterClient(case.model, "openrouter", default_hyperparams=case.defaults)
            if case.openrouter
            else LiteLLMClient(case.model, "litellm_remote", default_hyperparams=case.defaults)
        )
        client._client = sdk
        kwargs: dict[str, Any] = {
            "tools": TOOLS if case.tools else None,
            "hyperparams": case.params,
            "on_effort_applied": observe,
            "on_provider_dispatch": lambda: order.append("dispatch"),
        }
        if stream:
            events = [event async for event in client.stream(MESSAGES, **kwargs)]
            assert not [event for event in events if event.type == "error"]
            assert "".join(event.text or "" for event in events) == "ok"
        else:
            assert (await client.complete(MESSAGES, **kwargs)).text == "ok"

    assert order == ["dispatch", "effort", "io"]
    assert len(bodies) == 1
    body = bodies[0]
    assert {key: body[key] for key in ("reasoning_effort", "reasoning", "thinkingConfig") if key in body} == case.body
    assert "on_effort_applied" not in body
    assert "on_provider_dispatch" not in body
    assert (case.params.model_dump() if case.params is not None else None) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["chat", "responses", "openrouter"])
async def test_completion_retries_observe_each_outbound_attempt(path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    client = (
        OpenRouterClient("provider/chat-fixture", "openrouter")
        if path == "openrouter"
        else LiteLLMClient(
            "openai/gpt-6-astra" if path == "responses" else "provider/chat-fixture",
            "litellm_remote",
        )
    )
    monkeypatch.setattr(getattr(client._make_completion_request, "retry"), "wait", wait_none())
    observations: list[AppliedEffort] = []
    bodies: list[dict[str, Any]] = []

    def serve(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        assert len(observations) == len(bodies)
        if len(bodies) == 1:
            return httpx.Response(
                503,
                json={"error": {"message": "fixture retry", "type": "server_error"}},
            )
        return _response(request, body)

    async with AsyncOpenAI(
        api_key="fixture-key",
        base_url="http://effort.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(serve)),
    ) as sdk:
        client._client = sdk
        response = await client.complete(
            MESSAGES,
            hyperparams=ModelHyperparameters(reasoning_effort="high"),
            on_effort_applied=observations.append,
        )

    assert response.text == "ok"
    assert bodies[0] == bodies[1]
    assert observations == [AppliedEffort("high", "reasoning_effort" if path == "chat" else "reasoning.effort")] * 2
