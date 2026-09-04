"""Hermetic OpenAI-family proxy routing integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.integration.proxy.conftest import FakeOpenAIUpstream

pytestmark = pytest.mark.integration


def _read_tool_event_records(forge_home: Path) -> list[dict]:
    event_files = list((forge_home / "logs" / "tool_events").glob("*_proxy.*.jsonl"))
    if not event_files:
        return []
    assert len(event_files) == 1
    return [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines()]


def test_litellm_openai_sonnet_forwards_exact_astra_model(
    proxy_server_fake_litellm_openai: tuple[str, FakeOpenAIUpstream],
) -> None:
    """The bundled remote LiteLLM template forwards sonnet to the exact Astra slug."""
    proxy_base_url, fake_upstream = proxy_server_fake_litellm_openai
    inbound_user_agent = "claude-code/integration-" + "x" * 300

    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{proxy_base_url}/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Say hello"}],
            },
            headers={"x-api-key": "test", "user-agent": inbound_user_agent},
        )

    assert response.status_code == 200, response.text[:500]
    assert response.headers.get("X-Resolved-Tier") == "sonnet"
    assert response.headers.get("X-Resolved-Model") == "openai/gpt-6-astra"
    assert response.json()["content"][0]["text"] == "FAKE-SOL-OK"

    assert len(fake_upstream.requests) == 1
    upstream_request = fake_upstream.requests[0]
    assert upstream_request["path"] == "/v1/responses"
    assert upstream_request["body"]["input"] == [{"role": "user", "content": "Say hello"}]
    assert upstream_request["body"]["max_output_tokens"] == 16
    assert upstream_request["body"]["model"] == "openai/gpt-6-astra"
    assert upstream_request["body"]["reasoning"] == {"effort": "medium"}
    assert "temperature" not in upstream_request["body"]
    assert "top_p" not in upstream_request["body"]
    assert upstream_request["body"]["text"] == {"verbosity": "high"}
    assert upstream_request["headers"]["User-Agent"] == inbound_user_agent[:256]


def test_anthropic_any_reaches_responses_api_as_required(
    proxy_server_fake_litellm_openai: tuple[str, FakeOpenAIUpstream],
) -> None:
    """Required tool use survives both proxy translation seams."""
    proxy_base_url, fake_upstream = proxy_server_fake_litellm_openai
    fake_upstream.requests.clear()

    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{proxy_base_url}/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Read the file"}],
                "tools": [
                    {
                        "name": "Read",
                        "description": "Read a file",
                        "input_schema": {
                            "type": "object",
                            "properties": {"file_path": {"type": "string"}},
                            "required": ["file_path"],
                        },
                    }
                ],
                "tool_choice": {"type": "any"},
            },
            headers={"x-api-key": "test"},
        )

    assert response.status_code == 200, response.text[:500]
    assert len(fake_upstream.requests) == 1
    upstream_request = fake_upstream.requests[0]
    assert upstream_request["path"] == "/v1/responses"
    assert upstream_request["body"]["tool_choice"] == "required"
    assert upstream_request["body"]["tools"][0]["name"] == "Read"


def test_translated_converter_logs_keep_payload_canaries_out(
    proxy_server_fake_litellm_openai: tuple[str, FakeOpenAIUpstream],
    module_forge_home: Path,
) -> None:
    """The subprocess route preserves payloads upstream but writes metadata-only converter logs."""
    proxy_base_url, fake_upstream = proxy_server_fake_litellm_openai
    canaries = {
        "system": "O037_E2E_SYSTEM_CANARY",
        "message": "O037_E2E_MESSAGE_CANARY",
        "description": "O037_E2E_DESCRIPTION_CANARY",
        "schema": "O037_E2E_SCHEMA_CANARY",
        "stop": "O037_E2E_STOP_CANARY",
    }
    fake_upstream.requests.clear()
    prior_tool_event_count = len(_read_tool_event_records(module_forge_home))

    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{proxy_base_url}/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 16,
                "system": canaries["system"],
                "messages": [{"role": "user", "content": canaries["message"]}],
                "stop_sequences": [canaries["stop"]],
                "tools": [
                    {
                        "name": "CustomTool",
                        "description": canaries["description"],
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "value": {"type": "string", "description": canaries["schema"]},
                            },
                            "required": ["value"],
                        },
                    }
                ],
            },
            headers={"x-api-key": "test"},
        )

    assert response.status_code == 200, response.text[:500]
    assert len(fake_upstream.requests) == 1
    upstream_body = json.dumps(fake_upstream.requests[0]["body"])
    for field in ("system", "message", "description", "schema"):
        assert canaries[field] in upstream_body

    log_files = list((module_forge_home / "logs" / "proxy").glob("proxy.*.log"))
    assert len(log_files) == 1
    converter_log = log_files[0].read_text(encoding="utf-8")
    assert "Tool schema received:" in converter_log
    assert "Intermediate OpenAI request prepared:" in converter_log
    tool_events = _read_tool_event_records(module_forge_home)[prior_tool_event_count:]
    schema_events = [event for event in tool_events if event["metadata"]["event"] == "schema_observed"]
    assert len(schema_events) == 1
    assert schema_events[0]["metadata"] == {
        "event": "schema_observed",
        "schema_field_count": 3,
        "schema_property_count": 1,
        "schema_required_count": 1,
    }
    assert "details" not in schema_events[0]
    tool_event_text = json.dumps(tool_events)
    for canary in canaries.values():
        assert canary not in converter_log
        assert canary not in tool_event_text


def test_translated_tool_failure_diagnostics_keep_payload_canaries_out(
    proxy_server_fake_litellm_openai: tuple[str, FakeOpenAIUpstream],
    module_forge_home: Path,
) -> None:
    """A failed tool result stays on the wire but reaches diagnostics as shape metadata only."""
    proxy_base_url, fake_upstream = proxy_server_fake_litellm_openai
    input_canary = "D035_E2E_TOOL_INPUT_CANARY"
    result_canary = "Error: D035_E2E_TOOL_RESULT_CANARY"
    fake_upstream.requests.clear()

    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{proxy_base_url}/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 16,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "toolu_d035_e2e",
                                "name": "CustomTool",
                                "input": {"value": input_canary},
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_d035_e2e",
                                "content": result_canary,
                                "is_error": True,
                            }
                        ],
                    },
                ],
            },
            headers={"x-api-key": "test"},
        )

    assert response.status_code == 200, response.text[:500]
    assert len(fake_upstream.requests) == 1
    upstream_body = json.dumps(fake_upstream.requests[0]["body"])
    assert input_canary in upstream_body
    assert result_canary in upstream_body

    log_files = list((module_forge_home / "logs" / "proxy").glob("proxy.*.log"))
    assert len(log_files) == 1
    converter_log = log_files[0].read_text(encoding="utf-8")
    tool_events = _read_tool_event_records(module_forge_home)
    failure_events = [
        event
        for event in tool_events
        if event["metadata"]["event"] == "client_tool_failure" and event["metadata"].get("tool_id") == "toolu_d035_e2e"
    ]
    assert len(failure_events) == 1
    assert failure_events[0]["metadata"] == {
        "event": "client_tool_failure",
        "tool_id": "toolu_d035_e2e",
        "content_type": "str",
        "content_length": len(result_canary),
        "tool_name_found": True,
    }
    assert "details" not in failure_events[0]
    tool_event_text = json.dumps(tool_events)
    for canary in (input_canary, result_canary):
        assert canary not in converter_log
        assert canary not in tool_event_text
