"""Hermetic request-ID validation coverage for translated and passthrough routes."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from tests.integration.proxy.conftest import FakeAnthropicUpstream, FakeOpenAIUpstream

pytestmark = pytest.mark.integration

_INVALID_REQUEST_ID = "D036_E2E_REQUEST/path"
_GENERATED_REQUEST_ID_RE = re.compile(r"^req_[0-9a-f]{12}$")


def _logs_and_telemetry_text(forge_home: Path) -> str:
    paths = [
        path for root_name in ("logs", "telemetry") for path in (forge_home / root_name).rglob("*") if path.is_file()
    ]
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths)


def _assert_sanitized_logs_and_telemetry(response: httpx.Response, forge_home: Path) -> None:
    request_id = response.headers["X-Request-ID"]
    assert _GENERATED_REQUEST_ID_RE.fullmatch(request_id)

    diagnostics = _logs_and_telemetry_text(forge_home)
    assert request_id in diagnostics
    assert _INVALID_REQUEST_ID not in diagnostics


def test_translated_route_replaces_invalid_client_request_id(
    proxy_server_fake_litellm_openai: tuple[str, FakeOpenAIUpstream],
    module_forge_home: Path,
) -> None:
    proxy_base_url, fake_upstream = proxy_server_fake_litellm_openai
    fake_upstream.requests.clear()

    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{proxy_base_url}/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Say hello"}],
            },
            headers={"x-api-key": "test", "x-request-id": _INVALID_REQUEST_ID},
        )

    assert response.status_code == 200, response.text[:500]
    assert len(fake_upstream.requests) == 1
    _assert_sanitized_logs_and_telemetry(response, module_forge_home)


def test_anthropic_passthrough_replaces_invalid_client_request_id(
    proxy_server_fake_anthropic_passthrough: tuple[str, FakeAnthropicUpstream],
    module_forge_home: Path,
) -> None:
    proxy_base_url, fake_upstream = proxy_server_fake_anthropic_passthrough
    fake_upstream.requests.clear()

    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{proxy_base_url}/v1/messages",
            json={
                "model": "claude-opus-4-6",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Say hello"}],
            },
            headers={"x-api-key": "test", "x-request-id": _INVALID_REQUEST_ID},
        )

    assert response.status_code == 529
    assert response.content == fake_upstream.response_body
    assert len(fake_upstream.requests) == 1
    _assert_sanitized_logs_and_telemetry(response, module_forge_home)
