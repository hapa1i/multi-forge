"""Bounded Neon and Hydrogen tool round trips through the default Gemini tiers."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.integration.proxy.conftest import _openrouter_family_proxy

pytestmark = [pytest.mark.integration, pytest.mark.slow]


NEON = "google/gemini-4-neon"
HYDROGEN = "google/gemini-4-hydrogen"
# Claude tier names reach each default the way Claude Code does; Hydrogen is served at Haiku only.
DEFAULT_TIER_REQUESTS = [("claude-sonnet-5-5", NEON), ("claude-haiku-4-5", HYDROGEN)]
TOOL = {
    "name": "get_value",
    "description": "Return the requested value.",
    "input_schema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
}


@pytest.fixture(scope="module")
def gemini_proxy(module_forge_home: Path, tmp_path_factory: pytest.TempPathFactory) -> Generator[str, None, None]:
    yield from _openrouter_family_proxy(
        "openrouter-gemini",
        module_forge_home,
        tmp_path_factory,
        "Gemini proxy unreachable",
        preflight=False,
    )


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
@pytest.mark.parametrize(("model", "slug"), DEFAULT_TIER_REQUESTS)
def test_default_tier_tool_call_and_continuation(gemini_proxy: str, stream: bool, model: str, slug: str) -> None:
    base_url = gemini_proxy
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
        "tools": [TOOL],
        "tool_choice": {"type": "auto"},
    }
    with httpx.Client(timeout=180) as client:
        health = client.get(f"{base_url}/").json()
        assert health["runtime"]["data_policy"]["zdr"] == "required"
        assert health["runtime"]["tier_mappings"] == {"haiku": HYDROGEN, "sonnet": NEON, "opus": NEON}
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


@pytest.mark.parametrize(("model", "slug"), DEFAULT_TIER_REQUESTS)
def test_xhigh_is_accepted_under_required_zdr(gemini_proxy: str, model: str, slug: str) -> None:
    body = {
        "model": model,
        "max_tokens": 4096,
        "reasoning_effort": "xhigh",
        "messages": [{"role": "user", "content": "Reply with OK."}],
    }
    with httpx.Client(timeout=180) as client:
        response = client.post(f"{gemini_proxy}/v1/messages", json=body, headers={"x-api-key": "test"})

    assert response.headers.get("X-Resolved-Model") == slug
    message = _message(response, stream=False)
    # Thinking shares the output budget, so the deepest level may exhaust it before answering.
    assert message["stop_reason"] in {"end_turn", "max_tokens"}
    assert message["usage"]["output_tokens"] > 0


@pytest.mark.parametrize(("model", "slug"), DEFAULT_TIER_REQUESTS)
def test_openrouter_continues_a_tool_call_from_another_model(gemini_proxy: str, model: str, slug: str) -> None:
    _assert_foreign_tool_call_continues(gemini_proxy, model, slug)


@pytest.mark.parametrize(("model", "slug"), DEFAULT_TIER_REQUESTS)
def test_google_ai_continues_a_tool_call_from_another_model(proxy_server: str, model: str, slug: str) -> None:
    # The local LiteLLM route addresses the same models with the gemini/ prefix.
    _assert_foreign_tool_call_continues(proxy_server, model, slug.replace("google/", "gemini/"))


def _assert_foreign_tool_call_continues(base_url: str, model: str, resolved: str) -> None:
    # Claude made this call before the session switched models, so it carries no Gemini thought signature.
    body = {
        "model": model,
        "max_tokens": 512,
        "reasoning_effort": "low",
        "messages": [
            {
                "role": "user",
                "content": "Call get_value with key sample. After receiving it, reply with that value only.",
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_01ForeignModelCall",
                        "name": "get_value",
                        "input": {"key": "sample"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_01ForeignModelCall", "content": "42"}],
            },
        ],
        "tools": [TOOL],
    }
    with httpx.Client(timeout=180) as client:
        response = client.post(f"{base_url}/v1/messages", json=body, headers={"x-api-key": "test"})

    message = _message(response, stream=False)
    assert response.headers.get("X-Resolved-Model") == resolved
    assert message["stop_reason"] == "end_turn"
    assert "42" in "".join(block["text"] for block in message["content"] if block["type"] == "text")
