"""Hermetic OpenAI-family proxy routing integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.integration.proxy.conftest import FakeOpenAIUpstream

pytestmark = pytest.mark.integration


def test_litellm_openai_sonnet_forwards_exact_sol_model(
    proxy_server_fake_litellm_openai: tuple[str, FakeOpenAIUpstream],
) -> None:
    """The bundled remote LiteLLM template forwards sonnet to the exact Sol slug."""
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
    assert response.headers.get("X-Resolved-Model") == "openai/gpt-5.6-sol"
    assert response.json()["content"][0]["text"] == "FAKE-SOL-OK"

    assert len(fake_upstream.requests) == 1
    upstream_request = fake_upstream.requests[0]
    assert upstream_request["path"] == "/v1/responses"
    assert upstream_request["body"]["input"] == [{"role": "user", "content": "Say hello"}]
    assert upstream_request["body"]["max_output_tokens"] == 16
    assert upstream_request["body"]["model"] == "openai/gpt-5.6-sol"
    assert upstream_request["body"]["reasoning"] == {"effort": "medium"}
    assert upstream_request["body"]["text"] == {"verbosity": "high"}
    assert upstream_request["headers"]["User-Agent"] == inbound_user_agent[:256]


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
    for canary in canaries.values():
        assert canary not in converter_log
