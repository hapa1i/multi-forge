"""Bounded live tool round trips for the October OpenRouter alternatives."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.integration.proxy.conftest import _openrouter_family_proxy

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_MODELS = [
    ("kimi", "kimi-k3.1-pro", "moonshotai/kimi-k3.1-pro"),
    ("minimax", "minimax-m3.1-flash", "minimax/minimax-m3.1-flash"),
    ("deepseek", "deepseek-v4.1-flash-1017", "deepseek/deepseek-v4.1-flash-1017"),
]


@pytest.fixture(scope="module", params=_MODELS, ids=[model for _, model, _ in _MODELS])
def october_proxy(
    request: pytest.FixtureRequest, module_forge_home: Path, tmp_path_factory: pytest.TempPathFactory
) -> Generator[tuple[str, str, str], None, None]:
    family, model, slug = request.param
    for base_url in _openrouter_family_proxy(
        f"openrouter-{family}",
        module_forge_home,
        tmp_path_factory,
        "October model proxy unreachable",
        preflight=False,
    ):
        yield base_url, model, slug


def _message(response: httpx.Response, stream: bool) -> dict[str, Any]:
    assert response.status_code == 200, response.text[:500]
    if not stream:
        return response.json()
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert not [event for event in events if event["type"] == "error"]
    assert events[0]["type"] == "message_start"
    assert events[-1]["type"] == "message_stop"
    message = events[0]["message"]
    blocks: dict[int, dict[str, Any]] = {}
    arguments: dict[int, str] = {}
    for event in events:
        if event["type"] == "content_block_start":
            blocks[event["index"]] = event["content_block"]
        elif event["type"] == "content_block_delta":
            index, delta = event["index"], event["delta"]
            if delta["type"] == "text_delta":
                blocks[index]["text"] += delta["text"]
            elif delta["type"] == "input_json_delta":
                arguments[index] = arguments.get(index, "") + delta["partial_json"]
        elif event["type"] == "message_delta":
            message.update(event["delta"])
            message["usage"].update(event.get("usage", {}))
    for index, value in arguments.items():
        blocks[index]["input"] = json.loads(value)
    message["content"] = [blocks[index] for index in sorted(blocks)]
    return message


@pytest.mark.parametrize("stream", [False, True])
def test_model_tool_call_and_continuation(october_proxy: tuple[str, str, str], stream: bool) -> None:
    base_url, model, slug = october_proxy
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Call get_value with key sample. After receiving it, reply with that value only."}
    ]
    body = {
        "model": model,
        "max_tokens": 2048,
        "stream": stream,
        "reasoning_effort": "low",
        "temperature": 0.7,
        "top_p": 0.9,
        "messages": messages,
        "tools": [
            {
                "name": "get_value",
                "description": "Return the requested value.",
                "input_schema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
            }
        ],
        "tool_choice": {"type": "auto"},
    }
    with httpx.Client(timeout=180) as client:
        health = client.get(f"{base_url}/").json()
        assert health["runtime"]["data_policy"]["zdr"] == "required"
        assert health["runtime"]["model_alternatives"]["sonnet"][model] == slug
        response = client.post(f"{base_url}/v1/messages", json=body, headers={"x-api-key": "test"})
        assert response.headers.get("X-Resolved-Model") == slug
        first = _message(response, stream)
        assert first["stop_reason"] == "tool_use"
        tool_calls = [block for block in first["content"] if block["type"] == "tool_use"]
        assert len(tool_calls) == 1
        tool = tool_calls[0]
        assert tool["name"] == "get_value"
        assert tool["input"] == {"key": "sample"}
        assert first["usage"]["input_tokens"] > 0
        assert first["usage"]["output_tokens"] > 0

        messages.extend(
            [
                {"role": "assistant", "content": first["content"]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool["id"], "content": "42"}]},
            ]
        )
        response = client.post(
            f"{base_url}/v1/messages", json={**body, "max_tokens": 512}, headers={"x-api-key": "test"}
        )
        assert response.headers.get("X-Resolved-Model") == slug
        final = _message(response, stream)
        assert final["stop_reason"] == "end_turn"
        assert any(block["type"] == "text" and block["text"].strip() for block in final["content"])
        assert final["usage"]["output_tokens"] > 0
